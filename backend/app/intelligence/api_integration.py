"""
FastAPI Integration — Drop-in adapter for the existing BlackOpps API.

This module shows how to integrate the OSINT intelligence layer into
the existing POST /analyze endpoint. It replaces the local deterministic
analysis with the full enrichment pipeline.

Usage in your FastAPI app:

    from .intelligence import EnrichmentPipeline, InfluenceProfile

    pipeline = EnrichmentPipeline(
        opensanctions_key=os.getenv("OPENSANCTIONS_API_KEY"),
        newsapi_key=os.getenv("NEWSAPI_KEY"),
    )

    @app.post("/analyze")
    async def analyze(names: list[str]):
        profiles = await pipeline.enrich(names)
        return {
            "profiles": [profile_to_dict(p) for p in profiles],
            "summary": pipeline_summary(pipeline),
        }
"""

from typing import Optional
from .pipeline import EnrichmentPipeline
from .scoring import InfluenceProfile, InfluenceTier


# Singleton pipeline instance
_pipeline: Optional[EnrichmentPipeline] = None


def get_pipeline(**kwargs) -> EnrichmentPipeline:
    """Get or create the enrichment pipeline singleton."""
    global _pipeline
    if _pipeline is None:
        _pipeline = EnrichmentPipeline(**kwargs)
    return _pipeline


def reset_pipeline():
    """Reset pipeline (for testing)."""
    global _pipeline
    _pipeline = None


def profile_to_dict(profile: InfluenceProfile) -> dict:
    """Convert InfluenceProfile to API-safe dict."""
    return {
        "name": profile.name,
        "entity_id": profile.entity_id,
        "scores": {
            "political_capital": profile.political_capital,
            "community_influence": profile.community_influence,
            "voter_reliability": profile.voter_reliability,
            "financial_leverage": profile.financial_leverage,
            "composite": profile.composite_score,
        },
        "tier": profile.tier.value,
        "confidence": profile.confidence,
        "recommendation": profile.recommendation,
        "engagement_strategy": profile.engagement_strategy,
        "risk_factors": profile.risk_factors,
        "opportunities": profile.opportunities,
        "evidence": profile.evidence,
        "sources": profile.sources,
    }


def pipeline_summary(pipeline: EnrichmentPipeline) -> dict:
    """Generate pipeline-level summary."""
    profiles = pipeline._profiles
    if not profiles:
        return {"total": 0, "tiers": {}, "alerts": {}}

    tiers = {}
    for p in profiles.values():
        tiers[p.tier.value] = tiers.get(p.tier.value, 0) + 1

    alert_summary = pipeline.alert_manager.summary()
    network_summary = pipeline.get_network_summary()

    return {
        "total_profiles": len(profiles),
        "tier_distribution": tiers,
        "average_composite": round(
            sum(p.composite_score for p in profiles.values()) / len(profiles), 1
        ),
        "alerts": alert_summary,
        "network": network_summary,
        "hubs": pipeline.get_hubs(),
    }
