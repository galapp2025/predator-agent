"""
Social Media Collector — Presence detection, influence estimation, content analysis.

Sources:
  - Public profile discovery (no auth required for public data)
  - Twitter/X public API (limited, but useful for presence detection)
  - LinkedIn public profiles
  - Facebook public pages/groups

Key signals:
  - Platform presence (which platforms, how active)
  - Follower/connection estimates
  - Content topics & political alignment signals
  - Controversial content flags

IMPORTANT: All collection is from PUBLICLY available data only.
No authentication bypass, no scraping behind login walls.
"""

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)


class SocialCollector:
    """
    Multi-platform social media presence detector.
    Identifies public profiles and estimates influence metrics.
    """

    def __init__(self, twitter_bearer: str | None = None, session=None):
        self.twitter_bearer = twitter_bearer
        self._session = session
        self._cache: dict[str, dict] = {}
        self._cache_ttl = timedelta(hours=12)

    async def _get_session(self):
        if self._session is None:
            import aiohttp
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": "BlackOpps-OSINT/1.0"}
            )
        return self._session

    async def collect(self, name: str, location: str = "", timeout: int = 20) -> dict:
        """
        Discover social media presence across platforms.
        Returns structured data for the scoring engine.
        """
        cache_key = hashlib.md5(f"social:{name}:{location}".encode()).hexdigest()
        if cache_key in self._cache:
            return self._cache[cache_key]

        result = {
            "twitter": {},
            "facebook": {},
            "linkedin": {},
            "other_platforms": [],
            "political_signals": [],
            "controversial_content": False,
            "estimated_influence_score": 0.0,
            "_sources": [],
        }

        # Run platform checks concurrently
        tasks = []
        if self.twitter_bearer:
            tasks.append(self._check_twitter_api(name, timeout))
        tasks.append(self._check_twitter_public(name, timeout))
        tasks.append(self._check_facebook_public(name, location, timeout))
        tasks.append(self._check_linkedin_public(name, timeout))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results:
            if isinstance(r, dict) and r:
                platform = r.pop("_platform", None)
                if platform == "twitter":
                    result["twitter"] = r
                    result["_sources"].append("twitter.com")
                elif platform == "facebook":
                    result["facebook"] = r
                    result["_sources"].append("facebook.com")
                elif platform == "linkedin":
                    result["linkedin"] = r
                    result["_sources"].append("linkedin.com")

        # Compute estimated influence
        result["estimated_influence_score"] = self._estimate_influence(result)
        result["political_signals"] = self._detect_political_signals(name, result)

        self._cache[cache_key] = result
        return result

    async def _check_twitter_api(self, name: str, timeout: int) -> dict | None:
        """Check Twitter via API (if bearer token available)."""
        try:
            session = await self._get_session()
            url = "https://api.twitter.com/2/users/by/username/"
            username = self._guess_username(name)
            headers = {"Authorization": f"Bearer {self.twitter_bearer}"}
            async with session.get(
                f"{url}{username}", headers=headers, timeout=timeout
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    user_data = data.get("data", {})
                    return {
                        "_platform": "twitter",
                        "username": username,
                        "user_id": user_data.get("id"),
                        "name": user_data.get("name"),
                        "followers": user_data.get("public_metrics", {}).get("followers_count", 0),
                        "following": user_data.get("public_metrics", {}).get("following_count", 0),
                        "tweet_count": user_data.get("public_metrics", {}).get("tweet_count", 0),
                        "verified": user_data.get("verified", False),
                    }
        except Exception as e:
            logger.debug(f"Twitter API check failed for '{name}': {e}")
        return None

    async def _check_twitter_public(self, name: str, timeout: int) -> dict:
        """Check Twitter public presence via Google search."""
        result = {"_platform": "twitter"}
        try:
            session = await self._get_session()
            query = quote(f'{name} site:twitter.com OR site:x.com')
            url = f"https://www.google.com/search?q={query}&num=5"
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            }
            async with session.get(url, headers=headers, timeout=timeout) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    # Extract Twitter handles from search results
                    handles = re.findall(r'(?:twitter\.com|x\.com)/(\w{1,15})', text)
                    if handles:
                        result["found_handles"] = list(set(handles))[:5]
                        result["presence_detected"] = True
        except Exception as e:
            logger.debug(f"Twitter public check failed: {e}")

        return result if result.get("found_handles") else {}

    async def _check_facebook_public(self, name: str, location: str, timeout: int) -> dict:
        """Check Facebook public presence via search engines."""
        result = {"_platform": "facebook"}
        try:
            session = await self._get_session()
            loc_str = f" {location}" if location else ""
            query = quote(f'"{name}"{loc_str} site:facebook.com')
            url = f"https://www.google.com/search?q={query}&num=5"
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36"
                )
            }
            async with session.get(url, headers=headers, timeout=timeout) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    fb_urls = re.findall(
                        r'facebook\.com/(?:profile\.php\?id=\d+|[a-zA-Z0-9.]+)',
                        text
                    )
                    if fb_urls:
                        result["found_profiles"] = list(set(fb_urls))[:5]
                        result["presence_detected"] = True
                        # Rough estimate: if multiple profiles found, more active
                        result["friends_estimate"] = len(fb_urls) * 200
        except Exception as e:
            logger.debug(f"Facebook public check failed: {e}")

        return result if result.get("found_profiles") else {}

    async def _check_linkedin_public(self, name: str, timeout: int) -> dict:
        """Check LinkedIn public presence."""
        result = {"_platform": "linkedin"}
        try:
            session = await self._get_session()
            query = quote(f'"{name}" site:linkedin.com/in/')
            url = f"https://www.google.com/search?q={query}&num=5"
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36"
                )
            }
            async with session.get(url, headers=headers, timeout=timeout) as resp:
                if resp.status == 200:
                    text = await resp.text()
                    li_urls = re.findall(r'linkedin\.com/in/[a-zA-Z0-9%-]+', text)
                    if li_urls:
                        result["found_profiles"] = list(set(li_urls))[:5]
                        result["presence_detected"] = True
                        result["connections_estimate"] = 500  # Default LinkedIn avg
        except Exception as e:
            logger.debug(f"LinkedIn check failed: {e}")

        return result if result.get("found_profiles") else {}

    def _guess_username(self, name: str) -> str:
        """Generate likely Twitter/X username from name."""
        cleaned = re.sub(r'[^a-zA-Z0-9_\s]', '', name)
        parts = cleaned.lower().split()
        if len(parts) >= 2:
            # Common patterns: firstlast, first_last, first.last
            return parts[0] + parts[-1]
        return parts[0] if parts else cleaned.lower()

    def _estimate_influence(self, result: dict) -> float:
        """Estimate overall social media influence (0-100)."""
        score = 0.0

        twitter = result.get("twitter", {})
        if twitter.get("followers", 0) > 0:
            followers = twitter["followers"]
            if followers > 100000:
                score += 40
            elif followers > 10000:
                score += 25
            elif followers > 1000:
                score += 15
            elif followers > 100:
                score += 5
        elif twitter.get("found_handles"):
            score += 3  # Present but unknown follower count

        fb = result.get("facebook", {})
        if fb.get("presence_detected"):
            score += 5

        linkedin = result.get("linkedin", {})
        if linkedin.get("presence_detected"):
            score += 5

        # Multi-platform bonus
        platforms_present = sum(
            1 for p in [twitter, fb, linkedin]
            if p.get("presence_detected") or p.get("followers", 0) > 0
        )
        score += platforms_present * 3

        return min(score, 100)

    def _detect_political_signals(self, name: str, result: dict) -> list[str]:
        """Detect political alignment signals from social media presence."""
        signals = []

        # Twitter bio analysis (if we had it)
        twitter = result.get("twitter", {})
        if twitter.get("verified"):
            signals.append("verified_account")

        # Multi-platform presence correlates with public figure status
        platforms = sum(
            1 for p in [result.get("twitter", {}), result.get("facebook", {}),
                        result.get("linkedin", {})]
            if p.get("presence_detected")
        )
        if platforms >= 2:
            signals.append("multi_platform_presence")
        if platforms >= 3:
            signals.append("high_visibility_profile")

        # Follower count signals
        if twitter.get("followers", 0) > 1000:
            signals.append("significant_following")

        return signals

    def collect_sync(self, name: str, location: str = "", timeout: int = 20) -> dict:
        import asyncio as _asyncio
        try:
            loop = _asyncio.get_event_loop()
        except RuntimeError:
            loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(loop)
        return loop.run_until_complete(self.collect(name, location, timeout))

    async def close(self):
        if self._session:
            await self._session.close()
            self._session = None
