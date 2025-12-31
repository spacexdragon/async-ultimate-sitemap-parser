import re
from unittest import mock
from unittest.mock import AsyncMock

import pytest

from tests.tree.base import TreeTestBase
from usp.objects.sitemap import InvalidSitemap
from usp.tree import sitemap_tree_for_homepage


class TestTreeOpts(TreeTestBase):
    @pytest.fixture
    def mock_fetcher(self, mocker):
        mock_fetcher_instance = mocker.patch("usp.tree.SitemapFetcher")
        # Make the sitemap() method async
        mock_fetcher_instance.return_value.sitemap = AsyncMock(
            return_value=InvalidSitemap(url="test", reason="test")
        )
        return mock_fetcher_instance

    async def test_extra_known_paths(self, mock_fetcher):
        await sitemap_tree_for_homepage(
            "https://example.org", extra_known_paths={"custom_sitemap.xml"}
        )
        mock_fetcher.assert_any_call(
            url="https://example.org/custom_sitemap.xml",
            web_client=mock.ANY,
            recursion_level=0,
            parent_urls=set(),
            quiet_404=True,
            recurse_callback=None,
            recurse_list_callback=None,
            sitemap_chain=[],
        )

    async def test_filter_callback(self, requests_mock):
        self.init_basic_sitemap(requests_mock)

        def recurse_callback(
            url: str, recursion_level: int, parent_urls: set[str]
        ) -> bool:
            return re.search(r"news_\d", url) is None

        tree = await sitemap_tree_for_homepage(
            self.TEST_BASE_URL, recurse_callback=recurse_callback
        )

        # robots, pages, news_index_1, news_index_2, missing
        assert len(list(tree.all_sitemaps())) == 5
        assert all("/news/" not in page.url for page in tree.all_pages())

    async def test_filter_list_callback(self, requests_mock):
        self.init_basic_sitemap(requests_mock)

        def recurse_list_callback(
            urls: list[str], recursion_level: int, parent_urls: set[str]
        ) -> list[str]:
            return [url for url in urls if re.search(r"news_\d", url) is None]

        tree = await sitemap_tree_for_homepage(
            self.TEST_BASE_URL, recurse_list_callback=recurse_list_callback
        )

        # robots, pages, news_index_1, news_index_2, missing
        assert len(list(tree.all_sitemaps())) == 5
        assert all("/news/" not in page.url for page in tree.all_pages())
