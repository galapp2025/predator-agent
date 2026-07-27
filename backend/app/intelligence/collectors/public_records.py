"""
Public Records Collector — Voter history, campaign contributions, property, business.

Sources:
  - OpenCorporates API (free tier: company directorships & registrations)
  - Public campaign finance databases
  - Property registry data (where publicly available)
  - Government contract databases

All data sourced from PUBLIC records only.
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)

OPENCORPORATES_BASE = "https://api.opencorporates.com/v0.4"


class PublicRecordsCollector:
    """
    Collects public records data: business registrations, property, campaign finance.
    """

    def __init__(self, opencorporates_key: str | None = None, session=None):
        self.opencorporates_key = opencorporates_key
        self._session = session
        self._cache: dict[str, dict] = {}
        self._cache_ttl = timedelta(hours=24)

    async def _get_session(self):
        if self._session is None:
            import aiohttp
            self._session = aiohttp.ClientSession(
                headers={"User-Agent": "BlackOpps-OSINT/1.0"}
            )
        return self._session

    async def collect(self, name: str, jurisdiction: str = "il",
                       timeout: int = 20) -> dict:
        """
        Collect all public records for a person.
        """
        cache_key = hashlib.md5(f"records:{name}:{jurisdiction}".encode()).hexdigest()
        if cache_key in self._cache:
            return self._cache[cache_key]

        result = {
            "business": {"companies": [], "director_roles": [], "conflict_indicators": []},
            "contributions": {"total_donated": 0, "donations": [], "recipients": []},
            "affiliation": {"party_member": False, "party_name": None, "party_role": None},
            "property": {"properties_owned": 0, "records": []},
            "voting_history": {"recent_elections": [], "consistency": "unknown"},
            "registration": {"registered": None, "registration_date": None},
            "civic": {"volunteer": False, "donor": False},
            "government": {"contracts": []},
            "wealth_indicators": {"estimated_net_worth_category": None, "public_filings": []},
            "_sources": [],
        }

        # Run record checks concurrently
        tasks = [
            self._check_opencorporates(name, jurisdiction, timeout),
            self._check_campaign_finance(name, jurisdiction, timeout),
            self._check_property(name, jurisdiction, timeout),
        ]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        for r in results_list:
            if isinstance(r, dict) and r:
                result = self._deep_merge(result, r)

        if result["_sources"]:
            self._cache[cache_key] = result

        return result

    async def _check_opencorporates(self, name: str, jurisdiction: str,
                                     timeout: int) -> dict:
        """Check OpenCorporates for company directorships and registrations."""
        result = {"_sources": []}
        try:
            session = await self._get_session()
            query = quote(name)
            params = {"q": query, "jurisdiction_code": jurisdiction}
            headers = {}
            if self.opencorporates_key:
                headers["Authorization"] = f"Token {self.opencorporates_key}"

            async with session.get(
                f"{OPENCORPORATES_BASE}/companies/search",
                params=params, headers=headers, timeout=timeout
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    companies = []
                    for comp in data.get("results", {}).get("companies", []):
                        c = comp.get("company", {})
                        companies.append({
                            "name": c.get("name"),
                            "jurisdiction": c.get("jurisdiction_code"),
                            "status": c.get("current_status"),
                            "incorporation_date": c.get("incorporation_date"),
                        })

                    result["business"] = {"companies": companies}
                    result["_sources"].append("opencorporates.com")

            # Also search officers (director roles)
            async with session.get(
                f"{OPENCORPORATES_BASE}/officers/search",
                params={"q": query, "jurisdiction_code": jurisdiction},
                headers=headers, timeout=timeout
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    roles = []
                    for off in data.get("results", {}).get("officers", []):
                        o = off.get("officer", {})
                        roles.append({
                            "company": o.get("company", {}).get("name"),
                            "position": o.get("position"),
                            "start_date": o.get("start_date"),
                            "end_date": o.get("end_date"),
                        })

                    if "business" not in result:
                        result["business"] = {}
                    result["business"]["director_roles"] = roles

        except Exception as e:
            logger.debug(f"OpenCorporates unavailable for '{name}': {e}")

        return result

    async def _check_campaign_finance(self, name: str, jurisdiction: str,
                                        timeout: int) -> dict:
        """
        Check campaign finance / political contributions.
        Jurisdiction-specific implementations would go here.
        For Israel: Rasham HaMiflagot, State Comptroller reports.
        """
        result = {"_sources": []}

        # This is a framework — jurisdiction-specific scrapers would be added here.
        # For now, return a structured placeholder that can be populated by
        # jurisdiction-specific implementations.

        # Israel-specific stub:
        if jurisdiction == "il":
            # GovData / data.gov.il may have campaign finance datasets
            try:
                session = await self._get_session()
                # Check Israeli open data portal for party registration
                # This is a minimal implementation — full implementation would
                # connect to specific government data APIs
                result["contributions"] = {
                    "total_donated": 0,
                    "donations": [],
                    "recipients": [],
                    "jurisdiction": "il",
                    "_note": "Full campaign finance data requires jurisdiction-specific API integration",
                }
                result["_sources"].append("data.gov.il (stub)")
            except Exception as e:
                logger.debug(f"Public records sub-collector failed: {e}")

        return result

    async def _check_property(self, name: str, jurisdiction: str,
                               timeout: int) -> dict:
        """
        Check property ownership records.
        Jurisdiction-specific. Israel: Tabu / Rasham Mekarkein.
        """
        result = {"_sources": []}

        # Property records are typically behind paywalls or require
        # specific government portal access. This is a structured stub.
        if jurisdiction == "il":
            result["property"] = {
                "properties_owned": 0,
                "records": [],
                "jurisdiction": "il",
                "_note": "Property registry requires authorized access to Tabu system",
            }
            result["_sources"].append("property.stub")

        return result

    def _deep_merge(self, base: dict, update: dict) -> dict:
        """Deep merge two dictionaries."""
        for key, value in update.items():
            if key == "_sources":
                base.setdefault("_sources", []).extend(
                    s for s in value if s not in base["_sources"]
                )
            elif key in base and isinstance(base[key], dict) and isinstance(value, dict):
                base[key] = self._deep_merge(base[key], value)
            elif key in base and isinstance(base[key], list) and isinstance(value, list):
                base[key].extend(value)
            else:
                base[key] = value
        return base

    def collect_sync(self, name: str, jurisdiction: str = "il",
                      timeout: int = 20) -> dict:
        import asyncio as _asyncio
        try:
            loop = _asyncio.get_event_loop()
        except RuntimeError:
            loop = _asyncio.new_event_loop()
            _asyncio.set_event_loop(loop)
        return loop.run_until_complete(self.collect(name, jurisdiction, timeout))

    async def close(self):
        if self._session:
            await self._session.close()
            self._session = None
