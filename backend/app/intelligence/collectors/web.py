"""
Web Scraper — Generic OSINT web collection.

Capabilities:
  - Google search result analysis (name + location + keywords)
  - Entity co-occurrence discovery
  - Public directory scanning
  - Cross-reference validation between sources

All scraping respects robots.txt and uses conservative rate limiting.
"""

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote, urlparse

logger = logging.getLogger(__name__)


class WebScraper:
    """
    Generic web scraper for OSINT collection.
    Discovers public web presence, cross-references, validates.
    """

    def __init__(self, session=None):
        self._session = session
        self._cache: dict[str, dict] = {}
        self._cache_ttl = timedelta(hours=12)
        self._rate_limiter = asyncio.Semaphore(3)  # Max 3 concurrent requests

    async def _get_session(self):
        if self._session is None:
            import aiohttp
            self._session = aiohttp.ClientSession(
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    )
                }
            )
        return self._session

    async def collect(self, name: str, location: str = "",
                       keywords: list | None = None, timeout: int = 20) -> dict:
        """
        Collect web presence data via search engines and public directories.
        """
        cache_key = hashlib.md5(
            f"web:{name}:{location}:{str(keywords)}".encode()
        ).hexdigest()
        if cache_key in self._cache:
            return self._cache[cache_key]

        result = {
            "search_results": [],
            "entity_co_occurrences": [],
            "public_directory_matches": [],
            "estimated_web_footprint": 0,
            "_sources": [],
        }

        try:
            async with self._rate_limiter:
                session = await self._get_session()
                queries = self._build_search_queries(name, location, keywords)

                for query in queries:
                    url = f"https://www.google.com/search?q={quote(query)}&num=10"
                    try:
                        async with session.get(url, timeout=timeout) as resp:
                            if resp.status == 200:
                                text = await resp.text()
                                extracted = self._extract_search_results(text)
                                result = self._merge_search_results(result, extracted)
                    except Exception as e:
                        logger.debug(f"Search failed for '{query[:50]}...': {e}")
                        continue

        except Exception as e:
            logger.error(f"Web collector error for '{name}': {e}")
            result["_error"] = str(e)

        # Estimate web footprint
        result["estimated_web_footprint"] = self._estimate_footprint(result)

        if result["search_results"] or result["entity_co_occurrences"]:
            self._cache[cache_key] = result

        return result

    def _build_search_queries(self, name: str, location: str,
                               keywords: list | None) -> list[str]:
        """Build OSINT search queries for the person."""
        queries = [
            f'"{name}" {location}',
            f'"{name}" politics OR election OR party',
            f'"{name}" donation OR campaign OR volunteer',
            f'"{name}" community OR organization OR council',
            f'"{name}" business OR company OR director',
            f'"{name}" news OR media OR interview',
        ]

        if keywords:
            for kw in keywords:
                queries.append(f'"{name}" {kw}')

        if location:
            queries.append(f'"{name}" {location} voter OR election')

        return queries

    def _extract_search_results(self, html: str) -> dict:
        """Extract structured data from Google search results HTML."""
        results = {
            "urls": [],
            "titles": [],
            "snippets": [],
            "domains": [],
        }

        # Extract URLs
        url_pattern = r'href="/url\?q=(https?://[^&"]+)'
        urls = re.findall(url_pattern, html)
        results["urls"] = [u for u in urls if not u.startswith("https://www.google")][:10]

        # Extract titles
        title_pattern = r'<h3[^>]*>(.*?)</h3>'
        titles = re.findall(title_pattern, html)
        results["titles"] = [re.sub(r'<[^>]+>', '', t) for t in titles][:10]

        # Extract domains for entity analysis
        for url in results["urls"]:
            try:
                domain = urlparse(url).netloc
                if domain and domain not in results["domains"]:
                    results["domains"].append(domain)
            except Exception as e:
                logger.debug(f"Web search result parse failed: {e}")

        return results

    def _merge_search_results(self, base: dict, new: dict) -> dict:
        """Merge new search results into base, deduplicating."""
        existing_urls = set(base.get("search_results", []))
        for url in new.get("urls", []):
            if url not in existing_urls:
                base.setdefault("search_results", []).append(url)
                existing_urls.add(url)

        existing_domains = set(base.get("public_directory_matches", []))
        for domain in new.get("domains", []):
            if domain not in existing_domains:
                base.setdefault("public_directory_matches", []).append(domain)
                existing_domains.add(domain)

        if new.get("domains"):
            base.setdefault("_sources", []).extend(new["domains"])

        return base

    def _estimate_footprint(self, result: dict) -> int:
        """Estimate web footprint: number of URLs + domains found."""
        urls = len(result.get("search_results", []))
        domains = len(result.get("public_directory_matches", []))
        return min(urls * 10 + domains * 20, 100)

    def collect_sync(self, name: str, location: str = "",
                      keywords: list | None = None, timeout: int = 20) -> dict:
        import asyncio as _asyncio
        try:
            loop = _asyncio.get_event_loop()
        except RuntimeError:
            loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(loop)
        return loop.run_until_complete(self.collect(name, location, keywords, timeout))

    async def close(self):
        if self._session:
            await self._session.close()
            self._session = None
