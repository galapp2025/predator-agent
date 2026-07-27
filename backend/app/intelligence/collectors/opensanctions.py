"""
OpenSanctions Collector — PEPs, sanctions, political connections, corporate ties.

API: https://api.opensanctions.org (free, rate-limited)
Coverage: 400+ sanctions lists, PEP databases, wanted lists, debarment lists.
Entity types: Person, Organization, Company, PoliticalParty.

Key signals extracted:
  - PEP status (Politically Exposed Person)
  - Sanctions list membership
  - Political roles & positions
  - Corporate directorships
  - Family/political connections
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)

OPEN_SANCTIONS_BASE = "https://api.opensanctions.org"


class OpenSanctionsCollector:
    """
    Collects sanctions, PEP, and political connection data from OpenSanctions.
    Free tier: 100 requests/day without API key.
    """

    def __init__(self, api_key: str | None = None, session=None):
        self.api_key = api_key
        self._session = session
        self._cache: dict[str, dict] = {}
        self._cache_ttl = timedelta(hours=24)
        self._cache_timestamps: dict[str, datetime] = {}

    async def _get_session(self):
        if self._session is None:
            import aiohttp
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": "BlackOpps-OSINT/1.0"}
            )
        return self._session

    async def collect(self, name: str, country: str = "il", timeout: int = 15) -> dict:
        """
        Collect all OpenSanctions data for a person name.
        Returns structured data for the scoring engine.
        """
        cache_key = hashlib.md5(f"{name}:{country}".encode()).hexdigest()

        if cache_key in self._cache:
            ts = self._cache_timestamps.get(cache_key)
            if ts and datetime.now() - ts < self._cache_ttl:
                return self._cache[cache_key]

        result = {
            "pep_status": None,
            "sanctions_count": 0,
            "sanctions_lists": [],
            "political_roles": [],
            "corporate_roles": [],
            "family_connections": [],
            "risk_indicators": [],
            "_sources": [],
        }

        try:
            session = await self._get_session()
            url = f"{OPEN_SANCTIONS_BASE}/search/default"
            params = {"q": name, "limit": 10}

            headers = {}
            if self.api_key:
                headers["Authorization"] = f"ApiKey {self.api_key}"

            async with session.get(
                url, params=params, headers=headers, timeout=timeout
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result = self._parse_results(data, result)
                    result["_sources"].append("opensanctions.org")
                elif resp.status == 429:
                    logger.warning("OpenSanctions rate limit hit")
                    result["_rate_limited"] = True
                else:
                    logger.warning(f"OpenSanctions HTTP {resp.status} for '{name}'")

        except asyncio.TimeoutError:
            logger.warning(f"OpenSanctions timeout for '{name}'")
            result["_timeout"] = True
        except Exception as e:
            logger.error(f"OpenSanctions error for '{name}': {e}")
            result["_error"] = str(e)

        self._cache[cache_key] = result
        self._cache_timestamps[cache_key] = datetime.now()
        return result

    def _parse_results(self, data: dict, result: dict) -> dict:
        """Parse OpenSanctions API response into structured intelligence."""
        for entity in data.get("results", []):
            schema = entity.get("schema", "")
            props = entity.get("properties", {})

            # PEP detection
            if schema == "Person" and entity.get("datasets", []):
                for ds in entity.get("datasets", []):
                    if any(tag in str(ds).lower() for tag in ["pep", "politically", "office"]):
                        result["pep_status"] = "confirmed"
                        country_list = props.get("country", [])
                        if country_list:
                            result["pep_countries"] = country_list

            # Political roles
            position = props.get("position", [])
            if position:
                result["political_roles"].extend(position)

            # Sanctions
            if schema == "Sanction":
                result["sanctions_count"] += 1
                program = props.get("program", "")
                if program:
                    result["sanctions_lists"].append(program)

            # Topics
            topics = props.get("topics", [])
            for topic in topics:
                if topic in ["role.pep", "role.rca", "sanction"]:
                    if topic not in result["risk_indicators"]:
                        result["risk_indicators"].append(topic)

            # Corporate roles
            if "director" in str(props.get("position", [])).lower():
                result["corporate_roles"].append(props.get("position", []))

            # Family connections (association entities)
            if schema == "Family" or "family" in str(props.get("keywords", [])).lower():
                result["family_connections"].append({
                    "name": props.get("name", [entity.get("caption", "")]),
                    "relationship": props.get("summary", ""),
                })

        return result

    def collect_sync(self, name: str, country: str = "il", timeout: int = 15) -> dict:
        """Synchronous wrapper for non-async contexts."""
        import asyncio as _asyncio
        try:
            loop = _asyncio.get_event_loop()
        except RuntimeError:
            loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(loop)
        return loop.run_until_complete(self.collect(name, country, timeout))

    async def close(self):
        if self._session:
            await self._session.close()
            self._session = None
