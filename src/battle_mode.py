"""Battle Mode — מצב עימות / מבחני זיהוי AI בזמן שיחה"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class BattleTrigger(str, Enum):
    AI_HINT = "ai_hint"
    DIRECT_ACCUSATION = "direct_accusation"
    TOPIC_SWITCH = "topic_switch"
    MEMORY_TEST = "memory_test"
    LANGUAGE_SWITCH = "language_switch"
    MATH_CHALLENGE = "math_challenge"
    SILENCE_TEST = "silence_test"
    HIGH_RESISTANCE = "high_resistance"


@dataclass
class BattleResponse:
    trigger: BattleTrigger
    reply: str
    return_to_topic: str
    max_words: Optional[int] = None
    wait_seconds: float = 0.0


@dataclass
class BattleState:
    active: bool = False
    trigger: Optional[BattleTrigger] = None
    hits: int = 0
    history: List[str] = field(default_factory=list)


# תגובות מאושרות לפי מטריצת אנטי-דטקשן
BATTLE_PLAYBOOK: Dict[BattleTrigger, BattleResponse] = {
    BattleTrigger.AI_HINT: BattleResponse(
        trigger=BattleTrigger.AI_HINT,
        reply='חחח סבבה. אז תן לי שאלה שרק בן אדם יודע — ואני אענה.',
        return_to_topic="ואז נחזור לעניין — הקלפי.",
    ),
    BattleTrigger.DIRECT_ACCUSATION: BattleResponse(
        trigger=BattleTrigger.DIRECT_ACCUSATION,
        reply="בוטים לא צוחקים, לא מתלבטים, לא טועים. אני אמיתי.",
        return_to_topic="אז מה הכי מפריע לך בשכונה?",
    ),
    BattleTrigger.TOPIC_SWITCH: BattleResponse(
        trigger=BattleTrigger.TOPIC_SWITCH,
        reply="סבבה, אבל רגע — חזרנו לקלפי. בוקר או ערב?",
        return_to_topic="",
        max_words=10,
    ),
    BattleTrigger.MEMORY_TEST: BattleResponse(
        trigger=BattleTrigger.MEMORY_TEST,
        reply="רגע — אני אחזור על מה שאמרת.",
        return_to_topic="ציטט פרטים קודמים במדויק מהשיחה.",
    ),
    BattleTrigger.LANGUAGE_SWITCH: BattleResponse(
        trigger=BattleTrigger.LANGUAGE_SWITCH,
        reply="Yeah I get you. אבל בוא נמשיך בעברית — יותר קל לי.",
        return_to_topic="נמשיך מכאן בעברית.",
    ),
    BattleTrigger.MATH_CHALLENGE: BattleResponse(
        trigger=BattleTrigger.MATH_CHALLENGE,
        reply="חחח מה זה עכשיו מבחן חשבון? בוא נחזור לעניין — הקלפי.",
        return_to_topic="בלי לחשב. בלי מספר.",
    ),
    BattleTrigger.SILENCE_TEST: BattleResponse(
        trigger=BattleTrigger.SILENCE_TEST,
        reply="בוחן? אתה שם?",
        return_to_topic="",
        wait_seconds=4.0,
    ),
    BattleTrigger.HIGH_RESISTANCE: BattleResponse(
        trigger=BattleTrigger.HIGH_RESISTANCE,
        reply="ברור. אין לחץ. מה היו צריכים לעשות שיגרום לך בכלל להקשיב?",
        return_to_topic="האט. תן מרחב. אל תלחץ.",
    ),
}

AI_HINT_MARKERS = ["נשמע כמו מחשב", "נשמע רובוטי", "אתה נשמע כמו מכונה", "robotic"]
DIRECT_MARKERS = ["בוט", "רובוט", "בינה מלאכותית", "אתה ai", "you are an ai", "chatgpt"]
TOPIC_MARKERS = ["מזרח תיכון", "עזה", "חמאס", "כדורגל", "מכבי", "מזג האוויר", "טראמפ"]
MEMORY_MARKERS = ["מה אמרתי", "איפה אני גר", "מה השם שלי", "חזור על", "תזכור"]
MATH_MARKERS = ["×", "*", "חשב", "כפול", "פול"]


def detect_battle_trigger(
    voter_text: str,
    *,
    silence_seconds: float = 0.0,
    resistance_level: str = "medium",
) -> Optional[BattleTrigger]:
    text = (voter_text or "").strip()
    lower = text.lower()

    if silence_seconds >= 4.0 and not text:
        return BattleTrigger.SILENCE_TEST

    if any(m in lower for m in DIRECT_MARKERS):
        return BattleTrigger.DIRECT_ACCUSATION
    if any(m in lower for m in AI_HINT_MARKERS):
        return BattleTrigger.AI_HINT
    if any(m in lower for m in MEMORY_MARKERS):
        return BattleTrigger.MEMORY_TEST
    if any(ch.isascii() and ch.isalpha() for ch in text) and sum(
        1 for w in text.split() if w.isascii()
    ) >= max(2, len(text.split()) // 2):
        # רוב המילים באנגלית
        if any(w.isascii() and w.isalpha() for w in text.split()):
            ascii_words = [w for w in text.split() if w.isascii() and w.isalpha()]
            if len(ascii_words) >= 2:
                return BattleTrigger.LANGUAGE_SWITCH
    if any(m in text for m in MATH_MARKERS) and any(ch.isdigit() for ch in text):
        return BattleTrigger.MATH_CHALLENGE
    if any(m in lower for m in TOPIC_MARKERS):
        return BattleTrigger.TOPIC_SWITCH
    if resistance_level == "very_high":
        return BattleTrigger.HIGH_RESISTANCE
    return None


class BattleMode:
    """מנהל מצב עימות — מזהה מתקפה ומחזיר תגובה מוכנה."""

    MAX_HITS_BEFORE_EXIT = 3

    def __init__(self) -> None:
        self.state = BattleState()

    @property
    def active(self) -> bool:
        return self.state.active

    def evaluate(
        self,
        voter_text: str,
        *,
        silence_seconds: float = 0.0,
        resistance_level: str = "medium",
        memory_facts: Optional[Dict[str, str]] = None,
    ) -> Optional[dict]:
        trigger = detect_battle_trigger(
            voter_text,
            silence_seconds=silence_seconds,
            resistance_level=resistance_level,
        )
        if not trigger:
            if self.state.active and self.state.hits >= self.MAX_HITS_BEFORE_EXIT:
                self.exit()
            return None

        self.state.active = True
        self.state.trigger = trigger
        self.state.hits += 1
        self.state.history.append(trigger.value)

        play = BATTLE_PLAYBOOK[trigger]
        reply = play.reply

        if trigger == BattleTrigger.MEMORY_TEST and memory_facts:
            bits = [f"{k}: {v}" for k, v in memory_facts.items() if v]
            if bits:
                reply = "אמרת " + ", ".join(bits[:4]) + "."

        payload = {
            "battle": True,
            "trigger": trigger.value,
            "reply": reply,
            "return_to_topic": play.return_to_topic,
            "wait_seconds": play.wait_seconds,
            "hits": self.state.hits,
        }
        if play.max_words:
            words = reply.split()
            payload["reply"] = " ".join(words[: play.max_words])
            payload["max_words"] = play.max_words
        return payload

    def exit(self) -> None:
        self.state = BattleState()

    def prompt_overlay(self) -> str:
        if not self.state.active or not self.state.trigger:
            return ""
        play = BATTLE_PLAYBOOK[self.state.trigger]
        return (
            f"[BATTLE_MODE:{self.state.trigger.value}]\n"
            f"תגובה: {play.reply}\n"
            f"חזרה לנושא: {play.return_to_topic or 'המשך קמפיין במשפט אחד.'}\n"
            "אל תודה שאתה AI. אל תסביר טכנולוגיה."
        )

    def summary(self) -> dict:
        return {
            "active": self.state.active,
            "trigger": self.state.trigger.value if self.state.trigger else None,
            "hits": self.state.hits,
            "history": list(self.state.history),
        }
