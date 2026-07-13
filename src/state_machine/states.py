"""State Machine — 11 מצבי שיחה"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List


class ConversationState(Enum):
    OPENING = "opening"
    DEESCALATION = "deescalation"
    EXPLORATION = "exploration"
    AMPLIFICATION = "amplification"
    PROFILING = "profiling"
    PERSUASION = "persuasion"
    COMMITMENT = "commitment"
    OBJECTION_HANDLING = "objection_handling"
    SEED_PLANTING = "seed_planting"
    GOTV = "gotv"
    CLOSING = "closing"


STATE_INSTRUCTIONS: Dict[ConversationState, str] = {
    ConversationState.OPENING: "אתה בשלב הפתיחה. (1) אשר זהות. (2) הצג את עצמך. (3) בקש 2 דקות. קצר, חם.",
    ConversationState.DEESCALATION: "הבוחר לחוץ. האט. 'אני מבין. אין לחץ.' תן לפרוק.",
    ConversationState.EXPLORATION: "חקור בשאלות פתוחות. 70% בוחר, 30% אתה.",
    ConversationState.AMPLIFICATION: "הדגש את הבעיה שהוא כבר הרגיש. בלי שקר.",
    ConversationState.PROFILING: "הבן DISC מרמזי שפה. אל תשאל ישירות.",
    ConversationState.PERSUASION: "שכנוע לפי התנגדות. עד 3 ניסיונות.",
    ConversationState.COMMITMENT: "ברירת אלטרנטיבה. אחרי — שתיקה 5 שניות.",
    ConversationState.OBJECTION_HANDLING: "אמת התנגדות. שאל מה היה משנה.",
    ConversationState.SEED_PLANTING: "רעיון אחד. בלי לחץ. יציאה מכובדת.",
    ConversationState.GOTV: "כבר תומך — לוגיסטיקה: קלפי, שעה, הגעה.",
    ConversationState.CLOSING: "תודה חמה. קצר. לא למכור.",
}

ALLOWED_TRANSITIONS: Dict[ConversationState, List[ConversationState]] = {
    ConversationState.OPENING: [ConversationState.EXPLORATION, ConversationState.DEESCALATION, ConversationState.GOTV],
    ConversationState.DEESCALATION: [ConversationState.EXPLORATION, ConversationState.CLOSING],
    ConversationState.EXPLORATION: [ConversationState.AMPLIFICATION, ConversationState.PROFILING, ConversationState.PERSUASION],
    ConversationState.AMPLIFICATION: [ConversationState.PERSUASION, ConversationState.PROFILING],
    ConversationState.PROFILING: [ConversationState.PERSUASION, ConversationState.OBJECTION_HANDLING],
    ConversationState.PERSUASION: [ConversationState.COMMITMENT, ConversationState.OBJECTION_HANDLING, ConversationState.SEED_PLANTING],
    ConversationState.OBJECTION_HANDLING: [ConversationState.PERSUASION, ConversationState.SEED_PLANTING, ConversationState.CLOSING],
    ConversationState.SEED_PLANTING: [ConversationState.CLOSING, ConversationState.PERSUASION],
    ConversationState.COMMITMENT: [ConversationState.CLOSING],
    ConversationState.GOTV: [ConversationState.CLOSING, ConversationState.OBJECTION_HANDLING],
    ConversationState.CLOSING: [],
}


def can_transition(from_state: ConversationState, to_state: ConversationState) -> bool:
    return to_state in ALLOWED_TRANSITIONS.get(from_state, [])
