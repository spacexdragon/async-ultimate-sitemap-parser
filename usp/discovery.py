"""Helpers for discovering sitemap URLs without fetching all content."""

import logging
import re
from collections import OrderedDict
from collections.abc import Callable

from .helpers import is_http_url, strip_url_to_homepage, ungzipped_response_content
from .helpers import get_url_retry_on_client_errors
from .objects.sitemap import IndexRobotsTxtSitemap, InvalidSitemap
from .web_client.abstract_client import AbstractWebClient, WebClientErrorResponse

log = logging.getLogger(__name__)


async def discover_sitemap_urls_from_robots(
    homepage_url: str,
    web_client: AbstractWebClient | None = None,
) -> list[str]:
    """
    Discover sitemap URLs from robots.txt without fetching their content.

    This function fetches only the robots.txt file and extracts the sitemap URLs
    listed in it. It does not fetch the actual sitemaps or their content.

    :param homepage_url: Homepage URL of a website, e.g. "http://www.example.com/".
    :param web_client: Custom web client implementation to use when fetching robots.txt.
        If ``None``, a :class:`~.RequestsWebClient` will be used.
    :return: List of sitemap URLs found in robots.txt.

    Example:
        >>> from usp.web_client.httpx_client import HttpxWebClient
        >>> web_client = HttpxWebClient()
        >>> sitemap_urls = await discover_sitemap_urls_from_robots(
        ...     "https://www.example.com",
        ...     web_client=web_client
        ... )
        >>> print(f"Found {len(sitemap_urls)} sitemaps")
        >>> for url in sitemap_urls:
        ...     print(f"  - {url}")
        >>> await web_client.close()
    """
    if not is_http_url(homepage_url):
        raise ValueError(f"URL {homepage_url} is not a HTTP(s) URL.")

    stripped_homepage_url = strip_url_to_homepage(url=homepage_url)
    if homepage_url != stripped_homepage_url:
        log.warning(
            f"Assuming that the homepage of {homepage_url} is {stripped_homepage_url}"
        )
        homepage_url = stripped_homepage_url

    if not homepage_url.endswith("/"):
        homepage_url += "/"
    robots_txt_url = homepage_url + "robots.txt"

    if not web_client:
        from .web_client.requests_client import RequestsWebClient

        web_client = RequestsWebClient()

    # Fetch robots.txt
    log.info(f"Fetching robots.txt from {robots_txt_url}...")
    response = await get_url_retry_on_client_errors(
        url=robots_txt_url, web_client=web_client
    )

    if isinstance(response, WebClientErrorResponse):
        log.warning(f"Failed to fetch robots.txt: {response.message()}")
        return []

    # Parse robots.txt content
    content = ungzipped_response_content(url=robots_txt_url, response=response)

    # Extract sitemap URLs using the same regex as IndexRobotsTxtSitemapParser
    sitemap_urls = OrderedDict()
    for line in content.splitlines():
        line = line.strip()
        sitemap_match = re.search(r"^site-?map:\s*(.+?)$", line, flags=re.IGNORECASE)
        if sitemap_match:
            sitemap_url = sitemap_match.group(1)
            if is_http_url(sitemap_url):
                sitemap_urls[sitemap_url] = True
            else:
                log.warning(
                    f"Sitemap URL {sitemap_url} doesn't look like a URL, skipping"
                )

    return list(sitemap_urls.keys())
