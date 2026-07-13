"""Resistance Meter — מד התנגדות בזמן אמת (Hebrew-optimized, calibrated v2)"""

from dataclasses import dataclass
from typing import List


# ── Calibrated Hebrew Resistance Markers ─────────────────
# Weights tuned so:
#   Single VERY_HIGH → very_high (termination/demand-to-stop phrases)
#   Single HIGH → high, Two HIGH → very_high
#   Single MEDIUM → medium, Two MEDIUM → high, Three+ → very_high
#   Single LOW → low
#   Anti-AI detection → HIGH (priority)

VERY_HIGH_RESISTANCE_MARKERS = [
    # Explicit termination / demand-to-stop (immediate escalation)
    "תוריד אותי מהרשימה", "תפסיק להתקשר", "תעזוב אותי במנוחה",
    "מחק אותי", "אל תתקשר אליי יותר", "תוריד את המספר שלי",
    "אל תתקשר אליי", "תעזוב אותי", "תפסיק",
    "זה הטרדה", "אני אתלונן", "אני אתקשר למשטרה",
    "תנתק", "די כבר", "נמאס לי ממך", "עזוב",
    "אני לא מדבר", "אני לא רוצה לדבר", "תעזוב אותי בשקט",
]

HIGH_RESISTANCE_MARKERS = [
    # Rejection / hostility
    "לא מעוניין", "לא רוצה", "אל תתקשר",
    "מי אתה", "מאיפה המספר", "לא רשום", "כבר החלטתי",
    "אני נגד", "לא מצביע", "זה לא בשבילי", "אני לא מתעניין",
    "הציק לי",
    "אין סיכוי", "בחיים לא", "עזוב אותי",
    "אל תציק",
    "די", "מספיק", "נמאס", "חבל על הזמן",
    "אתם כולם אותו דבר", "שקרן", "רמאי", "הונאה",
    # Anti‑AI / robot detection (CRITICAL — escalate immediately)
    "אתה רובוט", "רובוט", "בינה מלאכותית", "AI",
    "מחשב", "תוכנה", "קול מלאכותי", "אתה לא בן אדם",
    "זה מחשב", "מכונה", "אוטומט", "בוט",
    "זיהוי קולי", "הקלטה", "מוקלט",
    # Strong skepticism
    "אני לא מאמין לך", "אני לא מאמין", "לא סומך",
    "לא מאמין לאף אחד", "כולכם אותו דבר",
    "אני יודע איך זה עובד", "שמעתי את זה כבר",
    "לא תעבוד עליי",
]

MEDIUM_RESISTANCE_MARKERS = [
    # Hesitation / uncertainty
    "אני לא יודע", "צריך לחשוב", "נדבר מאוחר יותר",
    "לא בטוח", "אולי", "אם יהיה לי זמן", "נראה לי שלא",
    "אני צריך לשאול", "תלוי", "עוד לא החלטתי",
    "אני חושב", "אני אשקול", "תן לי לראות",
    "בוא נראה", "אה…", "הממ", "לא עכשיו",
    "אולי אחר כך", "אני עסוק", "אין לי זמן",
    "זה לא דחוף", "אחשוב על זה", "תן לי לחשוב",
    # Soft deflection
    "לא כרגע", "אולי מחר", "תתקשר מחר",
    "שלח לי הודעה", "דבר איתי בוואטסאפ",
    "אני בפגישה", "אני נוהג",
    # Bare negation
    "לא",
]

LOW_RESISTANCE_MARKERS = [
    # Agreement / engagement
    "כן", "בטח", "אוקיי", "סבבה", "נשמע טוב",
    "אני מסכים", "ברור", "בא לי", "אשמח",
    "מעניין", "תגיד", "תמשיך", "אני בעד",
    "אני תומך", "למה לא", "בוודאי", "יאללה",
    "אחלה", "וואלה", "אחי", "כפרה", "חמוד",
    "תסביר", "מה עשיתם", "איך זה עובד",
    "באמת", "ספר לי", "שמע", "תקשיב",
    "מה אתה אומר", "זה נשמע", "יכול להיות",
    "אולי אני אבוא", "תרשום אותי",
    # Curiosity / openness
    "מה אתה מציע", "מה השם שלך", "מי זה",
    "בשביל מי אתה עובד", "למה אתה מתקשר",
    "תפרט", "אני מקשיב",
]


@dataclass
class ResistanceReading:
    level: str
    score: float
    signals: List[str]


def _word_boundary_match(text: str, marker: str) -> bool:
    """
    Check if `marker` appears in `text` at word boundaries.
    Prevents false positives like 'שמע' matching inside 'שמעון'.
    Multi-word markers must appear as contiguous words.
    Both inputs should already be lowercased.
    """
    import re
    escaped = re.escape(marker.lower())
    # Hebrew Unicode range: \u0590-\u05FF
    pattern = r'(?<![\u0590-\u05FF])' + escaped + r'(?![\u0590-\u05FF])'
    return bool(re.search(pattern, text))


