"""Parametrized tests for both RequestsWebClient and HttpxWebClient."""

import logging
import re
import socket
from http import HTTPStatus

import pytest
import respx
from httpx import Response as HttpxResponse

from usp import __version__
from usp.web_client.abstract_client import (
    AbstractWebClientSuccessResponse,
    WebClientErrorResponse,
)
from usp.web_client.httpx_client import HttpxWebClient
from usp.web_client.requests_client import RequestsWebClient


class TestWebClients:
    """Test suite for both web clients."""

    TEST_BASE_URL = "http://test-ultimate-sitemap-parser.com"
    TEST_CONTENT_TYPE = "text/html"

    @pytest.fixture(params=["requests", "httpx"])
    def client_setup(self, request, requests_mock):
        """Parametrized fixture that returns client and appropriate mock."""
        client_type = request.param

        if client_type == "requests":
            return RequestsWebClient(), requests_mock, "requests"
        else:
            return HttpxWebClient(), None, "httpx"

    @respx.mock
    async def test_get(self, client_setup):
        """Test basic GET request."""
        client, requests_mocker, client_type = client_setup

        test_url = self.TEST_BASE_URL + "/"
        test_content = "This is a homepage."

        if client_type == "requests":
            requests_mocker.get(
                test_url,
                headers={"Content-Type": self.TEST_CONTENT_TYPE},
                text=test_content,
            )
        else:
            respx.get(test_url).mock(
                return_value=HttpxResponse(
                    200,
                    headers={"Content-Type": self.TEST_CONTENT_TYPE},
                    text=test_content,
                )
            )

        response = await client.get(test_url)

        assert response
        assert isinstance(response, AbstractWebClientSuccessResponse)
        assert response.status_code() == HTTPStatus.OK.value
        assert response.status_message() == HTTPStatus.OK.phrase
        assert response.header("Content-Type") == self.TEST_CONTENT_TYPE
        assert response.header("content-type") == self.TEST_CONTENT_TYPE
        assert response.header("nonexistent") is None
        assert response.raw_data().decode("utf-8") == test_content

    @respx.mock
    async def test_get_user_agent(self, client_setup):
        """Test that User-Agent header is set correctly."""
        client, requests_mocker, client_type = client_setup

        test_url = self.TEST_BASE_URL + "/"

        if client_type == "requests":

            def content_user_agent(request, context):
                context.status_code = HTTPStatus.OK.value
                return request.headers.get("User-Agent", "unknown")

            requests_mocker.get(test_url, text=content_user_agent)
        else:

            def httpx_user_agent(request):
                user_agent = request.headers.get("User-Agent", "unknown")
                return HttpxResponse(200, text=user_agent)

            respx.get(test_url).mock(side_effect=httpx_user_agent)

        response = await client.get(test_url)

        assert response
        assert isinstance(response, AbstractWebClientSuccessResponse)

        content = response.raw_data().decode("utf-8")
        assert content == f"ultimate_sitemap_parser/{__version__}"

    @respx.mock
    async def test_get_not_found(self, client_setup):
        """Test handling of 404 Not Found responses."""
        client, requests_mocker, client_type = client_setup

        test_url = self.TEST_BASE_URL + "/404.html"

        if client_type == "requests":
            requests_mocker.get(
                test_url,
                status_code=HTTPStatus.NOT_FOUND.value,
                reason=HTTPStatus.NOT_FOUND.phrase,
                headers={"Content-Type": self.TEST_CONTENT_TYPE},
                text="This page does not exist.",
            )
        else:
            respx.get(test_url).mock(
                return_value=HttpxResponse(
                    404,
                    headers={"Content-Type": self.TEST_CONTENT_TYPE},
                    text="This page does not exist.",
                )
            )

        response = await client.get(test_url)

        assert response
        assert isinstance(response, WebClientErrorResponse)
        assert response.retryable() is False

    async def test_get_nonexistent_domain(self):
        """Test handling of connection errors to nonexistent domains."""
        # Test both clients separately without mocking
        for client_class in [RequestsWebClient, HttpxWebClient]:
            client = client_class()
            test_url = "http://www.totallydoesnotexisthjkfsdhkfsd.com/some_page.html"

            response = await client.get(test_url)

            assert response
            assert isinstance(response, WebClientErrorResponse)
            assert response.retryable() is False
            # Both clients should report connection/resolution failures
            assert (
                re.search(
                    r"Failed to (establish a new connection|resolve)|"
                    r"Name or service not known|"
                    r"nodename nor servname provided|"
                    r"All connection attempts failed",
                    response.message(),
                )
                is not None
            )

    async def test_get_timeout(self):
        """Test timeout handling."""
        # Test both clients separately
        for client_class in [RequestsWebClient, HttpxWebClient]:
            sock = socket.socket()
            sock.bind(("", 0))
            socket_port = sock.getsockname()[1]
            assert socket_port
            sock.listen(1)

            test_timeout = 1
            test_url = f"http://127.0.0.1:{socket_port}/slow_page.html"

            client = client_class()
            client.set_timeout(test_timeout)

            response = await client.get(test_url)

            sock.close()

            assert response
            assert isinstance(response, WebClientErrorResponse)
            assert response.retryable() is True
            # Both clients should report timeout (or empty message for httpx)
            # RequestsWebClient provides "Read timed out" message
            # HttpxWebClient may have empty message from TimeoutException
            message = response.message().lower()
            assert (
                "timed out" in message
                or "timeout" in message
                or message == ""  # httpx TimeoutException can have empty string
            )

    @respx.mock
    async def test_get_max_response_data_length(self, client_setup):
        """Test max response data length limiting."""
        client, requests_mocker, client_type = client_setup

        actual_length = 1024 * 1024
        max_length = 1024 * 512

        test_url = self.TEST_BASE_URL + "/huge_page.html"
        test_content = "a" * actual_length

        if client_type == "requests":
            requests_mocker.get(
                test_url,
                headers={"Content-Type": self.TEST_CONTENT_TYPE},
                text=test_content,
            )
        else:
            respx.get(test_url).mock(
                return_value=HttpxResponse(
                    200,
                    headers={"Content-Type": self.TEST_CONTENT_TYPE},
                    text=test_content,
                )
            )

        client.set_max_response_data_length(max_length)

        response = await client.get(test_url)

        assert response
        assert isinstance(response, AbstractWebClientSuccessResponse)

        response_length = len(response.raw_data())
        assert response_length == max_length

    @respx.mock
    async def test_error_page_log(self, client_setup, caplog):
        """Test that error page content is logged at debug level."""
        client, requests_mocker, client_type = client_setup

        caplog.set_level(logging.DEBUG)
        test_url = self.TEST_BASE_URL + "/error_page.html"

        if client_type == "requests":
            requests_mocker.get(
                test_url,
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR.value,
                text="This page is broken.",
            )
        else:
            respx.get(test_url).mock(
                return_value=HttpxResponse(
                    500,
                    text="This page is broken.",
                )
            )

        await client.get(test_url)

        assert "Response content: This page is broken." in caplog.text

    async def test_no_request_wait(self, mocker):
        """Test that there's no wait when wait is not configured."""
        # Mock asyncio.sleep for httpx
        mocked_asyncio_sleep = mocker.patch("asyncio.sleep")
        # Mock time.sleep for requests
        mocked_time_sleep = mocker.patch("time.sleep")

        for client_class in [RequestsWebClient, HttpxWebClient]:
            client = client_class()
            # These will fail to connect but that's ok - we're testing wait behavior
            await client.get(self.TEST_BASE_URL + "/page1.html")
            await client.get(self.TEST_BASE_URL + "/page2.html")

        # Neither sleep should be called
        mocked_asyncio_sleep.assert_not_called()
        mocked_time_sleep.assert_not_called()

    async def test_request_wait(self, mocker):
        """Test that wait works correctly between requests."""
        # Mock asyncio.sleep for httpx
        mocked_asyncio_sleep = mocker.patch("asyncio.sleep")
        # Mock time.sleep for requests
        mocked_time_sleep = mocker.patch("time.sleep")

        # Test RequestsWebClient
        requests_client = RequestsWebClient(wait=1)
        await requests_client.get(self.TEST_BASE_URL + "/page1.html")
        mocked_time_sleep.assert_not_called()
        await requests_client.get(self.TEST_BASE_URL + "/page2.html")
        mocked_time_sleep.assert_called_once_with(1)

        # Reset mocks
        mocked_asyncio_sleep.reset_mock()
        mocked_time_sleep.reset_mock()

        # Test HttpxWebClient
        httpx_client = HttpxWebClient(wait=1)
        await httpx_client.get(self.TEST_BASE_URL + "/page1.html")
        mocked_asyncio_sleep.assert_not_called()
        await httpx_client.get(self.TEST_BASE_URL + "/page2.html")
        mocked_asyncio_sleep.assert_called_once_with(1)

    async def test_request_wait_random(self, mocker):
        """Test that random wait works correctly."""
        # Mock asyncio.sleep for httpx
        mocked_asyncio_sleep = mocker.patch("asyncio.sleep")
        # Mock time.sleep for requests
        mocked_time_sleep = mocker.patch("time.sleep")

        # Test RequestsWebClient
        requests_client = RequestsWebClient(wait=1, random_wait=True)
        await requests_client.get(self.TEST_BASE_URL + "/page1.html")
        await requests_client.get(self.TEST_BASE_URL + "/page2.html")

        mocked_time_sleep.assert_called_once()
        wait_time = mocked_time_sleep.call_args[0][0]
        assert 0.5 <= wait_time <= 1.5
        assert wait_time != 1  # Should not be exactly 1 (very unlikely with random)

        # Reset mocks
        mocked_asyncio_sleep.reset_mock()
        mocked_time_sleep.reset_mock()

        # Test HttpxWebClient
        httpx_client = HttpxWebClient(wait=1, random_wait=True)
        await httpx_client.get(self.TEST_BASE_URL + "/page1.html")
        await httpx_client.get(self.TEST_BASE_URL + "/page2.html")

        mocked_asyncio_sleep.assert_called_once()
        wait_time = mocked_asyncio_sleep.call_args[0][0]
        assert 0.5 <= wait_time <= 1.5
        assert wait_time != 1  # Should not be exactly 1 (very unlikely with random)


