#!/usr/bin/env python3
"""
🎙 PREDATOR AGENT — LIVE VOICE SERVER v2
═══════════════════════════════════════════════════════════════
צינור קולי מלא: מיקרופון ← Deepgram STT ← Predator Pipeline ← LLM ← Cartesia TTS ← רמקול

LLM: Groq (llama-3.3-70b) > OpenAI (gpt-4.1-mini) > fallback
Fallback: 8-12 תשובות בעברית לכל state × persona

הרצה: cd /home/user/predator-agent && python3 live_voice_server.py
"""

import asyncio
import base64
import json
import logging
import os
import random
import sys
import time
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import websockets
from websockets.server import WebSocketServerProtocol
from dotenv import load_dotenv
load_dotenv()

from src.agent.predator import PredatorAgent
from src.enrichment.voter_context import VoterContextBuilder
from src.personas.persona_base import get_persona

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("voice-server")

# ── Configuration ───────────────────────────────────────
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
CARTESIA_API_KEY = os.getenv("CARTESIA_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

CARTESIA_VOICE_MALE = os.getenv("CARTESIA_VOICE_MALE", "ff857c8e-e7f9-4afd-af42-dce9f3c5ab02")
CARTESIA_VOICE_FEMALE = os.getenv("CARTESIA_VOICE_FEMALE", "3e32f3c5-9ac0-4192-9994-87fdb277120f")

DEEPGRAM_WS_URL = "wss://api.deepgram.com/v1/listen"
CARTESIA_TTS_URL = "https://api.cartesia.ai/tts/bytes"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

SAMPLE_RATE = 16000


def _is_real_key(key: str) -> bool:
    """Check if a key looks like a real API key, not a placeholder."""
    if not key or len(key) < 15:
        return False
    if "xxx" in key.lower():
        return False
    return True


# ── Test voter context ──────────────────────────────────
TEST_VOTER = {
    "first_name": "אורי",
    "last_name": "כהן",
    "city": "תל אביב",
    "street": "אבן גבירול",
    "house_number": "45",
    "registered_branch": "תל אביב",
    "support_score": 0.55,
    "campaign_type": "primaries",
}


# ═══════════════════════════════════════════════════════════
# RICH FALLBACK RESPONSES — 8-12 per state, persona-aware
# ═══════════════════════════════════════════════════════════

FALLBACKS = {
    "opening": {
        "D": [
            "שלום, אלון מהמטה. תקשיב, אני אגיד לך ישר — יש לך שתי דקות?",
            "אלון. שלום. שמע, חשוב — הבחירות בפתח. אפשר רגע?",
            "שלום. מדבר ממטה [המועמד]. תכלס, אני צריך שתי דקות.",
            "היי. אלון. בוא נדבר תכלס — יש לך זמן קצר?",
            "שלום. מהקמפיין. דבר חשוב. שתי דקות?",
            "אלון, שלום. תשמע — העניין פשוט. בוא נדבר רגע.",
            "שלום. אלון מהמטה. בוא נדבר עכשיו, אני אקצר.",
            "שלום. יש לך דקה? זה חשוב.",
        ],
        "I": [
            "שלום! מיה מהמטה. וואלה, שמחה שענית. יש לך רגע?",
            "היי! מיה. בוקר טוב! שמע, דיברתי עם מישהו מהשכונה שלך — תן לי לספר לך.",
            "שלום! מיה מהקמפיין. איזה כיף שענית! יש לך שתי דקות?",
            "היי! מיה פה. תשמע, יש לי סיפור קטן — אבל קודם, אתה פנוי?",
            "שלום שלום! מיה. וואלה, התגעגעתי לשמוע קולות מהשכונה שלך.",
            "בוקר אור! מיה מהמטה. יש לך רגע למשהו טוב?",
            "שלום! מיה פה. שמע, משהו מרגש קרה ואני חייבת לשתף.",
            "היי, מיה. נפלתי עליך במקרה? [צחוק] לא, בכוונה. יש לך דקה?",
        ],
        "S": [
            "שלום. דוד, מהמטה. שמע, אני יודע שאתה עסוק — לא אקח הרבה זמן.",
            "שלום. דוד. תקשיב, אין שום לחץ. רק רציתי להגיד לך משהו קטן.",
            "ערב טוב. דוד מהמטה. אני יודע שזה לא זמן נוח — אבל זה חשוב.",
            "שלום. דוד פה. שמע, קח נשימה — זה לא דחוף, אבל כדאי שתשמע.",
            "שלום. דוד. אני כאן. לאט. יש לך רגע?",
            "דוד, שלום. שמע, אני מתקשר בלב שלם — אפשר לדבר?",
            "שלום. דוד מהקמפיין. אני לא ממהר. יש לך זמן?",
            "שלום. דוד. תקשיב, אני לא אחד שלוחץ. אבל יש משהו שחשוב לי שתדע.",
        ],
        "C": [
            "שלום, רונית מהמטה. שלוש עובדות, ואתה מחליט. יש לך שתי דקות?",
            "שלום. רונית מהקמפיין. אני אגיע ישר לעניין — יש לך רגע?",
            "רונית. שלום. בדקתי. מצאתי. יש לך זמן לשמוע?",
            "שלום, רונית. העובדות פשוטות — אפשר לדבר?",
            "שלום. רונית מהמטה. מסתבר ש— רגע, קודם כל, אתה פנוי?",
            "רונית פה. שלום. אני אדבר במדויק. יש לך דקה?",
            "שלום. רונית. הנתונים מראים משהו מעניין. אפשר לשתף?",
            "שלום. רונית מהמטה. בלי הקדמות — יש לך זמן למספרים?",
        ],
    },
    "exploration": {
        "D": [
            "תגיד, מה הכי חשוב לך בשכונה? תכלס.",
            "שמע, בוא נדבר תכלס — מה היית רוצה לראות משתנה?",
            "תקשיב, מה מעצבן אותך בשכונה? תגיד לי ישר.",
            "תכלס — מה הדבר הראשון שהיית משנה פה?",
            "שמע, אני רוצה להבין — מה באמת חשוב לך?",
            "בוא נדבר גלויות. מה הבעיה הכי גדולה בשכונה?",
            "תגיד, מה היית רוצה שהמועמד יעשה? בכנות.",
            "תקשיב, אני שואל ישר — מה חסר לך פה?",
        ],
        "I": [
            "תגיד, מה הכי חשוב לך בשכונה? ספר לי.",
            "וואלה, מעניין אותי — מה היית רוצה לראות משתנה?",
            "שמע, יש לי תחושה שאתה מכיר את השכונה טוב. מה דעתך?",
            "תאר לך — מה הדבר שהיה הכי משמח אותך לראות פה?",
            "אני סקרנית — מה אתה אוהב בשכונה? ומה פחות?",
            "ספר לי קצת — אתה גר פה הרבה זמן? מה השתנה?",
            "וואלה, תשתף אותי — מה הסיפור של השכונה?",
            "מעניין לי לשמוע — מה דעתך על מה שקורה פה?",
        ],
        "S": [
            "תקשיב, אין לחץ — ספר לי, מה חשוב לך בשכונה?",
            "אני מקשיב. מה אתה חושב? מה היית רוצה לשנות?",
            "קח את הזמן. מה הכי מטריד אותך בשכונה?",
            "אני באמת רוצה להבין — מה דעתך על המצב?",
            "תן לי להקשיב. מה אתה מרגיש לגבי השכונה?",
            "אני כאן. לאט. מה הכי חסר לך פה?",
            "בוא נדבר. מה היית רוצה שהמועמד ידע?",
            "שמע, אני לא ממהר. מה אתה אומר?",
        ],
        "C": [
            "בוא נבין — מה המצב בשכונה? מה דעתך?",
            "אני רוצה להבין את התמונה. מה אתה חושב?",
            "המספרים מספרים סיפור — אבל מה הסיפור שלך?",
            "בוא ננתח רגע — מה עובד ומה לא בשכונה?",
            "אני אוספת מידע. מה דעתך על המצב?",
            "תן לי להבין — מה הנתונים שאתה רואה בשטח?",
            "מה העובדות בשכונה? מה אתה רואה?",
            "בוא נדייק. מה המצב האמיתי פה?",
        ],
    },
    "profiling": {
        "D": [
            "אז אתה גר פה, מכיר את השכונה. תגיד — יש משהו שמעצבן אותך במיוחד?",
            "תקשיב, כמה זמן אתה גר פה? אתה מכיר את השכנים?",
            "שמע, בוא ניכנס קצת יותר. מה הסיפור שלך עם השכונה?",
            "תכלס, אתה מעורב במה שקורה פה?",
            "תגיד, יש לך משפחה? ילדים? זה משנה.",
        ],
        "I": [
            "אז ספר לי — כמה זמן אתה גר פה? יש סיפורים?",
            "וואלה, אני מרגישה שאתה מחובר לשכונה. מה הסיפור?",
            "תגיד, יש לך ילדים? הם גדלים פה?",
            "אני בטוחה שיש לך חוויות מהשכונה. ספר לי אחת.",
            "מה אתה אוהב פה? ומה פחות? תשתף.",
        ],
        "S": [
            "אני מבין. ואתה — כמה זמן אתה חלק מהשכונה?",
            "תקשיב, תן לי להבין אותך יותר טוב. מה הסיפור שלך?",
            "אני מקשיב. מה חשוב לך בחיים, מעבר לשכונה?",
            "תן לי להכיר אותך. מה אתה עושה? מה מעסיק אותך?",
            "קח את הזמן. מה היית רוצה שאני אדע עליך?",
        ],
        "C": [
            "בוא נדייק. כמה זמן אתה גר פה? זה עוזר להבין.",
            "אני רוצה למפות את המצב. מה הרקע שלך בשכונה?",
            "כמה זמן אתה פה? ומה הקשר שלך לקהילה?",
            "הנתונים מראים ש— אבל קודם, בוא נבין אותך.",
            "אני צריכה להבין את התמונה. מה הסיפור שלך?",
        ],
    },
    "persuasion": {
        "D": [
            "תדמיין עוד חודשיים — בית ספר משופץ. כי מישהו השקיע. מישהו שבחרת.",
            "בשנה שעברה היו 30 קולות הפרש. 30. אתה מבין כמה זה קרוב?",
            "תקשיב — אם אתה לא בא, מישהו אחר מחליט בשבילך. זה מה שיקרה.",
            "שמע, 5 דקות. זה מה שמפריד בינך לבין שינוי אמיתי.",
            "תכלס — כל בחירות יש תירוצים. אבל פה, ההפרש זעיר. הקול שלך מכריע.",
            "אני אגיד לך משהו בכנות — בלי הקול שלך, הסיכוי שלנו יורד דרמטית.",
        ],
        "I": [
            "תאר לך — עוד שנתיים הילדה שלך מסיימת תיכון משופץ. כי מישהו השקיע.",
            "דמיין שאתה יוצא מהבית בבוקר — אין פקקים, פארק ליד, תאורה. מרגיש בטוח.",
            "וואלה, אני מתרגשת כשאני חושבת על זה — יש סיכוי אמיתי לשינוי.",
            "שמע, היה לי בוחר שלשום — בדיוק כמוך. הוא בא, הצביע, והיום הוא מספר לכולם.",
            "תדמיין את השכונה בעוד שנה. יותר ירוק, יותר בטוח. זה אפשרי.",
            "אני רואה את הפוטנציאל. אבל צריך את הקול שלך. בלעדיך — זה לא יקרה.",
        ],
        "S": [
            "תחשוב על זה — עוד שנה, הילדים שלך משחקים בפארק משופץ. והכל התחיל בהחלטה קטנה.",
            "אני לא אלחץ. אבל תן לי לשאול — איך תרגיש אם המועמד מפסיד ב-20 קולות?",
            "תקשיב, אני מבין את ההתלבטות. באמת. אבל תן לי לספר לך משהו.",
            "אני רואה בן אדם שחשוב לו. וזו בדיוק הסיבה שאתה צריך לבוא.",
            "ההחלטה הזו — היא לא רק על פוליטיקה. היא על העתיד של השכונה שלך.",
            "אני לא מבקש הרבה. רק שתחשוב — מה היית רוצה לראות פה?",
        ],
        "C": [
            "המספרים מראים: 30 קולות הכריעו בפעם הקודמת. 30. זה סטטיסטי.",
            "אם תסתכל על הנתונים — כל קול בבחירות האלה שווה פי 3 מבחירות רגילות.",
            "העובדות פשוטות: בלי הקול שלך, הסיכוי לשינוי יורד ב-40%.",
            "בדקתי. מצאתי. בבחירות הקודמות, 20 קולות הכריעו את התוצאה.",
            "אני לא אומרת את זה סתם — הנתונים מראים שכל קול משנה.",
            "יש פה משוואה פשוטה: אתה בא = יש סיכוי. אתה לא בא = אין.",
        ],
    },
    "commitment": {
        "D": [
            "אז בוא נעשה משהו — שלישי בבוקר או בערב?",
            "תכלס — אתה בא? שלישי בבוקר, יותר נוח?",
            "יאללה, בוא נסגור. שלישי בבוקר או יותר נוח לך בערב?",
            "אז — שלישי. בוקר? ערב? מה עובד לך?",
            "תרשום: שלישי. קלפי בית ספר הרמז. בא לך?",
        ],
        "I": [
            "יאללה, בוא. שלישי בבוקר עובד לך?",
            "אז מה דעתך? בא לך לבוא ביום שלישי? בוקר או ערב?",
            "וואלה, אני מתרגשת. שלישי בבוקר, נכון?",
            "בוא נקבע — שלישי. מתי יותר נוח לך?",
            "יאללה, בוא. שלישי בערב? קבעתי?",
        ],
        "S": [
            "אם בא לך — אני כאן. יום שלישי?",
            "בוא נחשוב ביחד. שלישי בבוקר מתאים?",
            "אני לא לוחץ. אבל אם תרצה — שלישי.",
            "מה אתה אומר? שלישי — אפשרי?",
            "תחשוב על זה. שלישי. מה דעתך?",
        ],
        "C": [
            "המספרים ברורים. שלישי בבוקר — בא לך?",
            "העובדות מדברות. שלישי — בוקר או ערב?",
            "הנתונים מראים ששלישי זה היום. באיזה שעה?",
            "בוא נדייק. שלישי. בוקר? ערב?",
            "המשוואה פשוטה. שלישי. מתי?",
        ],
    },
    "closing": {
        "D": [
            "מעולה. אני רושם. תזכורת בוואטסאפ. נתראה בשלישי.",
            "אחלה. סגרנו. שלישי. תגיע, תשים פתק. חמש דקות.",
            "יופי. זהו. תזכורת בדרך. נתראה.",
            "מצוין. אני סומך עליך. נתראה בשלישי.",
        ],
        "I": [
            "מעולה! אני רושמת אותך. תזכורת בוואטסאפ. נתראה בשלישי!",
            "אחלה! איזה כיף. תגיע, תשים פתק. חמש דקות וזהו.",
            "יואו, איזה כיף! סגרנו. תזכורת בדרך. ביי!",
            "וואלה, שמחה! נתראה בשלישי. תזכורת מגיעה.",
        ],
        "S": [
            "יופי. אני רושם. תזכורת בוואטסאפ. נתראה.",
            "טוב. אני שמח. תגיע בשלישי. בלי לחץ.",
            "מצוין. סגרנו. אני פה אם צריך משהו.",
            "בסדר גמור. נתראה בשלישי. תודה.",
        ],
        "C": [
            "מעולה. רשום: שלישי. הנתונים מדויקים. נתראה.",
            "אושר. הקלפי ממתינה. שלישי. תזכורת נשלחת.",
            "מצוין. המידע ברור. נתראה בשלישי.",
            "בסדר. הנתונים מעודכנים. שלישי. תודה.",
        ],
    },
    "objection_handling": {
        "D": [
            "שמע, אני מבין. אבל תן לי לשאול — מה הדבר שהכי היה משכנע אותך?",
            "תקשיב, אני שומע. אבל בוא נדבר תכלס — מה מפריע לך?",
            "אני מבין את ההתנגדות. אבל תן לי לשאול אותך משהו אחר.",
            "בסדר. אני שומע. עכשיו תגיד לי — מה באמת?",
        ],
        "I": [
            "וואלה, אני מבינה. אבל תן לי לשאול — מה באמת מפריע לך?",
            "אני שומעת אותך. לגמרי. אבל יש לי שאלה אחת.",
            "אני מרגישה שיש פה משהו. מה באמת? דבר איתי.",
            "אני מבינה. לגמרי. אבל... יש סיכוי שאתה טועה?",
        ],
        "S": [
            "אני שומע. באמת. קח את הזמן — מה הכי מטריד?",
            "אני מבין. לגמרי. תן לי לשאול אותך משהו.",
            "אני כאן. בלי לחץ. תגיד לי מה בלב.",
            "תקשיב, אני מכבד. אבל תן לי להבין יותר.",
        ],
        "C": [
            "אני מבינה. בוא ננתח — מה בדיוק מפריע לך?",
            "הנתונים מראים ש— אבל קודם, מה הבעיה?",
            "בוא נפרק את זה. מה בדיוק לא מסתדר לך?",
            "אני רוצה להבין. מה העובדות שאתה רואה?",
        ],
    },
    "seed_planting": {
        "D": [
            "אני לא אלחץ. אבל תזכור — כשיגיע יום שלישי, תחשוב על השכונה.",
            "טוב. אני משאיר לך את המספר. כשתרצה לדבר — אני פה.",
            "תקשיב, אני מכבד. אבל המספר שלי אצלך. דבר איתי כשתחליט.",
        ],
        "I": [
            "אני לא אלחץ. אבל תזכור מה דיברנו. כשיגיע יום שלישי — אתה יודע.",
            "טוב, מותק. אני משאירה לך את המספר. דבר איתי כשבא לך.",
            "וואלה, אני מבינה. אבל תדע — יש פה משהו טוב. דבר איתי.",
        ],
        "S": [
            "אני לא לוחץ. אבל תדע — אני כאן. גם בעוד שבוע.",
            "טוב. המספר שלי שמור אצלך. דבר איתי כשנוח.",
            "קח את הזמן. אני לא בורח. דבר איתי.",
        ],
        "C": [
            "הנתונים כאן. כשתחליט — אני פה. המספר שמור.",
            "אני משאירה את המידע. כשתגיע להחלטה — דבר איתי.",
            "העובדות לא בורחות. קח את הזמן. אני פה.",
        ],
    },
    "deescalation": {
        "D": [
            "אני שומע. ואני מכבד. לא באתי לריב, באתי לדבר.",
            "תקשיב, אני לא אויב. אני בצד שלך. באמת.",
            "בוא נרגע רגע. אני לא פה כדי להתווכח.",
        ],
        "I": [
            "וואלה, אני שומעת. סליחה אם זה נשמע אחרת. לא באתי לריב.",
            "אני מצטערת. בוא נתחיל מחדש. אני פה בשבילך.",
            "אני מבינה שאתה כועס. זה בסדר. אני כאן.",
        ],
        "S": [
            "שמע, אני שומע. קח נשימה. אני לא פה כדי להילחם.",
            "אני מרגיש את התסכול. וזה בסדר. אני איתך.",
            "בוא ניקח רגע. אני לא ממהר. אני כאן.",
        ],
        "C": [
            "אני מבינה. בוא ניקח צעד אחורה. מה השתבש?",
            "אני מזהה שיש פה קונפליקט. בוא נפתור את זה.",
            "בוא נדייק. מה בדיוק מפריע? אני רוצה להבין.",
        ],
    },
    "gotv": [
        "תגיע. שלישי. בית ספר הרמז. חמש דקות. זה הכל.",
        "שלישי. קלפי. אתה יודע איפה. בוא.",
        "תגיע. זה חשוב. 5 דקות מהחיים שלך. בשביל השכונה.",
        "אל תשכח — שלישי. קלפי בית ספר הרמז. 3 דקות ממך.",
        "שלישי. בוא. תעשה הבדל.",
        "תזכורת: שלישי. בוקר. קלפי. בא לך.",
    ],
}


def _get_fallback(state: str, persona_disc: str) -> str:
    """Get a persona-appropriate Hebrew fallback response."""
    persona_map = {"D": "D", "I": "I", "S": "S", "C": "C"}
    disc = persona_map.get(persona_disc, "S")

    # gotv is a list, not a dict
    if state == "gotv":
        return random.choice(FALLBACKS["gotv"])

    state_responses = FALLBACKS.get(state, {})
    responses = state_responses.get(disc, state_responses.get("S", ["אני מבין. תמשיך."]))
    return random.choice(responses)


# ═══════════════════════════════════════════════════════════
# Voice Agent Session
# ═══════════════════════════════════════════════════════════

class VoiceAgentSession:
    """Manages a single voice conversation: STT → Pipeline → LLM → TTS."""

    def __init__(self, agent: PredatorAgent, builder: VoterContextBuilder):
        self.agent = agent
        self.builder = builder
        self.session_id: Optional[str] = None
        self.deepgram_ws: Optional[websockets.WebSocketClientProtocol] = None
        self.last_final_transcript = ""
        self.pending_response = False
        self._last_response = None
        self._dg_connected = False
        self._stt_started = False

    async def start(self, voter_profile: dict = None):
        """Create Predator session and connect to Deepgram."""
        profile = voter_profile or TEST_VOTER
        ctx = self.builder.build(**profile)
        self.session_id = f"voice-{int(datetime.now().timestamp())}"
        session = self.agent.create_session(self.session_id, voter_context=ctx)

        persona = get_persona(session.current_persona)
        print(f"\n📞 שיחה קולית חדשה — {self.session_id}")
        print(f"   בוחר: {profile.get('first_name', '?')} {profile.get('last_name', '?')}")
        print(f"   פרסונה: {persona.name} ({session.current_persona})")
        print(f"   תמיכה: {session.support_score:.2f}")
        print(f"   {'─'*50}")

        # Connect to Deepgram STT
        if _is_real_key(DEEPGRAM_API_KEY):
            await self._connect_deepgram()

    async def _connect_deepgram(self):
        """Connect to Deepgram WebSocket for STT."""
        try:
            dg_url = (
                f"{DEEPGRAM_WS_URL}?"
                f"encoding=linear16&sample_rate={SAMPLE_RATE}"
                f"&punctuate=true&interim_results=true&utterance_end_ms=800"
            )
            self.deepgram_ws = await websockets.connect(
                dg_url,
                additional_headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"},
                ping_interval=5,
                ping_timeout=3,
                close_timeout=3,
            )
            self._dg_connected = True
            asyncio.create_task(self._listen_deepgram())
            print(f"   📋 Deepgram STT: מחובר")
        except Exception as e:
            print(f"   ⚠️  Deepgram STT: נכשל ({e}) — המשך ללא תמלול")
            self._dg_connected = False

    async def feed_audio(self, audio_bytes: bytes):
        """Receive audio chunk from browser, forward to Deepgram."""
        if self._dg_connected and self.deepgram_ws and self.deepgram_ws.open:
            try:
                await self.deepgram_ws.send(audio_bytes)
            except Exception:
                self._dg_connected = False

    async def _listen_deepgram(self):
        """Continuously receive STT results from Deepgram."""
        if not self.deepgram_ws:
            return
        try:
            async for message in self.deepgram_ws:
                data = json.loads(message)
                await self._handle_deepgram_result(data)
        except Exception as e:
            logger.error(f"Deepgram listener error: {e}")
            self._dg_connected = False

    async def _handle_deepgram_result(self, data: dict):
        """Process Deepgram result — interim or final transcript."""
        channel = data.get("channel", {})
        alternatives = channel.get("alternatives", [])
        if not alternatives:
            return

        transcript = alternatives[0].get("transcript", "").strip()
        if not transcript:
            return

        is_final = data.get("is_final", False)
        speech_final = data.get("speech_final", False)

        if is_final or speech_final:
            if transcript and transcript != self.last_final_transcript:
                self.last_final_transcript = transcript
                print(f"\n🧪 בוחר: {transcript}")
                await self._process_voter_turn(transcript)
        else:
            if transcript != self.last_final_transcript and len(transcript) > 5:
                print(f"   (מתומלל: {transcript})", end="\r")

    async def _process_voter_turn(self, voter_text: str):
        """Run voter text through the full Predator pipeline, then LLM, then TTS."""
        if not self.session_id:
            return

        self.pending_response = True
        t0 = time.time()

        try:
            result = await self.agent.process_voter_turn(self.session_id, voter_text)
        except Exception as e:
            print(f"   ❌ שגיאת צינור: {e}")
            self.pending_response = False
            return

        pipe_time = (time.time() - t0) * 1000

        if "error" in result:
            print(f"   ❌ שגיאה: {result['error']}")
            self.pending_response = False
            return

        state = result["state"]
        resistance = result["resistance"]
        persona = result["persona"]
        tactic = result.get("tactic", "-")
        prompt_len = len(result["system_prompt"])
        tts_speed = result["tts_params"]["speed"]
        p = get_persona(persona)

        # ── Generate agent response via LLM ──
        t1 = time.time()
        agent_text = await self._generate_llm_response(result["system_prompt"], voter_text)
        llm_time = (time.time() - t1) * 1000

        if not agent_text:
            agent_text = _get_fallback(state, persona)

        # Record in session
        self.agent.add_assistant_response(self.session_id, agent_text)

        print(f"\n🤖 סוכן ({p.name}): {agent_text[:120]}{'...' if len(agent_text) > 120 else ''}")
        print(f"   [state={state} resist={resistance} tactic={tactic} tts={tts_speed}]")
        print(f"   ⏱ pipe={pipe_time:.0f}ms llm={llm_time:.0f}ms")

        # ── TTS via Cartesia ──
        t2 = time.time()
        voice_id = CARTESIA_VOICE_MALE if persona in ("D", "S") else CARTESIA_VOICE_FEMALE
        audio_data = await self._synthesize_speech(agent_text, voice_id, tts_speed)
        tts_time = (time.time() - t2) * 1000

        if audio_data:
            print(f"   🔈 TTS: {len(audio_data)} bytes ב-{tts_time:.0f}ms")

        self._last_response = {
            "type": "agent_response",
            "text": agent_text,
            "state": state,
            "resistance": resistance,
            "persona": persona,
            "persona_name": p.name,
            "tactic": tactic,
            "tts_speed": tts_speed,
            "audio": base64.b64encode(audio_data).decode("utf-8") if audio_data else None,
            "prompt_chars": prompt_len,
        }
        self.pending_response = False

    async def _generate_llm_response(self, system_prompt: str, voter_text: str) -> Optional[str]:
        """Use Groq > OpenAI to generate Hebrew response."""
        now = time.time()
        # Groq TPM limit: 12K tokens/min. Prompt ~7500 tokens = ~1 req per 38s max.
        # Throttle: only use Groq if last call was > 30s ago.
        groq_cooldown = 30 if not hasattr(self, '_last_groq_time') else \
            (30 - (now - self._last_groq_time)) if (now - self._last_groq_time) < 30 else 0

        # Trim prompt for Groq to stay under TPM
        trimmed_prompt = system_prompt
        if len(system_prompt) > 10000:
            # Keep first 60% + last 40% — preserves core instructions + final reminders
            keep_first = int(10000 * 0.6)
            keep_last = 10000 - keep_first
            trimmed_prompt = system_prompt[:keep_first] + "\n\n[...]\n\n" + system_prompt[-keep_last:]

        # Groq first (fast, but 12K TPM limit on on-demand)
        if _is_real_key(GROQ_API_KEY) and groq_cooldown <= 0:
            self._last_groq_time = now
            result = await self._call_llm(
                GROQ_API_URL, GROQ_API_KEY, "llama-3.3-70b-versatile",
                trimmed_prompt, voter_text
            )
            if result:
                return result
            # Groq failed — try OpenAI with full prompt

        # OpenAI second (higher limits, more reliable)
        if _is_real_key(OPENAI_API_KEY):
            return await self._call_llm(
                OPENAI_API_URL, OPENAI_API_KEY, "gpt-4.1-mini",
                system_prompt, voter_text
            )

        return None

    async def _call_llm(
        self, url: str, api_key: str, model: str,
        system_prompt: str, voter_text: str,
    ) -> Optional[str]:
        """Generic LLM API call (OpenAI-compatible endpoint)."""
        try:
            import aiohttp
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            body = {
                "model": model,
                "temperature": 0.82,
                "max_tokens": 150,
                "top_p": 0.92,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": voter_text},
                ],
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, headers=headers, json=body,
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data["choices"][0]["message"]["content"].strip()
                    else:
                        text_err = await resp.text()
                        logger.error(f"LLM error {resp.status}: {text_err[:200]}")
        except Exception as e:
            logger.error(f"LLM error ({model}): {e}")
        return None

    async def _synthesize_speech(self, text: str, voice_id: str, speed: float = 1.0) -> Optional[bytes]:
        """Call Cartesia TTS API, return raw PCM audio bytes."""
        if not _is_real_key(CARTESIA_API_KEY):
            return None

        try:
            import aiohttp
            headers = {
                "X-API-Key": CARTESIA_API_KEY,
                "Cartesia-Version": "2024-06-30",
                "Content-Type": "application/json",
            }
            body = {
                "model_id": "sonic-3",
                "transcript": text,
                "voice": {"mode": "id", "id": voice_id},
                "output_format": {
                    "container": "raw",
                    "encoding": "pcm_s16le",
                    "sample_rate": 24000,
                },
                "language": "he",
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    CARTESIA_TTS_URL,
                    headers=headers, json=body,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        return await resp.read()
                    else:
                        text_err = await resp.text()
                        logger.error(f"Cartesia error {resp.status}: {text_err[:200]}")
        except Exception as e:
            logger.error(f"TTS error: {e}")
        return None

    @property
    def last_response(self):
        return getattr(self, "_last_response", None)

    async def close(self):
        """Clean up session."""
        if self.deepgram_ws and self.deepgram_ws.open:
            await self.deepgram_ws.close()
        if self.session_id:
            self.agent.end_session(self.session_id)
            print(f"\n📴 שיחה הסתיימה — {self.session_id}")


# ═══════════════════════════════════════════════════════════
# WebSocket Server
# ═══════════════════════════════════════════════════════════

class VoiceServer:
    def __init__(self):
        self.agent = PredatorAgent(
            anthropic_api_key=ANTHROPIC_API_KEY if _is_real_key(ANTHROPIC_API_KEY) else None,
            openai_api_key=OPENAI_API_KEY if _is_real_key(OPENAI_API_KEY) else None,
        )
        self.builder = VoterContextBuilder()
        self.sessions: dict = {}

    async def handle(self, ws: WebSocketServerProtocol):
        """Handle a WebSocket client connection."""
        client_id = f"{ws.remote_address[0]}:{ws.remote_address[1]}"
        print(f"\n🔌 חיבור חדש: {client_id}")

        voice = VoiceAgentSession(self.agent, self.builder)
        self.sessions[ws] = voice

        try:
            await voice.start()

            # Send session info to client
            session_info = self.agent.get_session(voice.session_id)
            if session_info:
                persona = get_persona(session_info.current_persona)
                await ws.send(json.dumps({
                    "type": "session_started",
                    "session_id": voice.session_id,
                    "persona": session_info.current_persona,
                    "persona_name": persona.name,
                    "support_score": session_info.support_score,
                }, ensure_ascii=False))

            # Main message loop
            async for message in ws:
                if isinstance(message, bytes):
                    await voice.feed_audio(message)
                elif isinstance(message, str):
                    data = json.loads(message)
                    msg_type = data.get("type", "")

                    if msg_type == "audio":
                        audio_bytes = base64.b64decode(data["data"])
                        await voice.feed_audio(audio_bytes)
                    elif msg_type == "text":
                        # Allow text input for testing without mic
                        text = data.get("content", "")
                        if text:
                            await voice._process_voter_turn(text)
                    elif msg_type == "ping":
                        await ws.send(json.dumps({"type": "pong"}))
                    elif msg_type == "end_call":
                        print(f"\n📴 בוחר סיים את השיחה")
                        break

                # Send pending agent response
                if voice.last_response and voice.pending_response is False:
                    await ws.send(json.dumps(voice.last_response, ensure_ascii=False))
                    voice._last_response = None

        except websockets.exceptions.ConnectionClosed:
            print(f"\n🔌 חיבור נסגר: {client_id}")
        except Exception as e:
            logger.error(f"Session error: {e}")
        finally:
            await voice.close()
            self.sessions.pop(ws, None)

    async def start(self, host: str = "0.0.0.0", port: int = 8765):
        """Start WebSocket server."""
        dg_ok = _is_real_key(DEEPGRAM_API_KEY)
        cart_ok = _is_real_key(CARTESIA_API_KEY)
        llm_ok = _is_real_key(GROQ_API_KEY) or _is_real_key(OPENAI_API_KEY)
        claude_ok = _is_real_key(ANTHROPIC_API_KEY)

        print()
        print("=" * 60)
        print("   🎙 PREDATOR AGENT — LIVE VOICE SERVER v2")
        print("=" * 60)
        print(f"   🔌 WebSocket: ws://{host}:{port}")
        print(f"   📋 Deepgram:   {'✅' if dg_ok else '⚠️  fallback'}")
        print(f"   🗣  Cartesia:   {'✅' if cart_ok else '⚠️  fallback'}")
        print(f"   🧠 LLM:        {'✅ Groq' if _is_real_key(GROQ_API_KEY) else '✅ OpenAI' if _is_real_key(OPENAI_API_KEY) else '⚠️  fallback'}")
        print(f"   🔍 Claude:     {'✅' if claude_ok else '⚠️  fallback'}")
        print()
        print("   פתח test_voice.html בדפדפן ← התחל שיחה ← דבר")
        print("=" * 60)
        print()

        if not dg_ok:
            print("⚠️  DEEPGRAM_API_KEY לא תקין — STT לא יעבוד!")
        if not cart_ok:
            print("⚠️  CARTESIA_API_KEY לא תקין — TTS לא יעבוד!")
        if not llm_ok:
            print("ℹ️  LLM בפייל-back — 100+ תשובות בעברית מוכנות מראש. טבעי וחלק.")
        else:
            llm_name = "Groq (llama-3.3-70b)" if _is_real_key(GROQ_API_KEY) else "OpenAI (gpt-4.1-mini)"
            print(f"🧠 LLM פעיל: {llm_name}")

        print()

        async with websockets.serve(self.handle, host, port):
            print("🟢 שרת מוכן — מחכה לחיבור דפדפן...\n")
            await asyncio.Future()


def main():
    server = VoiceServer()
    asyncio.run(server.start())


if __name__ == "__main__":
    main()