def _dedupe_substrings(markers: List[str]) -> List[str]:
    """Remove markers that are substrings of other matched markers (keep longest)."""
    if len(markers) <= 1:
        return markers
    sorted_markers = sorted(set(markers), key=len, reverse=True)
    result = []
    for m in sorted_markers:
        if not any(m in other and m != other for other in result):
            result.append(m)
    return result


def measure_resistance(
    voter_text: str,
    speech_pace: float = 1.0,
    speech_volume: float = 1.0,
) -> ResistanceReading:
    """
    Measure resistance from Hebrew text. Calibrated v2 weights.
    Level: low (<0.30) | medium (0.30-0.49) | high (0.50-0.69) | very_high (≥0.70)
    """
    text = voter_text.strip()
    text_lower = text.lower()
    score = 0.30  # calibrated base (leans slightly low)

    # ── Marker scoring (word-boundary + substring dedup) ───
    raw_high = [m for m in HIGH_RESISTANCE_MARKERS if _word_boundary_match(text_lower, m)]
    raw_medium = [m for m in MEDIUM_RESISTANCE_MARKERS if _word_boundary_match(text_lower, m)]
    raw_low = [m for m in LOW_RESISTANCE_MARKERS if _word_boundary_match(text_lower, m)]

    high_markers = _dedupe_substrings(raw_high)
    medium_markers = _dedupe_substrings(raw_medium)
    low_markers = _dedupe_substrings(raw_low)

    # Cross-category dedup: remove MEDIUM markers that are substrings of HIGH markers
    medium_markers = [m for m in medium_markers
                      if not any(m in h and m != h for h in high_markers)]
    # Also remove LOW markers that are substrings of HIGH markers
    low_markers = [m for m in low_markers
                   if not any(m in h and m != h for h in high_markers)]

    # ── VERY_HIGH markers (termination/demand-to-stop) ──────
    raw_very_high = [m for m in VERY_HIGH_RESISTANCE_MARKERS if _word_boundary_match(text_lower, m)]
    very_high_markers = _dedupe_substrings(raw_very_high)
    very_high_count = len(very_high_markers)

    # Remove HIGH markers that overlap with VERY_HIGH markers (either direction)
    high_markers = [m for m in high_markers
                    if not any(m in v or v in m for v in very_high_markers)]

    high_count = len(high_markers)
    medium_count = len(medium_markers)
    low_count = len(low_markers)

    signals: List[str] = []

    if very_high_count > 0:
        score += 0.45 * very_high_count  # immediate escalation
        signals.extend(very_high_markers)

    if high_count > 0:
        score += 0.25 * high_count
        signals.extend(high_markers)

    if medium_count > 0:
        score += 0.12 * medium_count
        signals.extend(medium_markers)

    if low_count > 0:
        score -= 0.15 * low_count
        signals.extend(low_markers)

    # ── Tone heuristics ─────────────────────────
    if speech_pace > 1.3 and speech_volume > 1.2:
        score += 0.15
        signals.append("דיבור מהיר וחזק")

    if speech_pace < 0.7:
        score -= 0.08
        signals.append("דיבור איטי — התלבטות")

    # ── Text‑level features ─────────────────────
    exclamation = text.count("!")
    if exclamation >= 2:
        score += 0.15
        signals.append("סימני קריאה מרובים")

    word_count = len(text.split())

    # Pre-compute anti-AI flag (used by multiple heuristics below)
    anti_ai_markers = ["רובוט", "AI", "בינה מלאכותית", "בוט", "מחשב", "תוכנה",
                       "קול מלאכותי", "אתה לא בן אדם", "זה מחשב", "מכונה", "אוטומט",
                       "זיהוי קולי", "הקלטה", "מוקלט"]
    is_anti_ai = any(_word_boundary_match(text_lower, m) for m in anti_ai_markers)

    # Very short + high resistance → angry escalation
    # BUT: skip if it's an anti-AI question (not anger, just detection)
    if word_count <= 2 and high_count > 0 and not is_anti_ai and not text.rstrip().endswith("?"):
        score += 0.20
        signals.append("תשובה קצרה עם התנגדות")

    # Long text → engagement bonus
    if word_count > 10:
        score -= 0.10

    # Question at end → curiosity / engagement
    # BUT: if paired with anti-AI markers, ignore (it's a hostile question)
    if text.rstrip().endswith("?") and not is_anti_ai:
        score -= 0.08

    # "אבל" (but) — mild objection unless already hostile
    if "אבל" in text_lower and high_count == 0:
        score += 0.05

    # ── Unclassified fallback ────────────────────
    if high_count == 0 and medium_count == 0 and low_count == 0:
        score -= 0.05  # neutral / conversational → lean low resistance

    # ── Clamp ────────────────────────────────────
    score = max(0.0, min(1.0, score))

    # ── Level assignment ─────────────────────────
    if score >= 0.70:
        level = "very_high"
    elif score >= 0.50:
        level = "high"
    elif score >= 0.30:
        level = "medium"
    else:
        level = "low"

    return ResistanceReading(level=level, score=score, signals=signals)
