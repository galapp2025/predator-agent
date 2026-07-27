"""
GOTV (Get Out The Vote) Predictor — Voter classification & turnout modeling.

Classifies voters into actionable categories for campaign field operations:
  - SAFE:       Reliable supporter, high turnout probability
  - LEANING:    Likely supporter, needs light touching
  - SWING:      Persuadable, needs active engagement
  - AT_RISK:    May not vote without intervention
  - LOST:       Unlikely supporter, low turnout, hostile

Also computes:
  - turnout_probability:   estimated chance of voting (0-100)
  - persuasion_score:      how receptive to campaign messaging (0-100)
  - priority_score:        composite action priority (0-100)
  - optimal_channel:       best contact method
  - contact_frequency:     recommended touchpoints before election
  - messaging_frame:       most effective narrative angle
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class VoterCategory(str, Enum):
    SAFE = "safe"           # Reliable supporter, high turnout — minimal effort
    LEANING = "leaning"     # Likely supporter — light reinforcement
    SWING = "swing"         # Persuadable — active engagement needed
    AT_RISK = "at_risk"     # May drop off — urgent intervention
    LOST = "lost"           # Unlikely support, low turnout — deprioritize


class ContactChannel(str, Enum):
    PHONE = "phone"
    WHATSAPP = "whatsapp"
    SMS = "sms"
    DOOR_KNOCK = "door_knock"
    EMAIL = "email"
    SOCIAL = "social"


@dataclass
class GOTVProfile:
    """Complete GOTV assessment for a single voter."""
    name: str

    # Classification
    category: VoterCategory = VoterCategory.SWING
    category_confidence: float = 0.0

    # Core metrics (0-100)
    turnout_probability: float = 50.0
    persuasion_score: float = 50.0
    priority_score: float = 50.0

    # Campaign strategy
    optimal_channel: ContactChannel = ContactChannel.PHONE
    contact_frequency: str = "weekly"
    messaging_frame: str = "civic_duty"

    # Risk factors
    dropout_risk: float = 0.0           # probability of NOT voting (0-100)
    competitor_risk: float = 0.0         # risk of voting for opponent (0-100)
    disengagement_signals: list[str] = field(default_factory=list)

    # Opportunity flags
    volunteer_potential: bool = False
    donor_potential: bool = False
    multiplier_potential: bool = False    # can influence others

    # Evidence chain
    evidence: dict = field(default_factory=dict)
    recommended_action: str = ""


class GOTVPredictor:
    """
    Predicts voter behavior and classifies for GOTV campaign operations.

    Uses multi-factor heuristics based on:
      - Voting history consistency
      - Registration recency & status
      - Community engagement level
      - Political alignment signals
      - News/social media sentiment
      - Influence profile tier
    """

    # Weights for turnout probability model
    TURNOUT_WEIGHTS = {
        "voting_consistency": 0.35,    # strongest predictor
        "registration_age": 0.10,
        "civic_engagement": 0.15,
        "community_influence": 0.15,
        "news_exposure": 0.05,
        "political_capital": 0.10,
        "social_presence": 0.10,
    }

    # Weights for persuasion score
    PERSUASION_WEIGHTS = {
        "swing_indicator": 0.30,       # party switching history
        "news_sentiment": 0.20,
        "community_roles": 0.15,
        "issue_engagement": 0.15,
        "social_receptivity": 0.10,
        "volunteer_history": 0.10,
    }

    def predict(self, name: str, scoring_profile, voting_history: dict = None) -> GOTVProfile:
        """
        Generate complete GOTV prediction from scoring data.

        Args:
            name: Voter name
            scoring_profile: InfluenceProfile from scoring engine
            voting_history: Optional detailed voting history dict
        """
        vh = voting_history or {}

        turnout = self._compute_turnout_probability(scoring_profile, vh)
        persuasion = self._compute_persuasion_score(scoring_profile, vh)
        category, cat_conf = self._classify(turnout, persuasion, scoring_profile, vh)
        dropout = self._compute_dropout_risk(scoring_profile, vh)
        competitor = self._compute_competitor_risk(scoring_profile, vh)
        priority = self._compute_priority(turnout, persuasion, category, dropout)

        channel = self._optimal_channel(scoring_profile, vh)
        frequency = self._contact_frequency(category, turnout)
        frame = self._messaging_frame(scoring_profile, vh)

        signals = self._disengagement_signals(scoring_profile, vh)

        evidence = {
            "voter_reliability": scoring_profile.voter_reliability,
            "composite_score": scoring_profile.composite_score,
            "tier": scoring_profile.tier.value,
            "turnout_inputs": {
                "consistency": vh.get("consistency", "unknown"),
                "recent_turnout": self._recent_turnout(vh),
                "civic_score": scoring_profile.voter_reliability,
                "community_score": scoring_profile.community_influence,
            },
        }

        return GOTVProfile(
            name=name,
            category=category,
            category_confidence=round(cat_conf, 1),
            turnout_probability=round(turnout, 1),
            persuasion_score=round(persuasion, 1),
            priority_score=round(priority, 1),
            optimal_channel=channel,
            contact_frequency=frequency,
            messaging_frame=frame,
            dropout_risk=round(dropout, 1),
            competitor_risk=round(competitor, 1),
            disengagement_signals=signals,
            volunteer_potential=self._check_volunteer(scoring_profile, vh),
            donor_potential=self._check_donor(scoring_profile),
            multiplier_potential=self._check_multiplier(scoring_profile),
            evidence=evidence,
            recommended_action=self._action(category, channel, frequency, frame),
        )

    def batch_predict(self, profiles: dict, voting_histories: dict = None) -> list[GOTVProfile]:
        """Predict GOTV for multiple voters at once."""
        vh = voting_histories or {}
        results = []
        for name, profile in profiles.items():
            results.append(self.predict(name, profile, vh.get(name, {})))
        return sorted(results, key=lambda p: p.priority_score, reverse=True)

    # ---- Turnout Probability ----

    def _compute_turnout_probability(self, profile, vh: dict) -> float:
        score = 50.0  # baseline

        # Voting consistency (strongest signal)
        consistency = vh.get("consistency", "unknown")
        consistency_map = {
            "always": 95, "usually": 78, "sometimes": 55,
            "rarely": 25, "never": 5, "unknown": 50,
        }
        consistency_score = consistency_map.get(consistency, 50)
        score += (consistency_score - 50) * self.TURNOUT_WEIGHTS["voting_consistency"] * 2

        # Civic engagement → voter reliability
        voter_rel = profile.voter_reliability
        score += (voter_rel - 50) * self.TURNOUT_WEIGHTS["civic_engagement"] * 1.5

        # Community influence → more likely to vote
        comm = profile.community_influence
        score += (comm - 50) * self.TURNOUT_WEIGHTS["community_influence"] * 0.8

        # Political capital
        pol = profile.political_capital
        score += (pol - 50) * self.TURNOUT_WEIGHTS["political_capital"] * 0.6

        # Registration age bonus
        reg_age = vh.get("years_registered", 0)
        if reg_age > 10:
            score += 8
        elif reg_age > 5:
            score += 4
        elif reg_age > 2:
            score += 2

        return max(1, min(99, score))

    # ---- Persuasion Score ----

    def _compute_persuasion_score(self, profile, vh: dict) -> float:
        score = 50.0

        # Swing indicator: inconsistency in party voting
        consistency = vh.get("consistency", "unknown")
        if consistency in ("sometimes", "rarely"):
            score += 20  # inconsistent voters are more persuadable
        elif consistency == "always":
            score -= 10   # very consistent → harder to persuade
        elif consistency == "never":
            score -= 30   # non-voter → very hard

        # Community engagement → more receptive to peer influence
        comm = profile.community_influence
        if 30 <= comm <= 70:
            score += 10   # moderate community people are most persuadable
        elif comm > 70:
            score += 5    # high community people already have opinions

        # Financial interest → economic messaging may work
        fin = profile.financial_leverage
        if fin > 40:
            score += 8

        # Low political capital → more persuadable (less entrenched)
        pol = profile.political_capital
        if pol < 20:
            score += 12
        elif pol > 60:
            score -= 20   # highly political = entrenched

        return max(1, min(99, score))

    # ---- Classification ----

    def _classify(self, turnout: float, persuasion: float, profile, vh: dict) -> tuple[VoterCategory, float]:
        """
        Classify voter into operational category.

        Decision matrix:
                          High Turnout (>70)    Med Turnout (40-70)    Low Turnout (<40)
        High Persuasion     SAFE (base locked)    LEANING (cultivate)    SWING (persuade+motivate)
        Med Persuasion      SAFE (routine)        SWING (active)         AT_RISK (urgent)
        Low Persuasion      SAFE (monitor)        AT_RISK (defensive)    LOST (deprioritize)
        """
        if turnout > 70:
            if persuasion > 50:
                return VoterCategory.SAFE, 85.0
            elif persuasion > 25:
                return VoterCategory.SAFE, 70.0
            else:
                return VoterCategory.LEANING, 60.0
        elif turnout > 40:
            if persuasion > 50:
                return VoterCategory.LEANING, 75.0
            elif persuasion > 25:
                return VoterCategory.SWING, 65.0
            else:
                return VoterCategory.AT_RISK, 70.0
        else:
            if persuasion > 50:
                return VoterCategory.SWING, 60.0
            elif persuasion > 25:
                return VoterCategory.AT_RISK, 65.0
            else:
                return VoterCategory.LOST, 80.0

    # ---- Risks ----

    def _compute_dropout_risk(self, profile, vh: dict) -> float:
        """Probability of NOT voting despite being registered."""
        risk = 0.0
        consistency = vh.get("consistency", "unknown")
        if consistency == "rarely":
            risk += 40
        elif consistency == "sometimes":
            risk += 20
        elif consistency == "never":
            risk += 60

        # Recent registration = higher dropout
        reg_age = vh.get("years_registered", 10)
        if reg_age < 2:
            risk += 15
        elif reg_age < 5:
            risk += 8

        # Low civic engagement
        if profile.voter_reliability < 30:
            risk += 20
        elif profile.voter_reliability < 50:
            risk += 10

        return min(100, risk)

    def _compute_competitor_risk(self, profile, vh: dict) -> float:
        """Risk of voting for a competitor/opponent."""
        risk = 0.0

        # High political capital with different alignment = risk
        if profile.political_capital > 50 and vh.get("consistency") == "always":
            risk += 30

        # High financial leverage → may have competing interests
        if profile.financial_leverage > 60:
            risk += 15

        # Community leaders can sway others
        if profile.community_influence > 70:
            risk += 20

        # PEPs are usually aligned with status quo
        if profile.tier.value in ("critical", "high"):
            risk += 15

        return min(100, risk)

    # ---- Priority ----

    def _compute_priority(self, turnout: float, persuasion: float,
                          category: VoterCategory, dropout: float) -> float:
        """Composite action priority: who to contact FIRST."""
        base = 50.0

        # SWING voters are highest priority
        if category == VoterCategory.SWING:
            base += 25
        elif category == VoterCategory.AT_RISK:
            base += 15
        elif category == VoterCategory.LEANING:
            base += 10
        elif category == VoterCategory.LOST:
            base -= 20

        # High persuasion + high dropout = urgent
        if persuasion > 50 and dropout > 30:
            base += 15

        # Turnout impact
        if turnout < 50:
            base += (50 - turnout) * 0.3

        return max(1, min(100, base))

    # ---- Campaign Strategy ----

    def _optimal_channel(self, profile, vh: dict) -> ContactChannel:
        comm = profile.community_influence
        fin = profile.financial_leverage

        if comm > 70:
            return ContactChannel.DOOR_KNOCK  # community figures: personal touch
        if fin > 60:
            return ContactChannel.PHONE      # business figures: direct call
        if comm > 40:
            return ContactChannel.WHATSAPP   # social people: messaging
        if profile.voter_reliability > 80:
            return ContactChannel.SMS        # reliable voters: reminder
        return ContactChannel.PHONE

    def _contact_frequency(self, category: VoterCategory, turnout: float) -> str:
        if category == VoterCategory.SWING:
            return "twice_weekly"
        if category == VoterCategory.AT_RISK:
            return "weekly"
        if category == VoterCategory.LEANING:
            return "biweekly"
        if category == VoterCategory.SAFE:
            return "election_week_only" if turnout > 85 else "biweekly"
        return "none"

    def _messaging_frame(self, profile, vh: dict) -> str:
        pol = profile.political_capital
        comm = profile.community_influence
        fin = profile.financial_leverage
        voter_rel = profile.voter_reliability

        if pol > 50:
            return "policy_impact"
        if fin > 50:
            return "economic_benefit"
        if comm > 60:
            return "community_leadership"
        if voter_rel > 80:
            return "civic_duty"
        return "personal_connection"

    # ---- Signals ----

    def _disengagement_signals(self, profile, vh: dict) -> list[str]:
        signals = []
        consistency = vh.get("consistency", "unknown")
        if consistency in ("rarely", "never"):
            signals.append("missed_recent_elections")
        if consistency == "sometimes":
            signals.append("inconsistent_voter")
        reg_age = vh.get("years_registered", 10)
        if reg_age < 1:
            signals.append("newly_registered")
        if profile.voter_reliability < 30:
            signals.append("low_civic_engagement")
        return signals

    def _check_volunteer(self, profile, vh: dict) -> bool:
        comm = profile.community_influence
        voter_rel = profile.voter_reliability
        return comm > 60 and voter_rel > 70

    def _check_donor(self, profile) -> bool:
        return profile.financial_leverage > 50 or profile.political_capital > 60

    def _check_multiplier(self, profile) -> bool:
        return profile.community_influence > 75 and profile.tier.value in ("critical", "high", "moderate")

    def _recent_turnout(self, vh: dict) -> float:
        elections = vh.get("recent_elections", [])
        if not elections:
            return 50.0
        voted = sum(1 for e in elections if e.get("voted"))
        return (voted / len(elections)) * 100

    def _action(self, category: VoterCategory, channel: ContactChannel,
                frequency: str, frame: str) -> str:
        actions = {
            VoterCategory.SAFE: (
                "LOW EFFORT — Confirm turnout via {channel} {frequency}. "
                "Reinforce {frame} messaging. Consider volunteer/donor recruitment."
            ),
            VoterCategory.LEANING: (
                "MODERATE EFFORT — Cultivate via {channel} {frequency}. "
                "Share campaign updates. Leverage {frame} narrative."
            ),
            VoterCategory.SWING: (
                "HIGH PRIORITY — Active engagement via {channel} {frequency}. "
                "Personal contact with {frame} framing. "
                "Deploy senior field operative if multiplier potential confirmed."
            ),
            VoterCategory.AT_RISK: (
                "URGENT — Immediate intervention via {channel} {frequency}. "
                "Address disengagement signals directly. Remove barriers to voting. "
                "Offer transportation/polling assistance if applicable."
            ),
            VoterCategory.LOST: (
                "DEPRIORITIZE — Minimal resource allocation. "
                "Mass messaging only. Re-assess if new data emerges."
            ),
        }
        return actions.get(category, "").format(channel=channel.value, frequency=frequency, frame=frame)


# ---- GOTV Summary Generator ----

def gotv_battleplan(profiles: list[GOTVProfile]) -> dict:
    """
    Generate a GOTV battle plan from a list of voter profiles.
    Useful for campaign managers to allocate resources.
    """
    total = len(profiles)
    if total == 0:
        return {"total": 0}

    categories = {}
    for p in profiles:
        cat = p.category.value
        if cat not in categories:
            categories[cat] = {"count": 0, "avg_priority": 0.0, "voters": []}
        categories[cat]["count"] += 1
        categories[cat]["avg_priority"] += p.priority_score
        categories[cat]["voters"].append({
            "name": p.name,
            "priority": p.priority_score,
            "channel": p.optimal_channel.value,
            "turnout": p.turnout_probability,
        })

    for cat_info in categories.values():
        cat_info["avg_priority"] = round(cat_info["avg_priority"] / cat_info["count"], 1)
        cat_info["voters"].sort(key=lambda x: x["priority"], reverse=True)
        cat_info["voters"] = cat_info["voters"][:20]  # top 20 per category

    return {
        "total_voters": total,
        "categories": categories,
        "resource_allocation": {
            "swing_priority": len([p for p in profiles if p.category == VoterCategory.SWING]),
            "at_risk_count": len([p for p in profiles if p.category == VoterCategory.AT_RISK]),
            "safe_count": len([p for p in profiles if p.category == VoterCategory.SAFE]),
            "recommended_field_ops": max(1, total // 200),
        },
        "top_10_priority": sorted(
            [{
                "name": p.name,
                "category": p.category.value,
                "priority": p.priority_score,
                "action": p.recommended_action[:100],
            } for p in profiles],
            key=lambda x: x["priority"],
            reverse=True,
        )[:10],
    }
