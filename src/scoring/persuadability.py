"""Predictive Persuadability Scoring — ניקוד בוחרים חכם לפי סיכוי שכנוע"""
import csv
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("persuadability-scorer")

# ── Stronghold Cities (מועמד חזק בערים האלה) ──────────
# Geographic density bonus — voters in strongholds are easier to mobilize
STRONGHOLD_CITIES = {
    "תל אביב": 0.08, "תל אביב-יפו": 0.08, "יפו": 0.06,
    "גבעתיים": 0.07, "רמת גן": 0.06, "הרצליה": 0.05,
    "חולון": 0.04, "בת ים": 0.03, "ראשון לציון": 0.04,
    "פתח תקווה": 0.03, "כפר סבא": 0.04, "רעננה": 0.05,
    "נתניה": 0.03, "חיפה": 0.04, "באר שבע": 0.03,
    "ירושלים": 0.02, "מודיעין": 0.04, "רחובות": 0.03,
}

# ── Branch Loyalty Bonus (סניפים "חמים") ──────────────
# Registered branch tells us if the voter is already in the party's orbit
BRANCH_LOYALTY_BONUS = {
    "תל אביב": 0.10, "רמת גן": 0.09, "גבעתיים": 0.09,
    "הרצליה": 0.08, "רעננה": 0.07, "כפר סבא": 0.07,
    "חיפה": 0.06, "באר שבע": 0.05, "ירושלים": 0.05,
    "ראשון לציון": 0.06, "חולון": 0.05, "נתניה": 0.05,
    "פתח תקווה": 0.04, "מודיעין": 0.06, "רחובות": 0.04,
}

# ── Name-Based Age Heuristics (שמות לפי שנתון) ────────
# Israeli names carry generational signals
YOUNGER_NAMES = {
    # Gen Z / Millennial (under 35) — modern, trendy
    "אופק", "ליעד", "בר", "שחר", "נועה", "אגם", "עומר", "רוני",
    "עדי", "מאיה", "גיא", "יובל", "תומר", "אור", "רועי", "שירן",
    "לינוי", "ים", "גל", "אדר", "שגיא", "ענבר", "ליבי", "מיקה",
    "אלין", "ניקול", "אדל", "אמה", "אריאל", "הילה", "סתיו",
    "מתן", "דניאל", "נטע", "איתי", "נטלי", "אלונה", "טליה",
}
MIDDLE_AGED_NAMES = {
    # Gen X (35-55) — classic but not old-fashioned
    "גלית", "מיכל", "דנה", "ליאת", "קרן", "ענת", "שרון", "אורנה",
    "איריס", "יעל", "סיגל", "טל", "ניר", "איל", "גלעד", "ערן",
    "אמיר", "ארז", "דורון", "אבי", "אילן", "אורי", "בועז", "שי",
    "יוסי", "אודי", "קובי", "מוטי", "רן", "ליאור", "עודד",
}
OLDER_NAMES = {
    # Boomer (55+) — names that peaked in 1950s-70s
    "רחל", "מרדכי", "שרה", "אברהם", "יעקב", "מרים", "דוד", "לאה",
    "אסתר", "משה", "רבקה", "יצחק", "שושנה", "חיים", "יוסף", "חנה",
    "פנינה", "צבי", "יהודית", "שלמה", "בתיה", "מנחם", "ברכה",
    "אהרון", "זאב", "דבורה", "אליהו", "מאיר", "יפה", "שמעון",
    "תמר", "רות", "נעמי", "אורה", "עליזה", "גרשון",
}

# ── Score weights ──────────────────────────────────────
WEIGHTS = {
    "support_score": 0.30,       # Existing support signal
    "demographic": 0.20,         # Age/life-stage persuadability
    "geographic": 0.25,          # Stronghold density
    "branch_loyalty": 0.15,      # Party branch affinity
    "contact_history": 0.10,     # Previous contact success
}