class TestHttpxClientSpecific:
    """Tests specific to HttpxWebClient."""

    TEST_BASE_URL = "http://test-ultimate-sitemap-parser.com"

    def test_http2_enabled_by_default(self):
        """Test that HTTP/2 is enabled by default."""
        client = HttpxWebClient()
        # Check internal state - HTTP/2 should be enabled
        assert client._HttpxWebClient__http2 is True

    def test_http2_can_be_disabled(self):
        """Test that HTTP/2 can be disabled."""
        client = HttpxWebClient(http2=False)
        assert client._HttpxWebClient__http2 is False

    def test_set_proxy(self):
        """Test proxy configuration."""
        client = HttpxWebClient()
        test_proxy = "http://proxy.example.com:8080"
        client.set_proxy(test_proxy)

        # Verify proxy was set
        assert client._HttpxWebClient__proxy == test_proxy

    def test_verify_ssl_disabled(self):
        """Test that SSL verification can be disabled."""
        client = HttpxWebClient(verify=False)
        assert client._HttpxWebClient__verify is False


class TestRequestsClientSpecific:
    """Tests specific to RequestsWebClient."""

    def test_custom_session(self):
        """Test that a custom session can be provided."""
        import requests

        custom_session = requests.Session()
        client = RequestsWebClient(session=custom_session)

        # Verify the session is being used
        assert client._RequestsWebClient__session == custom_session

    def test_set_proxies(self):
        """Test proxy configuration for requests client."""
        client = RequestsWebClient()
        test_proxies = {
            "http": "http://proxy.example.com:8080",
            "https": "https://proxy.example.com:8080",
        }
        client.set_proxies(test_proxies)

        # Verify proxies were set
        assert client._RequestsWebClient__proxies == test_proxies
