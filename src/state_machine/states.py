"""
State Machine — Pipecat-inspired Flow
"""

from enum import Enum
from typing import Dict


class Phase(Enum):
    OPENING = "opening"
    DEESCALATE = "deescalate"       # בוחר עוין/שלילי
    EXPLORE = "explore"             # בוחר ניטרלי
    AMPLIFY = "amplify"             # בוחר חיובי
    PROFILE = "profile"             # מיפוי DISC
    PERSUADE = "persuade"           # טקטיקת שכנוע
    COMMIT = "commit"               # בוחר מוכן להתחייב
    OBJECTION = "objection"         # התנגדות
    SEED = "seed"                   # זרע לעתיד — שחרר בכבוד
    CLOSE = "close"                 # סיום
    HANDOFF = "handoff"             # העברה לנציג אנושי


TRANSITIONS: Dict[Phase, Dict[str, Phase]] = {
    Phase.OPENING: {
        "hostile": Phase.DEESCALATE,
        "neutral": Phase.EXPLORE,
        "receptive": Phase.AMPLIFY,
        "timeout": Phase.CLOSE,
    },
    Phase.DEESCALATE: {
        "calm": Phase.EXPLORE,
        "still_hostile": Phase.DEESCALATE,
        "escalating": Phase.HANDOFF,
    },
    Phase.EXPLORE: {
        "profiled": Phase.PROFILE,
        "more_info": Phase.EXPLORE,
        "hostile": Phase.DEESCALATE,
    },
    Phase.AMPLIFY: {
        "profiled": Phase.PROFILE,
        "ready": Phase.PERSUADE,
    },
    Phase.PROFILE: {
        "ready": Phase.PERSUADE,
        "incomplete": Phase.EXPLORE,
    },
    Phase.PERSUADE: {
        "convinced": Phase.COMMIT,
        "hesitant": Phase.PERSUADE,
        "resistant": Phase.OBJECTION,
    },
    Phase.OBJECTION: {
        "handled": Phase.PERSUADE,
        "stuck": Phase.SEED,
        "escalating": Phase.HANDOFF,
    },
    Phase.SEED: {
        "done": Phase.CLOSE,
    },
    Phase.COMMIT: {
        "confirmed": Phase.CLOSE,
        "unconfirmed": Phase.PERSUADE,
    },
    Phase.CLOSE: {},
    Phase.HANDOFF: {
        "completed": Phase.CLOSE,
    },
}


class ConversationState:
    def __init__(self):
        self.current: Phase = Phase.OPENING
        self.history: list[Phase] = [Phase.OPENING]
        self.attempts: dict[Phase, int] = {}
        self.resistance_history: list[float] = []

    def transition(self, outcome: str) -> Phase:
        possible = TRANSITIONS.get(self.current, {})

        if outcome in possible:
            next_phase = possible[outcome]
        else:
            next_phase = self.current

        self.history.append(next_phase)
        self.current = next_phase
        self.attempts[next_phase] = self.attempts.get(next_phase, 0) + 1

        return next_phase

    def should_handoff(self) -> bool:
        """האם להעביר לנציג אנושי?"""
        return (
            self.attempts.get(Phase.OBJECTION, 0) >= 3 or
            self.attempts.get(Phase.DEESCALATE, 0) >= 4
        )

    def should_release(self) -> bool:
        """האם לשחרר בכבוד?"""
        return (
            self.attempts.get(Phase.PERSUADE, 0) >= 3 and
            Phase.COMMIT not in self.history
        )

    def phase_instructions(self) -> str:
        """הנחיות ל-LLM לפי שלב נוכחי"""
        instructions = {
            Phase.OPENING: "פתח בשיחה. בדוק מצב רוח. אל תמהר.",
            Phase.DEESCALATE: "הבוחר שלילי/עוין. הרגע. הסכם. 'אתה צודק, ו...'. אל תעלה הילוך.",
            Phase.EXPLORE: "זהה נושאים חשובים. תן לבוחר לדבר. הקשיב.",
            Phase.AMPLIFY: "הבוחר חיובי. חזק. הגבר אנרגיה. שתף סיפור חיובי.",
            Phase.PROFILE: "אסוף מידע למיפוי אישיותי. שאל שאלות ערכיות.",
            Phase.PERSUADE: "השתמש בטקטיקת השכנוע. הוביל לשינוי עמדה. דבר על מה הבוחר יפסיד.",
            Phase.COMMIT: "הבוחר מוכן. אשר, חזק, קבע צעד הבא. 'אפשר לסמן אותך?' 'מתי נוח — בוקר או ערב?'",
            Phase.OBJECTION: "התנגדות. הסכם → שאל → הצע אלטרנטיבה. אל תתווכח. 3 קלפים: הדדיות → אובדן → דלת-בפנים.",
            Phase.SEED: "שתול זרע לעתיד. סיים בחיוב. 'אם תשנה את דעתך — דבר איתי.'",
            Phase.CLOSE: "סיים בחום. קצר. 'תודה על הזמן. יום טוב.'",
            Phase.HANDOFF: "הצע העברה לנציג אנושי. אל תתעקש. 'תן לי לחבר אותך למישהו שיכול לעזור יותר טוב.'",
        }
        return instructions.get(self.current, "")
