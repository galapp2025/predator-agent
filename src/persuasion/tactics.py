"""
8 Persuasion Tactics — מוכנות ל-LLM
"""

TACTICS = {
    "loss_aversion": {
        "hebrew": "רתיעה מאובדן",
        "principle": "הדגש מה הבוחר יפסיד אם לא יתמוך — פי 2 חזק יותר ממה שירוויח",
        "template": "אם {opponent} ייבחר — {issue} תמשיך להידרדר. {call_to_action}",
        "when": "תמיד — טקטיקת ברירת מחדל. במיוחד לבוחרים אדישים.",
    },
    "social_proof": {
        "hebrew": "הוכחה חברתית",
        "principle": "כולם כבר תומכים — אתה תהיה האחרון?",
        "template": "{percent}% מהשכונה איתנו. {neighbor} כבר נרשם. {call_to_action}",
        "when": "מתאים ל-I ו-S. לבוחרים שמושפעים מהסביבה.",
    },
    "scarcity": {
        "hebrew": "מחסור ודחיפות",
        "principle": "זמן אוזל — תפעל עכשיו או תפסיד",
        "template": "נשארו {days} ימים. אם לא נתגייס — {consequence}. {call_to_action}",
        "when": "שבועיים-שלושה לפני הבחירות. כשיש דד-ליין אמיתי.",
    },
    "reciprocity": {
        "hebrew": "הדדיות",
        "principle": "תן ערך קטן → בקש. הבוחר 'חייב' לך.",
        "template": "בדקתי לך את {report}. תראה את המספרים. עכשיו — אתה מוכן לעזור? {call_to_action}",
        "when": "אחרי שנתת מידע שימושי. הבוחר מרגיש שקיבל משהו.",
    },
    "anchoring": {
        "hebrew": "עיגון",
        "principle": "הצג מספר גדול → ההצעה נראית קטנה",
        "template": "יודע מה {budget}? {big_number} שקל. יודע כמה הגיע לפה? {small_number}. {call_to_action}",
        "when": "לפרופיל C — אוהב מספרים. כשיש פער שאפשר להדגיש.",
    },
    "foot_in_door": {
        "hebrew": "רגל בדלת",
        "principle": "התחייבות קטנה → גדולה. סולם המיקרו-כן.",
        "template": "חשוב לך ש{value}? ברור. אז תגיד — אתה מוכן {small_ask}?",
        "when": "תחילת שיחה. בונה מומנטום. מתאים לכולם.",
    },
    "door_in_face": {
        "hebrew": "דלת בפנים",
        "principle": "בקשה גדולה → סירוב → בקשה אמיתית קטנה",
        "template": "היית רוצה {big_ask}? לא? אני מבין. אבל לפחות {real_ask}?",
        "when": "אחרי 2-3 סירובים. הקלף השלישי של Richard V12.",
    },
    "fear_then_relief": {
        "hebrew": "פחד → הקלה",
        "principle": "תאר מצב חמור, הפסקה, ואז פתרון",
        "template": "המצב {negative}... [שתיקה] אבל יש פתרון. {solution}. {call_to_action}",
        "when": "לבוחרים אדישים או מנותקים. מעורר רגש.",
    }
}


def get_tactic_instructions(tactic_name: str) -> str:
    """מחזיר הנחיות LLM לטקטיקה"""
    t = TACTICS.get(tactic_name, TACTICS["loss_aversion"])
    return f"""
## ⚔️ טקטיקה פעילה: **{t['hebrew']}**
- **עיקרון**: {t['principle']}
- **מבנה**: {t['template']}
- **מתי**: {t['when']}
"""


def get_tactic_by_profile(disc: str, resistance: float) -> str:
    """בוחר טקטיקה אופטימלית לפי פרופיל DISC + רמת התנגדות"""
    if resistance > 0.7:
        # התנגדות גבוהה — Door-in-Face או Fear-Then-Relief
        return "door_in_face"
    
    disc_tactic_map = {
        "D": "loss_aversion",     # "תפסיד" — ישיר, עוצמתי
        "I": "social_proof",      # "כולם איתנו" — חברתי
        "S": "fear_then_relief",  # "המצב קשה → יש פתרון" — מרגיע
        "C": "anchoring",         # "הנה המספרים" — מבוסס נתונים
    }
    
    return disc_tactic_map.get(disc, "loss_aversion")
