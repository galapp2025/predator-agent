"""
Enrichment Pipeline — Orchestrates full OSINT collection → scoring → alerting flow.

Usage:
  pipeline = EnrichmentPipeline()
  profiles = await pipeline.enrich(["ישראל ישראלי", "שרה כהן"])

Or sync:
  profiles = pipeline.enrich_sync(["ישראל ישראלי", "שרה כהן"])
"""

import asyncio
import logging
from typing import Optional

from .scoring import InfluenceScorer, InfluenceProfile
from .alerts import AlertManager
from .network import InfluenceNetwork
from .collectors.opensanctions import OpenSanctionsCollector
from .collectors.news import NewsCollector
from .collectors.social import SocialCollector
from .collectors.public_records import PublicRecordsCollector
from .collectors.web import WebScraper

logger = logging.getLogger(__name__)


class EnrichmentPipeline:
    """
    Full enrichment pipeline: collect → score → alert → network.

    Configurable:
      - Which collectors to enable
      - API keys for premium sources
      - Batch size for concurrent processing
      - Caching TTLs
    """

    def __init__(
        self,
        opensanctions_key: str | None = None,
        newsapi_key: str | None = None,
        twitter_bearer: str | None = None,
        opencorporates_key: str | None = None,
        enable_opensanctions: bool = True,
        enable_news: bool = True,
        enable_social: bool = True,
        enable_public_records: bool = True,
        enable_web_scraper: bool = True,
        batch_size: int = 10,
        scorer_weights: dict | None = None,
    ):
        self.batch_size = batch_size
        self.enable_opensanctions = enable_opensanctions
        self.enable_news = enable_news
        self.enable_social = enable_social
        self.enable_public_records = enable_public_records
        self.enable_web_scraper = enable_web_scraper

        # Initialize collectors
        self.opensanctions = OpenSanctionsCollector(api_key=opensanctions_key) if enable_opensanctions else None
        self.news = NewsCollector(newsapi_key=newsapi_key) if enable_news else None
        self.social = SocialCollector(twitter_bearer=twitter_bearer) if enable_social else None
        self.public_records = PublicRecordsCollector(opencorporates_key=opencorporates_key) if enable_public_records else None
        self.web = WebScraper() if enable_web_scraper else None

        # Scoring & intelligence
        self.scorer = InfluenceScorer(weights=scorer_weights)
        self.alert_manager = AlertManager()
        self.network = InfluenceNetwork()

        # State
        self._profiles: dict[str, InfluenceProfile] = {}
        self._raw_data: dict[str, dict] = {}

    async def enrich(self, names: list[str], location: str = "",
                      jurisdiction: str = "il", keywords: list | None = None,
                      enable_alerting: bool = True) -> list[InfluenceProfile]:
        """
        Full enrichment pipeline for a list of names.

        1. Collect OSINT from all enabled sources (concurrent per name)
        2. Score multi-dimensional influence
        3. Detect changes & generate alerts
        4. Update network graph

        Args:
            names: List of person names
            location: Geographic location for disambiguation
            jurisdiction: Legal jurisdiction (default: "il" for Israel)
            keywords: Additional search keywords
            enable_alerting: Whether to run change detection and alerts

        Returns:
            List of InfluenceProfile objects
        """
        profiles = []

        # Process in batches
        for i in range(0, len(names), self.batch_size):
            batch = names[i:i + self.batch_size]
            batch_profiles = await self._process_batch(
                batch, location, jurisdiction, keywords, enable_alerting
            )
            profiles.extend(batch_profiles)

        # Sort by composite score descending
        profiles.sort(key=lambda p: p.composite_score, reverse=True)
        return profiles

    async def _process_batch(self, names: list[str], location: str,
                              jurisdiction: str, keywords: list | None,
                              enable_alerting: bool) -> list[InfluenceProfile]:
        """Process a batch of names concurrently."""
        tasks = [
            self._enrich_single(name, location, jurisdiction, keywords, enable_alerting)
            for name in names
        ]
        return await asyncio.gather(*tasks)

    async def _enrich_single(self, name: str, location: str, jurisdiction: str,
                              keywords: list | None, enable_alerting: bool) -> InfluenceProfile:
        """Full enrichment for a single person."""
        logger.info(f"Enriching: {name}")

        # Phase 1: Collect from all sources concurrently
        collector_tasks = {}
        if self.opensanctions:
            collector_tasks["sanctions"] = self.opensanctions.collect(name, jurisdiction)
        if self.news:
            collector_tasks["news"] = self.news.collect(name)
        if self.social:
            collector_tasks["social"] = self.social.collect(name, location)
        if self.public_records:
            collector_tasks["public_records"] = self.public_records.collect(name, jurisdiction)
        if self.web:
            collector_tasks["web"] = self.web.collect(name, location, keywords)

        collected = {}
        if collector_tasks:
            results = await asyncio.gather(*collector_tasks.values(), return_exceptions=True)
            for key, result in zip(collector_tasks.keys(), results):
                if isinstance(result, Exception):
                    logger.warning(f"Collector '{key}' failed for '{name}': {result}")
                    collected[key] = {"_error": str(result)}
                else:
                    collected[key] = result or {}

        # Merge all sources into a single data dict
        merged_data = self._merge_collected_data(collected, name, location)
        self._raw_data[name] = merged_data

        # Phase 2: Score
        profile = self.scorer.score(name, merged_data)
        self._profiles[name] = profile

        # Phase 3: Alerting
        if enable_alerting:
            snapshot = self.alert_manager.take_snapshot(name, profile)
            changes = self.alert_manager.detect_changes(name, profile)
            sanctions_alert = self.alert_manager.check_sanctions_alert(
                name, collected.get("sanctions", {})
            )
            if sanctions_alert:
                changes.append(sanctions_alert)
            news_alert = self.alert_manager.check_news_surge(
                name, collected.get("news", {})
            )
            if news_alert:
                changes.append(news_alert)

            # Attach alerts to profile
            if changes:
                profile.risk_factors.extend(
                    [a.title for a in changes if a.severity in ("critical", "high")]
                )

        # Phase 4: Network
        self.network.add_entity(name, profile.composite_score)
        self.network.build_from_collected_data(name, merged_data)

        logger.info(
            f"Enriched: {name} — "
            f"Composite: {profile.composite_score:.0f} "
            f"({profile.tier.value}) "
            f"Confidence: {profile.confidence:.0f}%"
        )

        return profile

    def _merge_collected_data(self, collected: dict, name: str, location: str) -> dict:
        """Merge all collected data from different sources into unified dict."""
        merged = {
            "sanctions": collected.get("sanctions", {}),
            "news": collected.get("news", {}),
            "social": collected.get("social", {}),
            "business": collected.get("public_records", {}).get("business", {}),
            "property": collected.get("public_records", {}).get("property", {}),
            "contributions": collected.get("public_records", {}).get("contributions", {}),
            "affiliation": collected.get("public_records", {}).get("affiliation", {}),
            "registration": collected.get("public_records", {}).get("registration", {}),
            "voting_history": collected.get("public_records", {}).get("voting_history", {}),
            "civic": collected.get("public_records", {}).get("civic", {}),
            "government": collected.get("public_records", {}).get("government", {}),
            "wealth_indicators": collected.get("public_records", {}).get("wealth_indicators", {}),
            "community": collected.get("public_records", {}).get("community", {}),
            "location": location,
            "_sources": [],
        }

        # Collect all source references
        for source_data in collected.values():
            if isinstance(source_data, dict):
                for src in source_data.get("_sources", []):
                    if src not in merged["_sources"]:
                        merged["_sources"].append(src)

        return merged

    def enrich_sync(self, names: list[str], location: str = "",
                     jurisdiction: str = "il", keywords: list | None = None,
                     enable_alerting: bool = True) -> list[InfluenceProfile]:
        """Synchronous wrapper for non-async contexts."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(
            self.enrich(names, location, jurisdiction, keywords, enable_alerting)
        )

    # ---- Query Methods ----

    def get_profile(self, name: str) -> Optional[InfluenceProfile]:
        """Get cached profile for a name."""
        return self._profiles.get(name)

    def get_alerts(self, severity: str | None = None) -> list:
        """Get active alerts, optionally filtered by severity."""
        from .alerts import AlertSeverity
        sev = AlertSeverity(severity) if severity else None
        return self.alert_manager.get_active_alerts(severity=sev)

    def get_timeline(self, name: str) -> list[dict]:
        """Get temporal timeline for an entity."""
        return self.alert_manager.get_timeline(name)

    def get_network_cluster(self, name: str, depth: int = 2) -> dict:
        """Get the influence network cluster around an entity."""
        return self.network.get_cluster(name, depth)

    def get_network_summary(self) -> dict:
        """Get network statistics."""
        self.network.compute_centrality()
        self.network.identify_hubs()
        return self.network.summary()

    def get_hubs(self, min_connections: int = 3) -> list[dict]:
        """Get identified influence hubs."""
        self.network.identify_hubs(min_connections)
        return [
            {
                "name": n.entity_name,
                "connections": len(n.connections),
                "score": n.influence_score,
                "centrality": n.centrality,
            }
            for n in self.network.identify_hubs(min_connections)
        ]

    def find_connection_path(self, source: str, target: str) -> Optional[list[str]]:
        """Find the shortest connection path between two entities."""
        return self.network.find_path(source, target)

    # ---- Reporting ----

    def generate_briefing(self, name: str) -> dict:
        """
        Generate a comprehensive intelligence briefing for one entity.
        Suitable for field operatives and decision-makers.
        """
        profile = self._profiles.get(name)
        if not profile:
            return {"error": f"No profile for '{name}'", "name": name}

        timeline = self.alert_manager.get_timeline(name)
        cluster = self.network.get_cluster(name, depth=2)

        return {
            "name": name,
            "classification": "CONFIDENTIAL",
            "generated_at": self.alert_manager.alerts[-1].timestamp
                if self.alert_manager.alerts else None,

            "influence_assessment": {
                "composite_score": profile.composite_score,
                "tier": profile.tier.value,
                "confidence": profile.confidence,
                "dimensions": {
                    "political_capital": profile.political_capital,
                    "community_influence": profile.community_influence,
                    "voter_reliability": profile.voter_reliability,
                    "financial_leverage": profile.financial_leverage,
                },
            },

            "evidence_summary": {
                k: v for k, v in profile.evidence.items() if v
            },
            "sources": profile.sources,

            "recommendation": profile.recommendation,
            "engagement_strategy": profile.engagement_strategy,

            "risks": profile.risk_factors,
            "opportunities": profile.opportunities,

            "network": {
                "cluster_size": cluster["size"],
                "hubs_in_cluster": cluster["hub_count"],
                "connections": cluster["cluster"][:10],  # Top 10
            },

            "temporal": {
                "snapshots": len(timeline),
                "latest_change": timeline[-1] if timeline else None,
            },
        }

    async def close(self):
        """Close all collector sessions."""
        for collector in [self.opensanctions, self.news, self.social,
                           self.public_records, self.web]:
            if collector and hasattr(collector, "close"):
                await collector.close()
