"""Tests for sitemap discovery helpers."""

import pytest

from usp.discovery import discover_sitemap_urls_from_robots


class TestDiscovery:
    """Test discovery helpers."""

    async def test_discover_sitemap_urls_from_robots(self, requests_mock):
        """Test discovering sitemap URLs from robots.txt without fetching content."""
        robots_content = """Sitemap: https://www.example.com/sitemap1.xml
Sitemap: https://www.example.com/sitemap2.xml
Sitemap: https://www.example.com/news/sitemap.xml
User-agent: *
Disallow: /admin/
"""
        requests_mock.get(
            "https://www.example.com/robots.txt",
            text=robots_content,
        )

        sitemap_urls = await discover_sitemap_urls_from_robots(
            "https://www.example.com"
        )

        assert len(sitemap_urls) == 3
        assert "https://www.example.com/sitemap1.xml" in sitemap_urls
        assert "https://www.example.com/sitemap2.xml" in sitemap_urls
        assert "https://www.example.com/news/sitemap.xml" in sitemap_urls

    async def test_discover_empty_robots(self, requests_mock):
        """Test discovering from robots.txt with no sitemaps."""
        robots_content = """User-agent: *
Disallow: /admin/
"""
        requests_mock.get(
            "https://www.example.com/robots.txt",
            text=robots_content,
        )

        sitemap_urls = await discover_sitemap_urls_from_robots(
            "https://www.example.com"
        )

        assert len(sitemap_urls) == 0

    async def test_discover_robots_404(self, requests_mock):
        """Test discovering when robots.txt returns 404."""
        requests_mock.get(
            "https://www.example.com/robots.txt",
            status_code=404,
        )

        sitemap_urls = await discover_sitemap_urls_from_robots(
            "https://www.example.com"
        )

        assert len(sitemap_urls) == 0
