"""
BlackOpps Intelligence Module — OSINT-Enabled Voter Enrichment Engine.

Multi-dimensional influence scoring with external OSINT collection.
Designed for operational intelligence at the level of a field intelligence unit.

Architecture:
  collectors/      — External data sources (OpenSanctions, news, social, public records, web)
  scoring.py       — Multi-dimensional influence scoring engine
  entity.py        — Entity resolution & deduplication
  network.py       — Relationship graph & connection mapping
  alerts.py        — Temporal change detection & alerting
  pipeline.py      — Full enrichment pipeline orchestrator
  gotv.py          — GOTV predictor: voter classification (SAFE/SWING/AT_RISK/LOST)
  opposition.py    — Opposition research: candidate comparison engine
  pdf_generator.py — PDF briefing generation for field operatives
"""

from .scoring import InfluenceScorer, InfluenceProfile
from .pipeline import EnrichmentPipeline
from .entity import resolve_entity
from .gotv import GOTVPredictor, GOTVProfile, VoterCategory, gotv_battleplan
from .opposition import OppositionResearch, ComparisonResult, comparison_to_dict
from .pdf_generator import BriefingPDF, generate_briefing_pdf
from .auth import AuthMiddleware, RateLimiter, SecurityHeadersMiddleware

__all__ = [
    # Core
    "InfluenceScorer",
    "InfluenceProfile",
    "EnrichmentPipeline",
    "resolve_entity",
    # GOTV
    "GOTVPredictor",
    "GOTVProfile",
    "VoterCategory",
    "gotv_battleplan",
    # Opposition
    "OppositionResearch",
    "ComparisonResult",
    "comparison_to_dict",
    # PDF
    "BriefingPDF",
    "generate_briefing_pdf",
    # Auth
    "AuthMiddleware",
    "RateLimiter",
    "SecurityHeadersMiddleware",
]
