"""
Opposition Research Engine — Comparative candidate analysis for campaign intelligence.

Capabilities:
  - Head-to-head candidate comparison across all dimensions
  - Strength/weakness identification
  - Vulnerability scoring (what can be exploited, what to defend)
  - Asymmetric advantage detection
  - Network overlap analysis (shared connections, intermediaries)
  - Recommendation engine for campaign strategy

Usage:
  research = OppositionResearch(pipeline)
  result = await research.compare("Candidate A", "Candidate B")
"""

import asyncio
from dataclasses import dataclass, field
from typing import Optional

from .gotv import GOTVPredictor, VoterCategory


@dataclass
class CandidateIntel:
    """Structured intelligence for one candidate."""
    name: str
    composite_score: float = 0.0
    tier: str = "negligible"
    confidence: float = 0.0

    # Dimensions
    political_capital: float = 0.0
    community_influence: float = 0.0
    voter_reliability: float = 0.0
    financial_leverage: float = 0.0

    # OSINT signals
    sanctions_risk: bool = False
    pep_status: bool = False
    news_mentions: int = 0
    news_sentiment_label: str = "neutral"
    negative_headlines: int = 0
    social_followers: int = 0
    business_ties: int = 0
    political_roles: list = field(default_factory=list)

    # Derived
    strengths: list = field(default_factory=list)
    weaknesses: list = field(default_factory=list)
    vulnerabilities: list = field(default_factory=list)

    sources: list = field(default_factory=list)


@dataclass
class ComparisonResult:
    """Complete head-to-head comparison."""
    candidate_a: CandidateIntel
    candidate_b: CandidateIntel

    # Who wins on each dimension
    winner_political: Optional[str] = None
    winner_community: Optional[str] = None
    winner_voter: Optional[str] = None
    winner_financial: Optional[str] = None
    winner_composite: Optional[str] = None

    # Margins
    margin_composite: float = 0.0
    dimension_margins: dict = field(default_factory=dict)

    # Asymmetric advantages
    a_advantages: list = field(default_factory=list)
    b_advantages: list = field(default_factory=list)

    # Shared connections / network overlap
    shared_connections: list = field(default_factory=list)
    network_distance: Optional[int] = None

    # Risk assessment
    a_attack_surface: list = field(default_factory=list)
    b_attack_surface: list = field(default_factory=list)
    a_defensive_gaps: list = field(default_factory=list)
    b_defensive_gaps: list = field(default_factory=list)

    # Strategic recommendations
    recommended_strategy: str = ""
    key_battlegrounds: list = field(default_factory=list)
    risk_escalation_scenarios: list = field(default_factory=list)