@dataclass
class ScoredLead:
    """Lead with computed persuadability score and breakdown."""
    phone: str
    first_name: str
    last_name: str
    full_name: str
    city: str
    street: str
    house_number: str
    registered_branch: str
    support_score: float
    persuadability_score: float = 0.5
    score_breakdown: Dict[str, float] = field(default_factory=dict)
    rank: int = 0
    tier: str = "C"  # A (≥0.7), B (0.4-0.69), C (<0.4)


class PersudadabilityScorer:
    """
    מחשב ציון שכנוע (0.0-1.0) לכל בוחר ב-CSV.
    
    Signals:
    - support_score: נתון ישיר מהקובץ (כמה הבוחר כבר תומך)
    - demographic: שם → שנתון → קבוצת גיל → סיכוי שכנוע משוערך
    - geographic: עיר/רחוב → אזורי כוח של המועמד
    - branch_loyalty: סניף רשום → קרבה ארגונית
    - contact_history: היסטוריית שיחות קודמות (אם קיימת)
    """

    def __init__(
        self,
        stronghold_cities: Optional[Dict[str, float]] = None,
        branch_bonuses: Optional[Dict[str, float]] = None,
        history_path: Optional[str] = "data/call_history.json",
    ):
        self.stronghold_cities = stronghold_cities or STRONGHOLD_CITIES
        self.branch_bonuses = branch_bonuses or BRANCH_LOYALTY_BONUS
        self.history_path = history_path
        self._contact_cache: Dict[str, int] = {}  # phone → previous contact count

    def _load_contact_history(self):
        """טוען היסטוריית שיחות קודמות לצורך ניקוד."""
        if self._contact_cache:
            return
        if not self.history_path or not os.path.exists(self.history_path):
            return
        try:
            with open(self.history_path, "r", encoding="utf-8") as f:
                history = json.load(f)
            for record in history:
                phone = record.get("phone", "")
                if phone:
                    self._contact_cache[phone] = self._contact_cache.get(phone, 0) + 1
            logger.debug(f"Loaded contact history for {len(self._contact_cache)} numbers")
        except (json.JSONDecodeError, FileNotFoundError, Exception) as e:
            logger.warning(f"Could not load contact history: {e}")

    def _estimate_age_group(self, first_name: str) -> str:
        """מעריך שנתון לפי שם פרטי."""
        name = first_name.strip()
        if name in YOUNGER_NAMES:
            return "young"
        if name in MIDDLE_AGED_NAMES:
            return "middle"
        if name in OLDER_NAMES:
            return "older"
        return "unknown"

    def _demographic_persuadability(self, first_name: str, city: str) -> float:
        """
        מחשב סיכוי שכנוע לפי דמוגרפיה.
        צעירים (25-35) קלים יותר לשכנוע; בני 55+ קשים יותר.
        """
        age_group = self._estimate_age_group(first_name)
        base = {
            "young": 0.65,     # Millennials/GenZ — more persuadable
            "middle": 0.55,    # GenX — moderate
            "older": 0.40,     # Boomers — more fixed opinions
            "unknown": 0.50,   # Can't estimate → neutral
        }
        score = base.get(age_group, 0.50)

        # City modifier: urban voters slightly more persuadable
        city_lower = city.strip().lower()
        if any(c in city_lower for c in ["תל אביב", "חיפה", "באר שבע", "ירושלים"]):
            score += 0.03
        # Peripheral voters also slightly more receptive (less political saturation)
        if any(c in city_lower for c in ["שדרות", "אופקים", "נתיבות", "קריית שמונה", "ירוחם"]):
            score += 0.04

        return min(0.85, max(0.25, score))

    def _geographic_score(self, city: str, street: str) -> float:
        """בונוס גיאוגרפי לפי עיר חזקה + רחוב מבוסס."""
        city_score = 0.0
        city_clean = city.strip()

        # Exact match
        if city_clean in self.stronghold_cities:
            city_score = self.stronghold_cities[city_clean]
        else:
            # Partial match (e.g., "תל אביב-יפו" matches "תל אביב")
            for stronghold, bonus in self.stronghold_cities.items():
                if stronghold in city_clean or city_clean in stronghold:
                    city_score = bonus
                    break

        # Street-level affluence bonus (שמות רחובות "טובים")
        street_lower = street.strip().lower()
        affluent_streets = [
            "רוטשילד", "בן יהודה", "דיזנגוף", "אבן גבירול", "הרצל",
            "ויצמן", "ז'בוטינסקי", "ביאליק", "אלנבי", "הנשיא",
            "פנקס", "הגפן", "האורנים", "הדקלים", "השקמה",
            "הגולן", "הכרמל", "הגליל", "הארזים", "הברושים",
        ]
        street_bonus = 0.02 if any(s in street_lower for s in affluent_streets) else 0.0

        return min(0.15, city_score + street_bonus)

    def _branch_score(self, registered_branch: str) -> float:
        """בונוס נאמנות סניף."""
        if not registered_branch:
            return 0.0
        branch_clean = registered_branch.strip()
        if branch_clean in self.branch_bonuses:
            return self.branch_bonuses[branch_clean]
        # Partial match
        for branch_key, bonus in self.branch_bonuses.items():
            if branch_key in branch_clean or branch_clean in branch_key:
                return bonus
        return 0.0

    def _contact_score(self, phone: str) -> float:
        """בונוס היסטוריית קשר."""
        if phone in self._contact_cache:
            count = self._contact_cache[phone]
            if count == 0:
                return 0.0
            if count == 1:
                return 0.03
            if count == 2:
                return 0.05
            return 0.07  # 3+ contacts — they keep engaging
        return 0.0

    def score_lead(self, lead: Dict) -> ScoredLead:
        """
        מחשב ציון שכנוע לבוחר בודד.
        
        Args:
            lead: Dict with keys: phone, first_name, last_name, city, street, 
                  house_number, registered_branch, support_score
        
        Returns:
            ScoredLead with persuadability_score and breakdown
        """
        self._load_contact_history()

        phone = lead.get("phone", "")
        first_name = lead.get("first_name", "")
        last_name = lead.get("last_name", "")
        city = lead.get("city", "")
        street = lead.get("street", "")
        house_number = lead.get("house_number", "")
        registered_branch = lead.get("registered_branch", "")
        support_score = float(lead.get("support_score", 0.5))

        # ── Signal 1: Support score ──
        # Higher support = more persuadable (they already lean toward us)
        # Non-linear: mid-range supporters (0.3-0.6) are most persuadable
        # This is the "swing voter" sweet spot
        if support_score >= 0.7:
            support_signal = 0.90  # Already ours — easy to GOTV
        elif support_score >= 0.5:
            support_signal = 0.75  # Leaning our way
        elif support_score >= 0.3:
            support_signal = 0.55  # Swing voter — high value target
        elif support_score >= 0.15:
            support_signal = 0.35  # Leaning against
        else:
            support_signal = 0.15  # Strongly opposed

        # ── Signal 2: Demographic ──
        demographic_signal = self._demographic_persuadability(first_name, city)

        # ── Signal 3: Geographic ──
        geographic_signal = self._geographic_score(city, street)

        # ── Signal 4: Branch loyalty ──
        branch_signal = self._branch_score(registered_branch)

        # ── Signal 5: Contact history ──
        contact_signal = self._contact_score(phone)

        # ── Weighted composite ──
        raw_score = (
            support_signal * WEIGHTS["support_score"]
            + demographic_signal * WEIGHTS["demographic"]
            + geographic_signal * WEIGHTS["geographic"]
            + branch_signal * WEIGHTS["branch_loyalty"]
            + contact_signal * WEIGHTS["contact_history"]
        )

        # Normalize to 0.0-1.0 and add a small Gaussian noise (±0.02) to break ties
        import random
        noise = random.uniform(-0.02, 0.02)
        final_score = max(0.01, min(0.99, raw_score + noise))

        # Tier
        if final_score >= 0.70:
            tier = "A"
        elif final_score >= 0.40:
            tier = "B"
        else:
            tier = "C"

        return ScoredLead(
            phone=phone,
            first_name=first_name,
            last_name=last_name,
            full_name=f"{first_name} {last_name}".strip(),
            city=city,
            street=street,
            house_number=house_number,
            registered_branch=registered_branch,
            support_score=support_score,
            persuadability_score=round(final_score, 3),
            score_breakdown={
                "support_signal": round(support_signal, 3),
                "demographic_signal": round(demographic_signal, 3),
                "geographic_signal": round(geographic_signal, 3),
                "branch_signal": round(branch_signal, 3),
                "contact_signal": round(contact_signal, 3),
            },
            tier=tier,
        )

    def score_csv(self, csv_path: str) -> List[ScoredLead]:
        """
        קורא CSV, מנקד כל בוחר, מחזיר רשימה ממוינת (הכי ניתן לשכנוע ראשון).
        
        Args:
            csv_path: Path to CSV file (e.g., 'data/leads.csv')
        
        Returns:
            List of ScoredLead sorted by persuadability_score descending
        """
        if not os.path.exists(csv_path):
            logger.error(f"CSV not found: {csv_path}")
            return []

        leads = []
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                phone = (row.get("phone") or "").strip()
                if not phone:
                    continue
                leads.append(row)

        scored = [self.score_lead(l) for l in leads]
        scored.sort(key=lambda x: x.persuadability_score, reverse=True)

        # Assign ranks
        for i, s in enumerate(scored, start=1):
            s.rank = i

        logger.info(
            f"Scored {len(scored)} leads: "
            f"A-tier={sum(1 for s in scored if s.tier == 'A')}, "
            f"B-tier={sum(1 for s in scored if s.tier == 'B')}, "
            f"C-tier={sum(1 for s in scored if s.tier == 'C')}"
        )

        return scored

    def export_scored_csv(self, input_path: str, output_path: str) -> str:
        """
        Reads CSV, scores, and exports a new sorted CSV with score columns.
        
        Returns path to output file.
        """
        scored = self.score_csv(input_path)

        fieldnames = [
            "rank", "phone", "first_name", "last_name", "full_name",
            "city", "street", "house_number", "registered_branch",
            "support_score", "persuadability_score", "tier",
            "support_signal", "demographic_signal", "geographic_signal",
            "branch_signal", "contact_signal",
        ]

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for s in scored:
                row = {
                    "rank": s.rank,
                    "phone": s.phone,
                    "first_name": s.first_name,
                    "last_name": s.last_name,
                    "full_name": s.full_name,
                    "city": s.city,
                    "street": s.street,
                    "house_number": s.house_number,
                    "registered_branch": s.registered_branch,
                    "support_score": s.support_score,
                    "persuadability_score": s.persuadability_score,
                    "tier": s.tier,
                    **{k: v for k, v in s.score_breakdown.items()},
                }
                writer.writerow(row)

        logger.info(f"Exported scored leads to {output_path}")
        return output_path

    def get_top_tier(self, csv_path: str, tier: str = "A") -> List[ScoredLead]:
        """Returns only leads matching a specific tier."""
        return [s for s in self.score_csv(csv_path) if s.tier == tier]

    def get_stats(self, csv_path: str) -> Dict:
        """Returns scoring statistics for the CSV."""
        scored = self.score_csv(csv_path)
        if not scored:
            return {"total": 0, "tiers": {}, "avg_score": 0.0, "sweet_spot_count": 0}

        scores = [s.persuadability_score for s in scored]
        return {
            "total": len(scored),
            "tiers": {
                "A": sum(1 for s in scored if s.tier == "A"),
                "B": sum(1 for s in scored if s.tier == "B"),
                "C": sum(1 for s in scored if s.tier == "C"),
            },
            "avg_score": round(sum(scores) / len(scores), 3),
            "max_score": round(max(scores), 3),
            "min_score": round(min(scores), 3),
            "sweet_spot_count": sum(
                1 for s in scored if 0.30 <= s.support_score <= 0.60
            ),
        }
