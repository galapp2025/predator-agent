"""DISC Classifier — סיווג בוחר לפי שפה"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class DISCProfile:
    primary: str
    secondary: Optional[str] = None
    confidence: float = 0.5
    signals: List[str] = field(default_factory=list)


D_MARKERS = [
    "מהר", "עכשיו", "תכלס", "בוא נעשה", "ישר", "תחליט", "אני מחליט",
    "מספיק", "קדימה", "מיד", "לא מעוניין", "לא רוצה", "תקצר", "תגיד לי", "בוא לעניין",
]
I_MARKERS = [
    "וואלה", "מגניב", "אחלה", "כיף", "מעולה", "אני מכיר", "סיפרו לי", "חבר שלי",
    "אהבתי", "נהניתי", "תספר", "תמשיך", "באמת", "וואו", "מעניין אותי", "אני אוהב", "מרגש",
]
S_MARKERS = [
    "אולי", "נראה לי", "צריך לחשוב", "תלוי", "לא יודע", "לא בטוח", "אשאל",
    "אני צריך", "אשמח", "תודה", "בבקשה", "אם אפשר", "אין לי בעיה", "אני בסדר",
    "אפשר לדבר", "המשפחה שלי", "אשתי", "בעלי", "הילדים", "תקשיב",
]
C_MARKERS = [
    "לפי", "מתי", "כמה", "איפה", "מי", "תראה לי", "נתונים", "מספרים", "אחוזים",
    "מחקר", "דוח", "מה אתה אומר", "בדקת", "תוכל", "האם", "מתי בדיוק", "מה ההבדל", "תסביר",
]


def classify(text: str) -> DISCProfile:
    text_lower = text.lower()
    d_count = sum(1 for m in D_MARKERS if m in text_lower)
    i_count = sum(1 for m in I_MARKERS if m in text_lower)
    s_count = sum(1 for m in S_MARKERS if m in text_lower)
    c_count = sum(1 for m in C_MARKERS if m in text_lower)
    scores = {"D": d_count, "I": i_count, "S": s_count, "C": c_count}
    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    primary = sorted_scores[0][0]
    primary_count = sorted_scores[0][1]
    secondary = None
    if (
        len(sorted_scores) > 1
        and sorted_scores[1][1] > 0
        and primary_count > 0
        and sorted_scores[1][1] >= primary_count * 0.5
    ):
        secondary = sorted_scores[1][0]
    total = d_count + i_count + s_count + c_count
    confidence = 0.3 if total == 0 else min(0.95, 0.4 + (primary_count / total) * 0.55)
    signals: List[str] = []
    for marker_list in (D_MARKERS, I_MARKERS, S_MARKERS, C_MARKERS):
        found = [m for m in marker_list if m in text_lower]
        if found:
            signals.extend(found[:3])
    return DISCProfile(
        primary=primary,
        secondary=secondary,
        confidence=confidence,
        signals=signals[:5],
    )


def suggest_persona_from_profile(profile: DISCProfile) -> str:
    mapping = {"D": "S", "I": "I", "S": "S", "C": "C"}
    return mapping.get(profile.primary, "S")
