"""Implementation of :mod:`usp.web_client.abstract_client` with Httpx and HTTP/2."""

import asyncio
import logging
import random
from http import HTTPStatus

import httpx

from usp import __version__

from .abstract_client import (
    RETRYABLE_HTTP_STATUS_CODES,
    AbstractWebClient,
    AbstractWebClientResponse,
    AbstractWebClientSuccessResponse,
    WebClientErrorResponse,
)

log = logging.getLogger(__name__)


class HttpxWebClientSuccessResponse(AbstractWebClientSuccessResponse):
    """
    httpx-based successful response.
    """

    __slots__ = [
        "__httpx_response",
        "__max_response_data_length",
    ]

    def __init__(
        self,
        httpx_response: httpx.Response,
        max_response_data_length: int | None = None,
    ):
        """
        :param httpx_response: Response data
        :param max_response_data_length: Maximum data length, or ``None`` to not restrict.
        """
        self.__httpx_response = httpx_response
        self.__max_response_data_length = max_response_data_length

    def status_code(self) -> int:
        return int(self.__httpx_response.status_code)

    def status_message(self) -> str:
        message = self.__httpx_response.reason_phrase
        if not message:
            message = HTTPStatus(self.status_code()).phrase
        return message

    def header(self, case_insensitive_name: str) -> str | None:
        return self.__httpx_response.headers.get(case_insensitive_name.lower(), None)

    def raw_data(self) -> bytes:
        if self.__max_response_data_length:
            data = self.__httpx_response.content[: self.__max_response_data_length]
        else:
            data = self.__httpx_response.content

        return data

    def url(self) -> str:
        return str(self.__httpx_response.url)


class HttpxWebClientErrorResponse(WebClientErrorResponse):
    """
    Error response from the Httpx client.
    """

    pass


class HttpxWebClient(AbstractWebClient):
    """httpx-based web client with HTTP/2 support to be used by the sitemap fetcher."""

    __USER_AGENT = f"ultimate_sitemap_parser/{__version__}"

    __HTTP_REQUEST_TIMEOUT = httpx.Timeout(60.0, connect=9.05)
    """
    HTTP request timeout.

    Some webservers might be generating huge sitemaps on the fly, so this is why it's rather big.
    """

    __slots__ = [
        "__max_response_data_length",
        "__timeout",
        "__proxy",
        "__verify",
        "__wait",
        "__random_wait",
        "__is_first_request",
        "__http2",
    ]

    def __init__(
        self,
        verify: bool = True,
        wait: float | None = None,
        random_wait: bool = False,
        http2: bool = True,
    ):
        """
        :param verify: whether certificates should be verified for HTTPS requests.
        :param wait: time to wait between requests, in seconds.
        :param random_wait: if true, wait time is multiplied by a random number between 0.5 and 1.5.
        :param http2: whether to enable HTTP/2 support (default: True).
        """
        self.__max_response_data_length = None
        self.__timeout = self.__HTTP_REQUEST_TIMEOUT
        self.__proxy = None
        self.__verify = verify
        self.__wait = wait or 0
        self.__random_wait = random_wait
        self.__is_first_request = True
        self.__http2 = http2
        self.__client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self.__client is None:
            self.__client = httpx.AsyncClient(
                http2=self.__http2,
                verify=self.__verify,
                timeout=self.__timeout,
                proxy=self.__proxy,
                headers={"User-Agent": self.__USER_AGENT},
                follow_redirects=True,
            )
        return self.__client

    def set_timeout(self, timeout: float | httpx.Timeout | None) -> None:
        """Set HTTP request timeout.

        See also: `HTTPX timeout docs <https://www.python-httpx.org/advanced/#timeout-configuration>`__

        :param timeout: A float to use as the total timeout, an httpx.Timeout object
            for fine-grained control, or None for no timeout.
        """
        if isinstance(timeout, int | float):
            self.__timeout = httpx.Timeout(timeout)
        else:
            self.__timeout = timeout

    def set_proxy(self, proxy: str | None) -> None:
        """
        Set a proxy for the request.

        :param proxy: Proxy URL (e.g., 'http://user:pass@10.10.1.10:3128/'),
            or None to disable proxy.
        """
        self.__proxy = proxy

    def set_max_response_data_length(
        self, max_response_data_length: int | None
    ) -> None:
        self.__max_response_data_length = max_response_data_length

    async def __wait_if_needed(self) -> None:
        """Perform a wait if needed. Should be called before each request.

        Will skip wait if this is the first request.
        """
        if self.__wait == 0:
            return

        if self.__is_first_request:
            self.__is_first_request = False
            return

        wait_f = 1.0
        if self.__random_wait:
            wait_f = random.uniform(0.5, 1.5)

        await asyncio.sleep(self.__wait * wait_f)

    async def get(self, url: str) -> AbstractWebClientResponse:
        """
        Fetch a URL and return a response.

        :param url: URL to fetch.
        :return: Response object.
        """
        await self.__wait_if_needed()

        try:
            client = self._get_client()
            response = await client.get(url)

        except httpx.TimeoutException as ex:
            # Retryable timeouts
            return HttpxWebClientErrorResponse(message=str(ex), retryable=True)

        except httpx.HTTPError as ex:
            # Other errors, e.g. connection errors, redirect loops
            return HttpxWebClientErrorResponse(message=str(ex), retryable=False)

        else:
            if 200 <= response.status_code < 300:
                return HttpxWebClientSuccessResponse(
                    httpx_response=response,
                    max_response_data_length=self.__max_response_data_length,
                )
            else:
                message = f"{response.status_code} {response.reason_phrase}"
                log.debug(f"Response content: {response.text}")

                if response.status_code in RETRYABLE_HTTP_STATUS_CODES:
                    return HttpxWebClientErrorResponse(message=message, retryable=True)
                else:
                    return HttpxWebClientErrorResponse(message=message, retryable=False)

    async def close(self) -> None:
        """Close the underlying client."""
        if self.__client is not None:
            await self.__client.aclose()
            self.__client = None