class OppositionResearch:
    """
    Produces comprehensive opposition research reports by comparing
    two candidates across all available intelligence dimensions.
    """

    def __init__(self, pipeline=None):
        self.pipeline = pipeline
        self.gotv = GOTVPredictor()

    async def compare(self, name_a: str, name_b: str,
                       location: str = "", jurisdiction: str = "il") -> ComparisonResult:
        """
        Generate a complete head-to-head comparison.

        If pipeline is available, enriches both candidates first.
        Otherwise, uses previously cached profiles.
        """
        # Enrich both candidates
        profile_a = None
        profile_b = None

        if self.pipeline:
            profiles = await self.pipeline.enrich(
                [name_a, name_b], location, jurisdiction
            )
            for p in profiles:
                if p.name == name_a:
                    profile_a = p
                elif p.name == name_b:
                    profile_b = p
        else:
            profile_a = self.pipeline.get_profile(name_a) if self.pipeline else None
            profile_b = self.pipeline.get_profile(name_b) if self.pipeline else None

        if not profile_a or not profile_b:
            raise ValueError(f"Could not enrich both candidates. A={profile_a is not None}, B={profile_b is not None}")

        # Build intel for each
        intel_a = self._build_intel(name_a, profile_a)
        intel_b = self._build_intel(name_b, profile_b)

        # Compare dimensions
        result = ComparisonResult(
            candidate_a=intel_a,
            candidate_b=intel_b,
        )

        # Who wins each dimension
        result.winner_political = self._winner(intel_a.political_capital, intel_b.political_capital, name_a, name_b)
        result.winner_community = self._winner(intel_a.community_influence, intel_b.community_influence, name_a, name_b)
        result.winner_voter = self._winner(intel_a.voter_reliability, intel_b.voter_reliability, name_a, name_b)
        result.winner_financial = self._winner(intel_a.financial_leverage, intel_b.financial_leverage, name_a, name_b)
        result.winner_composite = self._winner(profile_a.composite_score, profile_b.composite_score, name_a, name_b)

        result.margin_composite = round(profile_a.composite_score - profile_b.composite_score, 1)
        result.dimension_margins = {
            "political": round(intel_a.political_capital - intel_b.political_capital, 1),
            "community": round(intel_a.community_influence - intel_b.community_influence, 1),
            "voter": round(intel_a.voter_reliability - intel_b.voter_reliability, 1),
            "financial": round(intel_a.financial_leverage - intel_b.financial_leverage, 1),
        }

        # Asymmetric advantages
        result.a_advantages = self._find_advantages(intel_a, intel_b, name_a, name_b)
        result.b_advantages = self._find_advantages(intel_b, intel_a, name_b, name_a)

        # Network analysis
        result.shared_connections = self._shared_connections(
            self.pipeline, name_a, name_b
        ) if self.pipeline else []

        if self.pipeline:
            path = self.pipeline.find_connection_path(name_a, name_b)
            result.network_distance = len(path) - 1 if path and len(path) > 1 else None

        # Attack surfaces
        result.a_attack_surface = self._attack_surface(intel_a)
        result.b_attack_surface = self._attack_surface(intel_b)
        result.a_defensive_gaps = self._defensive_gaps(intel_a)
        result.b_defensive_gaps = self._defensive_gaps(intel_b)

        # Strategy
        result.recommended_strategy = self._recommend_strategy(result, name_a, name_b)
        result.key_battlegrounds = self._battlegrounds(result)
        result.risk_escalation_scenarios = self._escalation_scenarios(intel_a, intel_b)

        return result

    def compare_sync(self, name_a: str, name_b: str,
                      location: str = "", jurisdiction: str = "il") -> ComparisonResult:
        """Synchronous wrapper."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(
            self.compare(name_a, name_b, location, jurisdiction)
        )

    def _build_intel(self, name: str, profile) -> CandidateIntel:
        """Extract structured intelligence from an influence profile."""
        evidence = profile.evidence if hasattr(profile, 'evidence') else {}

        # Collect raw data from pipeline if available
        raw = {}
        if self.pipeline and hasattr(self.pipeline, '_raw_data'):
            raw = self.pipeline._raw_data.get(name, {})

        sanctions = raw.get("sanctions", {})
        news = raw.get("news", {})
        social = raw.get("social", {})
        business = raw.get("public_records", {}).get("business", {})

        intel = CandidateIntel(
            name=name,
            composite_score=profile.composite_score,
            tier=profile.tier.value,
            confidence=profile.confidence,
            political_capital=profile.political_capital,
            community_influence=profile.community_influence,
            voter_reliability=profile.voter_reliability,
            financial_leverage=profile.financial_leverage,
            sanctions_risk=sanctions.get("sanctions_count", 0) > 0,
            pep_status=sanctions.get("pep_status") == "confirmed",
            news_mentions=news.get("mention_count", 0),
            news_sentiment_label=news.get("sentiment", {}).get("label", "neutral"),
            negative_headlines=news.get("negative_mentions", 0),
            social_followers=(
                social.get("twitter", {}).get("followers", 0) +
                social.get("facebook", {}).get("friends_estimate", 0)
            ),
            business_ties=len(business.get("companies", [])) + len(business.get("director_roles", [])),
            political_roles=sanctions.get("political_roles", []),
            strengths=self._identify_strengths(profile),
            weaknesses=self._identify_weaknesses(profile, raw),
            vulnerabilities=self._identify_vulnerabilities(raw),
            sources=profile.sources if hasattr(profile, 'sources') else [],
        )
        return intel

    def _identify_strengths(self, profile) -> list[dict]:
        strengths = []
        if profile.political_capital > 60:
            strengths.append({"dimension": "political", "score": profile.political_capital, "note": "Strong political connections & influence"})
        if profile.community_influence > 60:
            strengths.append({"dimension": "community", "score": profile.community_influence, "note": "Deep community roots & network"})
        if profile.voter_reliability > 70:
            strengths.append({"dimension": "voter", "score": profile.voter_reliability, "note": "Consistent, reliable voter base"})
        if profile.financial_leverage > 50:
            strengths.append({"dimension": "financial", "score": profile.financial_leverage, "note": "Significant financial resources & connections"})
        if profile.tier.value in ("critical", "high"):
            strengths.append({"dimension": "overall", "score": profile.composite_score, "note": "Top-tier overall influence"})
        return strengths

    def _identify_weaknesses(self, profile, raw: dict) -> list[dict]:
        weaknesses = []
        if profile.political_capital < 20:
            weaknesses.append({"dimension": "political", "score": profile.political_capital, "note": "Limited political capital — vulnerability to established figures"})
        if profile.community_influence < 25:
            weaknesses.append({"dimension": "community", "score": profile.community_influence, "note": "Weak community presence — limited grassroots"})
        if profile.voter_reliability < 40:
            weaknesses.append({"dimension": "voter", "score": profile.voter_reliability, "note": "Unreliable voter base — turnout risk"})
        if profile.financial_leverage < 15:
            weaknesses.append({"dimension": "financial", "score": profile.financial_leverage, "note": "Limited financial resources — fundraising gap"})
        return weaknesses

    def _identify_vulnerabilities(self, raw: dict) -> list[dict]:
        vulns = []
        sanctions = raw.get("sanctions", {})
        news = raw.get("news", {})

        if sanctions.get("sanctions_count", 0) > 0:
            vulns.append({
                "type": "sanctions",
                "severity": "critical",
                "detail": f"On {sanctions['sanctions_count']} sanctions list(s): {sanctions.get('sanctions_lists', [])}",
            })
        if sanctions.get("pep_status") == "confirmed":
            vulns.append({
                "type": "pep",
                "severity": "high",
                "detail": "Politically Exposed Person — enhanced scrutiny risk",
            })
        if news.get("negative_mentions", 0) > 3:
            vulns.append({
                "type": "negative_press",
                "severity": "medium",
                "detail": f"{news['negative_mentions']} negative headlines — media vulnerability",
            })
        if news.get("sentiment", {}).get("label") == "negative":
            vulns.append({
                "type": "sentiment",
                "severity": "medium",
                "detail": "Overall negative sentiment in media coverage",
            })
        business = raw.get("public_records", {}).get("business", {})
        if business.get("conflict_indicators"):
            vulns.append({
                "type": "conflict_of_interest",
                "severity": "high",
                "detail": f"Conflict indicators: {business['conflict_indicators']}",
            })
        return vulns

    def _winner(self, score_a: float, score_b: float, name_a: str, name_b: str) -> str:
        if score_a > score_b:
            return name_a
        elif score_b > score_a:
            return name_b
        return "tie"

    def _find_advantages(self, intel: CandidateIntel, opponent: CandidateIntel,
                          name: str, opponent_name: str) -> list[dict]:
        """Find areas where candidate has a clear edge over opponent."""
        advantages = []
        margin = 15  # minimum margin to be considered an advantage

        if intel.political_capital - opponent.political_capital >= margin:
            advantages.append({
                "dimension": "political",
                "margin": round(intel.political_capital - opponent.political_capital, 1),
                "exploit": f"Leverage political network to outflank {opponent_name}",
            })
        if intel.community_influence - opponent.community_influence >= margin:
            advantages.append({
                "dimension": "community",
                "margin": round(intel.community_influence - opponent.community_influence, 1),
                "exploit": f"Activate grassroots network where {opponent_name} has no presence",
            })
        if intel.voter_reliability - opponent.voter_reliability >= margin:
            advantages.append({
                "dimension": "voter",
                "margin": round(intel.voter_reliability - opponent.voter_reliability, 1),
                "exploit": f"Push turnout — own base is more reliable than {opponent_name}'s",
            })
        if intel.financial_leverage - opponent.financial_leverage >= margin:
            advantages.append({
                "dimension": "financial",
                "margin": round(intel.financial_leverage - opponent.financial_leverage, 1),
                "exploit": f"Outspend on advertising and field operations vs {opponent_name}",
            })
        # Clean record advantage
        if not intel.sanctions_risk and opponent.sanctions_risk:
            advantages.append({
                "dimension": "integrity",
                "margin": 0,
                "exploit": f"Clean record vs {opponent_name}'s sanctions exposure",
            })
        if intel.negative_headlines < opponent.negative_headlines and opponent.negative_headlines > 3:
            advantages.append({
                "dimension": "media",
                "margin": opponent.negative_headlines - intel.negative_headlines,
                "exploit": f"Negative press surrounding {opponent_name} is exploitable",
            })
        return advantages

    def _shared_connections(self, pipeline, name_a: str, name_b: str) -> list[dict]:
        """Find shared network connections between two candidates."""
        if not pipeline:
            return []
        cluster_a = pipeline.get_network_cluster(name_a, depth=2)
        cluster_b = pipeline.get_network_cluster(name_b, depth=2)

        names_a = {n.get("name", n.get("entity", "")) for n in cluster_a.get("cluster", [])}
        names_b = {n.get("name", n.get("entity", "")) for n in cluster_b.get("cluster", [])}

        shared = []
        for name in names_a & names_b:
            if name and name not in (name_a, name_b):
                shared.append({"name": name, "relationship": "intermediary"})

        return shared

    def _attack_surface(self, intel: CandidateIntel) -> list[dict]:
        """Identify exploitable weaknesses — what opponent can attack."""
        surface = []
        if intel.sanctions_risk:
            surface.append({"target": "sanctions", "impact": "critical", "narrative": "Ethics and compliance questions"})
        if intel.pep_status:
            surface.append({"target": "pep", "impact": "high", "narrative": "Political elite / out of touch"})
        if intel.negative_headlines > 2:
            surface.append({"target": "media", "impact": "medium", "narrative": f"Negative press record ({intel.negative_headlines} stories)"})
        if intel.news_mentions < 5 and intel.community_influence < 30:
            surface.append({"target": "visibility", "impact": "medium", "narrative": "Low public profile — unknown quantity"})
        if intel.political_capital < 15:
            surface.append({"target": "experience", "impact": "low", "narrative": "Lack of political experience"})
        return surface

    def _defensive_gaps(self, intel: CandidateIntel) -> list[dict]:
        """What the candidate needs to shore up defensively."""
        gaps = []
        if intel.political_capital < 30:
            gaps.append({"area": "political_endorsements", "action": "Secure endorsements from established figures"})
        if intel.community_influence < 30:
            gaps.append({"area": "grassroots", "action": "Build community presence — town halls, local events"})
        if intel.voter_reliability < 50:
            gaps.append({"area": "turnout", "action": "Implement GOTV program targeting base"})
        if intel.financial_leverage < 25:
            gaps.append({"area": "fundraising", "action": "Launch targeted fundraising campaign"})
        if intel.negative_headlines > 3:
            gaps.append({"area": "pr", "action": "Deploy counter-narrative and positive media push"})
        return gaps

    def _recommend_strategy(self, result: ComparisonResult, name_a: str, name_b: str) -> str:
        """Generate strategic recommendation based on comparison."""
        a_adv = len(result.a_advantages)
        b_adv = len(result.b_advantages)
        a_vuln = len(result.a_attack_surface)
        b_vuln = len(result.b_attack_surface)

        if a_adv > b_adv and a_vuln < b_vuln:
            return (
                f"OFFENSIVE POSTURE — {name_a} holds asymmetric advantage over {name_b}. "
                f"Attack on {name_b}'s vulnerabilities ({b_vuln} identified) while defending own strengths. "
                f"Key: maintain momentum, force {name_b} to react."
            )
        elif b_adv > a_adv and b_vuln < a_vuln:
            return (
                f"DEFENSIVE POSTURE — {name_b} currently stronger than {name_a}. "
                f"Shore up {a_vuln} identified vulnerabilities. "
                f"Look for asymmetric angles — community, grassroots, integrity."
            )
        else:
            return (
                f"BALANCED CONTEST — {name_a} and {name_b} are closely matched. "
                f"Focus on turnout (GOTV) and exploiting opponent's {b_vuln} attack surfaces. "
                f"Swing voters in shared network will be decisive."
            )

    def _battlegrounds(self, result: ComparisonResult) -> list[dict]:
        """Identify key battleground dimensions."""
        battlegrounds = []
        margins = result.dimension_margins

        for dim, margin in margins.items():
            if abs(margin) < 10:
                battlegrounds.append({
                    "dimension": dim,
                    "margin": margin,
                    "description": f"{dim} is effectively tied — small shifts decisive",
                })
            elif abs(margin) < 20:
                battlegrounds.append({
                    "dimension": dim,
                    "margin": margin,
                    "description": f"{dim} advantage is narrow — could flip with effort",
                })

        return battlegrounds

    def _escalation_scenarios(self, intel_a: CandidateIntel,
                               intel_b: CandidateIntel) -> list[dict]:
        """Predict potential escalation scenarios."""
        scenarios = []
        if intel_a.sanctions_risk:
            scenarios.append({
                "trigger": "Sanctions disclosure",
                "impact": "Reputational damage to Candidate A",
                "likelihood": "medium",
            })
        if intel_b.sanctions_risk:
            scenarios.append({
                "trigger": "Sanctions disclosure",
                "impact": "Reputational damage to Candidate B",
                "likelihood": "medium",
            })
        if intel_a.negative_headlines > 5:
            scenarios.append({
                "trigger": "Media investigation",
                "impact": "Sustained negative coverage cycle",
                "likelihood": "high",
            })
        if intel_a.pep_status and not intel_b.pep_status:
            scenarios.append({
                "trigger": "Anti-elite narrative",
                "impact": "Candidate A framed as establishment insider",
                "likelihood": "high",
            })
        return scenarios


def comparison_to_dict(result: ComparisonResult) -> dict:
    """Convert ComparisonResult to API-safe dict."""
    a = {
        "name": result.candidate_a.name,
        "composite": result.candidate_a.composite_score,
        "tier": result.candidate_a.tier,
        "dimensions": {
            "political": result.candidate_a.political_capital,
            "community": result.candidate_a.community_influence,
            "voter": result.candidate_a.voter_reliability,
            "financial": result.candidate_a.financial_leverage,
        },
        "strengths": result.candidate_a.strengths,
        "weaknesses": result.candidate_a.weaknesses,
        "vulnerabilities": result.candidate_a.vulnerabilities,
        "attack_surface": result.a_attack_surface,
        "defensive_gaps": result.a_defensive_gaps,
        "advantages": result.a_advantages,
    }
    b = {
        "name": result.candidate_b.name,
        "composite": result.candidate_b.composite_score,
        "tier": result.candidate_b.tier,
        "dimensions": {
            "political": result.candidate_b.political_capital,
            "community": result.candidate_b.community_influence,
            "voter": result.candidate_b.voter_reliability,
            "financial": result.candidate_b.financial_leverage,
        },
        "strengths": result.candidate_b.strengths,
        "weaknesses": result.candidate_b.weaknesses,
        "vulnerabilities": result.candidate_b.vulnerabilities,
        "attack_surface": result.b_attack_surface,
        "defensive_gaps": result.b_defensive_gaps,
        "advantages": result.b_advantages,
    }
    return {
        # Canonical nested shape
        "candidates": {"a": a, "b": b},
        # Flat aliases expected by clients / integrity suite
        "candidate_a": a,
        "candidate_b": b,
        "composite_delta": result.margin_composite,
        "head_to_head": {
            "winner_composite": result.winner_composite,
            "margin_composite": result.margin_composite,
            "dimension_winners": {
                "political": result.winner_political,
                "community": result.winner_community,
                "voter": result.winner_voter,
                "financial": result.winner_financial,
            },
            "dimension_margins": result.dimension_margins,
        },
        "network": {
            "shared_connections": result.shared_connections,
            "network_distance": result.network_distance,
        },
        "strategy": {
            "recommended": result.recommended_strategy,
            "key_battlegrounds": result.key_battlegrounds,
            "escalation_scenarios": result.risk_escalation_scenarios,
        },
    }
