"""Resistance Meter — מד התנגדות בזמן אמת + מגמה לאורך השיחה"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional


HIGH_RESISTANCE_MARKERS = [
    "לא מעוניין",
    "לא רוצה",
    "תעזוב אותי",
    "אל תתקשר",
    "מי אתה",
    "מאיפה המספר",
    "לא רשום",
    "כבר החלטתי",
    "אני נגד",
    "לא מצביע",
    "זה לא בשבילי",
    "אני לא מתעניין",
    "תוריד אותי מהרשימה",
    "תפסיק להתקשר",
    "הציק לי",
    "אין סיכוי",
    "בחיים לא",
    "תספיק",
    "די כבר",
    "לא רלוונטי",
]

MEDIUM_RESISTANCE_MARKERS = [
    "אני לא יודע",
    "צריך לחשוב",
    "נדבר מאוחר יותר",
    "לא בטוח",
    "אולי",
    "אם יהיה לי זמן",
    "נראה לי שלא",
    "אני צריך לשאול",
    "תלוי",
    "עוד לא החלטתי",
    "בוא נראה",
    "אחר כך",
    "אין לי כוח",
    "אני עסוק",
]

LOW_RESISTANCE_MARKERS = [
    "כן",
    "בטח",
    "אוקיי",
    "סבבה",
    "נשמע טוב",
    "אני מסכים",
    "ברור",
    "בא לי",
    "אשמח",
    "מעניין",
    "תגיד",
    "תמשיך",
    "אני בעד",
    "אני תומך",
    "למה לא",
    "בוודאי",
    "יאללה",
    "בסדר",
    "מסכים",
]

# סימני מבחן זיהוי / עימות — מעלים התנגדות ומפעילים battle mode
DETECTION_ATTACK_MARKERS = [
    "נשמע כמו מחשב",
    "אתה בוט",
    "אתה רובוט",
    "בינה מלאכותית",
    "אתה AI",
    "you are an ai",
    "are you a bot",
    "chatgpt",
    "gpt",
]


@dataclass
class ResistanceReading:
    level: str
    score: float
    signals: List[str]
    detection_attack: bool = False
    trend: str = "stable"  # rising | falling | stable


@dataclass
class ResistanceSnapshot:
    exchange: int
    reading: ResistanceReading


def _level_from_score(score: float) -> str:
    if score >= 0.75:
        return "very_high"
    if score >= 0.55:
        return "high"
    if score >= 0.35:
        return "medium"
    return "low"


def measure_resistance(
    voter_text: str,
    speech_pace: float = 1.0,
    speech_volume: float = 1.0,
    previous_score: Optional[float] = None,
) -> ResistanceReading:
    """מדידת התנגדות בודדת לטקסט תור נוכחי."""
    text = (voter_text or "").strip()
    text_lower = text.lower()
    signals: List[str] = []
    score = 0.5
    detection_attack = False

    high_count = sum(1 for m in HIGH_RESISTANCE_MARKERS if m in text_lower)
    medium_count = sum(1 for m in MEDIUM_RESISTANCE_MARKERS if m in text_lower)
    low_count = sum(1 for m in LOW_RESISTANCE_MARKERS if m in text_lower)
    detect_hits = [m for m in DETECTION_ATTACK_MARKERS if m.lower() in text_lower]

    if high_count > 0:
        score += 0.3 * high_count
        signals.extend([m for m in HIGH_RESISTANCE_MARKERS if m in text_lower][:5])
    if medium_count > 0:
        score += 0.15 * medium_count
        signals.extend([m for m in MEDIUM_RESISTANCE_MARKERS if m in text_lower][:4])
    if low_count > 0:
        score -= 0.2 * low_count
        signals.extend([m for m in LOW_RESISTANCE_MARKERS if m in text_lower][:4])

    if detect_hits:
        detection_attack = True
        score += 0.25
        signals.extend(detect_hits[:3])
        signals.append("detection_attack")

    if speech_pace > 1.3 and speech_volume > 1.2:
        score += 0.2
        signals.append("דיבור מהיר וחזק")
    if speech_pace < 0.7:
        score -= 0.1
        signals.append("דיבור איטי — התלבטות")

    if text.count("!") >= 2:
        score += 0.2
        signals.append("סימני קריאה מרובים")

    word_count = len(text.split())
    if word_count <= 2 and high_count > 0:
        score += 0.2
        signals.append("תשובה קצרה עם התנגדות")
    if word_count >= 40 and high_count == 0:
        score -= 0.05
        signals.append("תשובה ארוכה — מעורבות")

    # שאלות מתמטיות / הסחות — סימן למבחן, לא בהכרח התנגדות גבוהה
    if any(ch.isdigit() for ch in text) and ("×" in text or "*" in text or "x" in text_lower):
        signals.append("math_challenge")
        detection_attack = True

    score = max(0.0, min(1.0, score))
    trend = "stable"
    if previous_score is not None:
        delta = score - previous_score
        if delta >= 0.12:
            trend = "rising"
        elif delta <= -0.12:
            trend = "falling"

    return ResistanceReading(
        level=_level_from_score(score),
        score=round(score, 3),
        signals=signals[:8],
        detection_attack=detection_attack,
        trend=trend,
    )


class ResistanceMeter:
    """מד התנגדות מצטבר — שומר היסטוריה ומחשב מגמה."""

    def __init__(self, window: int = 8):
        self.window = window
        self.history: Deque[ResistanceSnapshot] = deque(maxlen=window)
        self.exchange = 0

    @property
    def last(self) -> Optional[ResistanceReading]:
        return self.history[-1].reading if self.history else None

    @property
    def current_level(self) -> str:
        return self.last.level if self.last else "medium"

    @property
    def current_score(self) -> float:
        return self.last.score if self.last else 0.5

    def update(
        self,
        voter_text: str,
        speech_pace: float = 1.0,
        speech_volume: float = 1.0,
    ) -> ResistanceReading:
        prev = self.current_score if self.history else None
        reading = measure_resistance(
            voter_text,
            speech_pace=speech_pace,
            speech_volume=speech_volume,
            previous_score=prev,
        )
        self.exchange += 1
        self.history.append(ResistanceSnapshot(exchange=self.exchange, reading=reading))
        return reading

    def average_score(self) -> float:
        if not self.history:
            return 0.5
        return sum(s.reading.score for s in self.history) / len(self.history)

    def rising_streak(self) -> int:
        streak = 0
        for snap in reversed(self.history):
            if snap.reading.trend == "rising":
                streak += 1
            else:
                break
        return streak

    def should_deescalate(self) -> bool:
        if not self.last:
            return False
        if self.last.level in ("high", "very_high"):
            return True
        return self.rising_streak() >= 2 and self.average_score() >= 0.55

    def should_enter_battle(self) -> bool:
        """עימות / מבחן זיהוי — מעבר ל-battle mode."""
        if not self.last:
            return False
        if self.last.detection_attack:
            return True
        return self.last.level == "very_high" and self.rising_streak() >= 1

    def summary(self) -> dict:
        return {
            "level": self.current_level,
            "score": self.current_score,
            "avg": round(self.average_score(), 3),
            "trend": self.last.trend if self.last else "stable",
            "rising_streak": self.rising_streak(),
            "detection_attack": bool(self.last and self.last.detection_attack),
            "should_deescalate": self.should_deescalate(),
            "should_enter_battle": self.should_enter_battle(),
            "exchanges": self.exchange,
            "signals": list(self.last.signals) if self.last else [],
        }
