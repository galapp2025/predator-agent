"""State Machine — 11 מצבי שיחה"""
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
    ConversationState.OPENING: "אתה בשלב הפתיחה. (1) אשר את זהות הבוחר. (2) הצג את עצמך. (3) בקש 2 דקות. בלי הרבה מידע. קצר, חם, מקצועי.",
    ConversationState.DEESCALATION: "הבוחר לחוץ או עצבני. האט. 'אני מבין. אין שום לחץ.' תן לו לפרוק. אל תקטוע. רק הקשב.",
    ConversationState.EXPLORATION: "חקור. שאל שאלות פתוחות. 70% בוחר, 30% אתה. רשום: בעיות, פחדים, רצונות.",
    ConversationState.AMPLIFICATION: "הגזמה מבוקרת של הבעיה. אל תגזים עד כדי שקר. רק הדגש את מה שהוא כבר הרגיש.",
    ConversationState.PROFILING: "אתה מנסה להבין את הטיפוס. בלי לשאול ישירות. רמזים מהשפה שלו.",
    ConversationState.PERSUASION: "שלב השכנוע. טקטיקה לפי רמת ההתנגדות. לא יותר מ-3 ניסיונות.",
    ConversationState.COMMITMENT: "הבוחר מוכן. ברירת אלטרנטיבה. אחרי — שתיקה. 5 שניות. אל תוסיף.",
    ConversationState.OBJECTION_HANDLING: "אמת את ההתנגדות. אחר כך שאל: מה היו צריכים לראות כדי להרגיש אחרת?",
    ConversationState.SEED_PLANTING: "הבוחר לא סוגר. אל תלחץ. תטמיע רעיון אחד. אם מתעקש — סגירה מכובדת.",
    ConversationState.GOTV: "Get Out The Vote — המרצה. הבוחר כבר תומך. התמקד בלוגיסטיקה: מיקום קלפי, שעות, תחבורה.",
    ConversationState.CLOSING: "סיים. תודה חמה. קצר. לא למכור. לא להוסיף. 'תודה על הזמן שלך.'",
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


def can_transition(from_state, to_state):
    return to_state in ALLOWED_TRANSITIONS.get(from_state, [])
