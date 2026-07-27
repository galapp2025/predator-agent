"""
Multi-Dimensional Influence Scoring Engine.

Scoring Dimensions:
  political_capital   — Political activity, donations, connections, party affiliation
  community_influence — Social media presence, news mentions, community roles
  voter_reliability   — Voting history, civic engagement, registration status
  financial_leverage  — Business ties, wealth indicators, economic interests

All dimensions: 0-100. Composite: weighted aggregation with configurable weights.

Weights are calibrated for election influence assessment:
  - political_capital:   30%  (direct political power)
  - community_influence: 25%  (ability to sway others)
  - voter_reliability:   25%  (probability of voting)
  - financial_leverage:  20%  (economic influence)
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class InfluenceTier(str, Enum):
    CRITICAL = "critical"       # 85-100: Top-tier influencer
    HIGH = "high"               # 70-84:  Significant influence
    MODERATE = "moderate"       # 50-69:  Notable influence
    LOW = "low"                 # 30-49:  Limited influence
    NEGLIGIBLE = "negligible"   # 0-29:   Minimal influence


# ---- Influence Profile ----

@dataclass
class InfluenceProfile:
    """Complete influence assessment for one entity."""
    name: str
    entity_id: Optional[str] = None

    # Core dimensions (0-100)
    political_capital: float = 0.0
    community_influence: float = 0.0
    voter_reliability: float = 0.0
    financial_leverage: float = 0.0

    # Composite
    composite_score: float = 0.0
    tier: InfluenceTier = InfluenceTier.NEGLIGIBLE

    # Evidence & provenance
    evidence: dict = field(default_factory=dict)
    sources: list = field(default_factory=list)
    confidence: float = 0.0  # Overall confidence in assessment

    # Actionable intelligence
    recommendation: str = ""
    risk_factors: list = field(default_factory=list)
    opportunities: list = field(default_factory=list)
    engagement_strategy: str = ""

    # Temporal tracking
    last_updated: Optional[str] = None
    change_since_last: Optional[dict] = None


# ---- Dimension Sub-Scorers ----

class PoliticalCapitalScorer:
    """
    Political capital — direct political power, connections, activity.
    Sources: OpenSanctions, campaign finance records, party registries.
    """

    # Role tier scoring — reflects actual political power
    ROLE_TIER_KEYWORDS = {
        # Tier 1: Head of state/government (highest power)
        "head_of_state": [
            "president", "prime minister", "premier", "chancellor",
            "ראש ממשלה", "נשיא", 'רוה"מ',
        ],
        # Tier 2: Cabinet-level ministers
        "minister": [
            "minister", "secretary", "attorney general",
            "שר", "שרה",
        ],
        # Tier 3: Parliament/Congress members
        "legislator": [
            "member of parliament", "member of knesset", "knesset member", "parliament",
            "senator", "congressman", "congresswoman", "mp", "mk", "חבר כנסת", "חכ", "חברת כנסת",
        ],
        # Tier 4: Local government / party officials
        "local_official": [
            "mayor", "governor", "council", "ראש עיר", "מועצה",
        ],
    }

    ROLE_TIER_SCORES = {
        "head_of_state": 50,
        "minister": 35,
        "legislator": 25,
        "local_official": 15,
        "default": 10,
    }

    def _classify_role(self, role_text: str) -> str:
        """Classify a political role string into a tier."""
        role_lower = role_text.lower()
        for tier, keywords in self.ROLE_TIER_KEYWORDS.items():
            for kw in keywords:
                if kw in role_lower:
                    return tier
        return "default"

    def score(self, data: dict) -> tuple[float, dict]:
        evidence = {}
        score = 0.0

        # OpenSanctions / sanctions list matches
        sanctions = data.get("sanctions", {})
        if sanctions.get("pep_status"):
            evidence["pep"] = sanctions["pep_status"]
            score += 40  # Raised from 35 — PEP is significant

        if sanctions.get("sanctions_count", 0) > 0:
            evidence["sanctions"] = sanctions["sanctions_count"]
            score += 25  # Raised from 20 — sanctions are a red flag

        if sanctions.get("political_roles", []):
            roles = sanctions["political_roles"]
            # Use tiered scoring: score each role by its tier, take best 3
            role_scores = []
            for role in roles:
                role_text = role if isinstance(role, str) else role.get("role", str(role))
                tier = self._classify_role(role_text)
                role_scores.append(self.ROLE_TIER_SCORES.get(tier, 10))
            role_scores.sort(reverse=True)
            # Top 3 roles contribute (with diminishing returns after first)
            top3 = role_scores[:3]
            if top3:
                role_bonus = top3[0] + sum(s * 0.3 for s in top3[1:])
                evidence["political_roles"] = len(roles)
                # Use the highest-tier role for evidence, not just the first one
                best_role = max(roles, key=lambda r: self.ROLE_TIER_SCORES.get(
                    self._classify_role(r if isinstance(r, str) else r.get("role", "")), 0
                ))
                best_role_text = best_role if isinstance(best_role, str) else best_role.get("role", "")
                evidence["top_role_tier"] = self._classify_role(best_role_text)
                evidence["top_role"] = best_role_text
                score += role_bonus

        # Campaign contributions
        contributions = data.get("contributions", {})
        if contributions.get("total_donated", 0) > 0:
            evidence["contributions"] = contributions["total_donated"]
            score += min(contributions["total_donated"] / 1000, 15)

        # Party / organizational affiliation
        affiliation = data.get("affiliation", {})
        if affiliation.get("party_member"):
            evidence["party"] = affiliation["party_name"]
            score += 10
        if affiliation.get("party_role"):
            evidence["party_role"] = affiliation["party_role"]
            score += 15  # Raised from 10 — formal party role matters

        return min(score, 100), evidence


class CommunityInfluenceScorer:
    """
    Community influence — ability to sway others, public visibility.
    Sources: social media, news mentions, community leadership roles.
    """

    def score(self, data: dict) -> tuple[float, dict]:
        evidence = {}
        score = 0.0

        # Social media presence
        social = data.get("social", {})
        if social.get("twitter", {}):
            tw = social["twitter"]
            followers = tw.get("followers", 0)
            evidence["twitter_followers"] = followers
            score += min(followers / 100, 25)

        if social.get("facebook", {}):
            fb = social["facebook"]
            friends = fb.get("friends_estimate", 0)
            evidence["facebook_presence"] = friends
            score += min(friends / 200, 10)

        if social.get("linkedin", {}):
            li = social["linkedin"]
            connections = li.get("connections_estimate", 0)
            evidence["linkedin_connections"] = connections
            score += min(connections / 100, 10)

        # News mentions
        news = data.get("news", {})
        mentions = news.get("mention_count", 0)
        evidence["news_mentions"] = mentions
        score += min(mentions * 5, 20)

        sentiment = news.get("sentiment", {})
        if sentiment:
            pos = sentiment.get("positive", 0)
            evidence["positive_sentiment_pct"] = pos
            score += pos * 0.15

        # Community roles
        community = data.get("community", {})
        roles = community.get("leadership_roles", [])
        evidence["community_roles"] = len(roles)
        score += min(len(roles) * 8, 20)

        return min(score, 100), evidence


class VoterReliabilityScorer:
    """
    Voter reliability — probability and consistency of voting.
    Sources: voter history records, registration data, civic engagement.
    """

    def score(self, data: dict) -> tuple[float, dict]:
        evidence = {}
        score = 50.0  # Base: registered voter

        # Voting history
        history = data.get("voting_history", {})
        elections = history.get("recent_elections", [])
        if elections:
            voted_count = sum(1 for e in elections if e.get("voted"))
            turnout_pct = (voted_count / len(elections)) * 100
            evidence["recent_turnout"] = turnout_pct
            score += turnout_pct * 0.3

        consistency = history.get("consistency", "unknown")
        evidence["consistency"] = consistency
        consistency_bonus = {
            "always": 20,
            "usually": 12,
            "sometimes": 5,
            "rarely": 0,
            "never": -20,
            "unknown": 0,
        }
        score += consistency_bonus.get(consistency, 0)

        # Registration
        registration = data.get("registration", {})
        if registration.get("registered"):
            evidence["registered"] = True
            score += 5
        if registration.get("registration_date"):
            import datetime
            try:
                reg_date = datetime.datetime.strptime(
                    registration["registration_date"], "%Y-%m-%d"
                )
                years_registered = (datetime.datetime.now() - reg_date).days / 365
                evidence["years_registered"] = round(years_registered, 1)
                score += min(years_registered * 0.5, 10)
            except (ValueError, TypeError):
                pass

        # Civic engagement
        civic = data.get("civic", {})
        if civic.get("volunteer"):
            evidence["volunteer"] = True
            score += 5
        if civic.get("donor"):
            evidence["donor"] = True
            score += 5

        return max(0, min(score, 100)), evidence


class FinancialLeverageScorer:
    """
    Financial leverage — economic influence, business connections.
    Sources: OpenCorporates, property records, business registries.
    """

    def score(self, data: dict) -> tuple[float, dict]:
        evidence = {}
        score = 0.0

        # Business ownership
        business = data.get("business", {})
        companies = business.get("companies", [])
        if companies:
            evidence["companies_owned"] = len(companies)
            score += min(len(companies) * 10, 25)

        director_roles = business.get("director_roles", [])
        if director_roles:
            evidence["director_positions"] = len(director_roles)
            score += min(len(director_roles) * 8, 20)

        # Property
        property_data = data.get("property", {})
        if property_data.get("properties_owned", 0) > 0:
            evidence["properties"] = property_data["properties_owned"]
            score += min(property_data["properties_owned"] * 8, 16)

        # Wealth indicators
        wealth = data.get("wealth_indicators", {})
        if wealth.get("estimated_net_worth_category"):
            cat = wealth["estimated_net_worth_category"]
            evidence["net_worth_category"] = cat
            nw_bonus = {"high": 20, "upper_middle": 12, "middle": 5, "lower": 0}
            score += nw_bonus.get(cat, 0)

        if wealth.get("public_filings", []):
            evidence["public_filings"] = len(wealth["public_filings"])
            score += min(len(wealth["public_filings"]) * 3, 9)

        # Government contracts
        gov = data.get("government", {})
        if gov.get("contracts", []):
            evidence["gov_contracts"] = len(gov["contracts"])
            score += min(len(gov["contracts"]) * 10, 10)

        return min(score, 100), evidence


# ---- Master Scorer ----

DEFAULT_WEIGHTS = {
    "political_capital": 0.30,
    "community_influence": 0.25,
    "voter_reliability": 0.25,
    "financial_leverage": 0.20,
}

# Adaptive weights: when a profile type is detected, use specialized weights
# that give more emphasis to the dominant dimension.
PROFILE_WEIGHTS = {
    "political": {
        "political_capital": 0.45,
        "community_influence": 0.20,
        "voter_reliability": 0.15,
        "financial_leverage": 0.20,
    },
    "community": {
        "political_capital": 0.15,
        "community_influence": 0.45,
        "voter_reliability": 0.20,
        "financial_leverage": 0.20,
    },
    "business": {
        "political_capital": 0.20,
        "community_influence": 0.15,
        "voter_reliability": 0.15,
        "financial_leverage": 0.50,
    },
    "general": {
        "political_capital": 0.30,
        "community_influence": 0.25,
        "voter_reliability": 0.25,
        "financial_leverage": 0.20,
    },
}

TIER_THRESHOLDS = [
    (85, InfluenceTier.CRITICAL),
    (70, InfluenceTier.HIGH),
    (50, InfluenceTier.MODERATE),
    (30, InfluenceTier.LOW),
    (0, InfluenceTier.NEGLIGIBLE),
]

# PEP override: when PEP detected and political_capital > 50, floor the composite
PEP_COMPOSITE_FLOOR = 55  # PEPs are at minimum MODERATE


class InfluenceScorer:
    """
    Master influence scorer.
    Aggregates four dimensions into a composite score with configurable weights.
    """

    def __init__(self, weights: dict | None = None):
        self.weights = weights or DEFAULT_WEIGHTS
        self.political = PoliticalCapitalScorer()
        self.community = CommunityInfluenceScorer()
        self.voter = VoterReliabilityScorer()
        self.financial = FinancialLeverageScorer()

    def _detect_profile_type(self, pol_score: float, com_score: float,
                             fin_score: float, data: dict) -> str:
        """
        Detect dominant profile type for adaptive weighting.
        Returns: 'political', 'community', 'business', or 'general'
        """
        is_pep = bool(data.get("sanctions", {}).get("pep_status"))

        if is_pep or pol_score >= 65:
            return "political"
        if fin_score >= 50:
            return "business"
        if com_score >= 60:
            return "community"
        return "general"

    def _impute_missing_dimensions(self, pol_score: float, com_score: float,
                                     vot_score: float, fin_score: float,
                                     profile_type: str, data: dict) -> tuple[float, float, float, float]:
        """
        Impute conservative defaults for missing dimensions on high-value targets.
        Avoids penalizing profiles when data simply wasn't collected (e.g., no
        business API key available but target is clearly a political figure).
        """
        is_pep = bool(data.get("sanctions", {}).get("pep_status"))

        if profile_type == "political" and pol_score >= 50:
            # Political figures: assume baseline financial resources and voter reliability
            if fin_score == 0:
                fin_score = 35  # Conservative assumption — political figures have resources
            if vot_score <= 50:
                vot_score = max(vot_score, 60)  # Political figures are reliable voters

        if profile_type == "business" and fin_score >= 50:
            if pol_score == 0:
                pol_score = 20  # Business figures often have political connections
            if vot_score <= 50:
                vot_score = max(vot_score, 55)

        return pol_score, com_score, vot_score, fin_score

    def score(self, name: str, data: dict) -> InfluenceProfile:
        """Generate complete influence profile from collected data."""

        # Score each dimension
        pol_score, pol_evidence = self.political.score(data)
        com_score, com_evidence = self.community.score(data)
        vot_score, vot_evidence = self.voter.score(data)
        fin_score, fin_evidence = self.financial.score(data)

        # Detect profile type and impute missing dimensions
        profile_type = self._detect_profile_type(pol_score, com_score, fin_score, data)
        pol_score, com_score, vot_score, fin_score = self._impute_missing_dimensions(
            pol_score, com_score, vot_score, fin_score, profile_type, data
        )

        # Use adaptive weights based on profile type
        weights = PROFILE_WEIGHTS.get(profile_type, DEFAULT_WEIGHTS)

        # Composite
        composite = (
            pol_score * weights["political_capital"]
            + com_score * weights["community_influence"]
            + vot_score * weights["voter_reliability"]
            + fin_score * weights["financial_leverage"]
        )

        # PEP override: political figures with PEP status should not fall below MODERATE
        is_pep = bool(data.get("sanctions", {}).get("pep_status"))
        if is_pep and pol_score >= 50:
            composite = max(composite, PEP_COMPOSITE_FLOOR)

        # Determine tier
        tier = InfluenceTier.NEGLIGIBLE
        for threshold, t in TIER_THRESHOLDS:
            if composite >= threshold:
                tier = t
                break

        # Confidence: higher when more dimensions have data
        dimensions_with_data = sum(
            1 for s in [pol_score, com_score, vot_score, fin_score] if s > 0
        )
        confidence = min(dimensions_with_data / 4 * 100, 95)

        # Build profile
        profile = InfluenceProfile(
            name=name,
            political_capital=round(pol_score, 1),
            community_influence=round(com_score, 1),
            voter_reliability=round(vot_score, 1),
            financial_leverage=round(fin_score, 1),
            composite_score=round(composite, 1),
            tier=tier,
            confidence=round(confidence, 1),
            evidence={
                "political": pol_evidence,
                "community": com_evidence,
                "voter": vot_evidence,
                "financial": fin_evidence,
            },
            sources=data.get("_sources", []),
            recommendation=self._generate_recommendation(tier, composite, pol_score, vot_score),
            risk_factors=self._identify_risks(data),
            opportunities=self._identify_opportunities(tier, pol_score, com_score, vot_score),
            engagement_strategy=self._engagement_strategy(tier, pol_score, com_score, vot_score, fin_score),
        )

        return profile

    def score_batch(self, names: list[str], data_map: dict[str, dict]) -> list[InfluenceProfile]:
        """Score multiple entities at once."""
        return [self.score(name, data_map.get(name, {})) for name in names]

    # ---- Intelligence generation ----

    def _generate_recommendation(self, tier: InfluenceTier, composite: float,
                                  pol: float, vot: float) -> str:
        if tier == InfluenceTier.CRITICAL:
            return (
                "PRIORITY TARGET — Immediate direct engagement by senior field operative. "
                "This individual has exceptional influence across multiple dimensions. "
                "Personal contact essential. Prepare comprehensive briefing package."
            )
        elif tier == InfluenceTier.HIGH:
            return (
                "HIGH VALUE — Direct engagement recommended within 48 hours. "
                "Significant community or political influence. Tailor approach based on "
                "dominant dimension. Leverage existing network connections if available."
            )
        elif tier == InfluenceTier.MODERATE:
            if pol > 50:
                return (
                    "POLITICAL TARGET — Has political influence. Engage via policy "
                    "channels. Senior operative or political liaison recommended. "
                    "Monitor PEP/sanctions status for changes."
                )
            if vot > 70:
                return (
                    "RELIABLE VOTER — Canvass for turnout confirmation. "
                    "Moderate influence profile but consistent voter. Focus on "
                    "get-out-the-vote messaging. Good candidate for volunteer recruitment."
                )
            return (
                "STANDARD ENGAGEMENT — Include in targeted outreach campaigns. "
                "Moderate potential. Digital + mail contact sufficient. "
                "Monitor for changes in influence profile."
            )
        elif tier == InfluenceTier.LOW:
            return (
                "LOW PRIORITY — Mass outreach appropriate. Limited influence. "
                "Include in broad awareness campaigns. Worth monitoring for "
                "changes if circumstances shift."
            )
        return (
            "MINIMAL — Standard voter rolls treatment. No special engagement "
            "warranted. Flag for re-evaluation if new data emerges."
        )

    def _identify_risks(self, data: dict) -> list[str]:
        risks = []
        if data.get("sanctions", {}).get("sanctions_count", 0) > 0:
            risks.append("Sanctions exposure — reputational risk if publicly associated")
        if data.get("news", {}).get("negative_mentions", 0) > 3:
            risks.append("Negative media profile — may attract unwanted attention")
        if data.get("business", {}).get("conflict_indicators", []):
            risks.append("Potential conflicts of interest flagged")
        if data.get("social", {}).get("controversial_content", False):
            risks.append("Controversial social media content detected")
        return risks

    def _identify_opportunities(self, tier: InfluenceTier, pol: float,
                                 com: float, vot: float) -> list[str]:
        opportunities = []
        if com > 70:
            opportunities.append("Community amplifier — can reach 10-50x through network effect")
        if pol > 60:
            opportunities.append("Political access point — potential conduit to decision-makers")
        if vot > 80:
            opportunities.append("Reliable turnout — low-effort vote secured")
        if tier in (InfluenceTier.CRITICAL, InfluenceTier.HIGH):
            opportunities.append("Fundraising potential — likely donor or fundraiser")
        return opportunities

    def _engagement_strategy(self, tier: InfluenceTier, pol: float,
                              com: float, vot: float, fin: float) -> str:
        dominant = max(
            ("political", pol), ("community", com),
            ("voter", vot), ("financial", fin), key=lambda x: x[1]
        )[0]

        strategies = {
            "political": (
                "Engage through policy discussions. Emphasize systemic impact. "
                "Connect to broader political narrative. Senior operative required."
            ),
            "community": (
                "Engage through community channels. Emphasize local impact. "
                "Leverage social proof and network effects. Peer-to-peer optimal."
            ),
            "voter": (
                "Direct GOTV approach. Emphasize civic duty and election stakes. "
                "Minimal friction — confirm and remind. Standard canvassing effective."
            ),
            "financial": (
                "Engage through economic framing. Emphasize fiscal impact. "
                "Business-case approach. Personal network introduction preferred."
            ),
        }

        if tier == InfluenceTier.CRITICAL:
            return strategies[dominant] + " FULL BRIEFING PACKAGE — all dimensions consolidated."
        return strategies[dominant]
