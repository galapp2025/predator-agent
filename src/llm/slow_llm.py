"""
Slow LLM — Claude Sonnet 4
ניתוח פסיכולוגי מעמיק, מיפוי DISC/OCEAN, בחירת טקטיקה
רץ במקביל ל-Fast LLM — כל 2-3 חילופי דברים
"""

import json
import anthropic
import logging
from typing import Optional, Dict

logger = logging.getLogger("predator.slow_llm")

class PsychologicalAnalyzer:
    """שולח תמלול שיחה לקלוד, מקבל ניתוח פסיכולוגי מלא"""

    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.profile: Optional[Dict] = None
        self.analysis_count = 0

    async def analyze(self, transcript: str) -> Dict:
        """ניתוח מלא — DISC, רגש, טקטיקה מומלצת, נקודות הדגשה"""

        prompt = f"""אתה מנתח מודיעין פסיכולוגי. נתח את השיחה הבאה בעברית בין סוכן קמפיין בחירות לבוחר ישראלי.

החזר JSON בלבד — בלי טקסט נוסף, בלי ```json, בלי הסברים:

{{
  "disc_profile": "D" | "I" | "S" | "C",
  "emotional_state": "calm" | "anxious" | "angry" | "excited" | "skeptical" | "hopeful" | "frustrated",
  "persuasion_resistance": 0.0-1.0,
  "recommended_tactic": "loss_aversion" | "social_proof" | "scarcity" | "reciprocity" | "anchoring" | "foot_in_door" | "door_in_face" | "fear_then_relief",
  "recommended_persona": "D" | "I" | "S" | "C",
  "next_move": "deepen_rapport" | "attack_issue" | "commitment_ask" | "handle_objection" | "plant_seed" | "close" | "deescalate",
  "key_issues": ["רשימת 1-3 נושאים שמפעילים את הבוחר"],
  "talking_points": ["3 נקודות ספציפיות שהסוכן צריך להדגיש כרגע"],
  "loss_aversion_trigger": "מה הבוחר הכי מפחד לאבד — משפט אחד בעברית",
  "voter_support_estimated": -5 עד 5
}}

הנחיות ניתוח:
- D (דומיננטי) = מהיר, ממוקד תוצאות, חסר סבלנות. מזהה: "תכל'ס", "בשורה התחתונה", משפטים קצרים.
- I (משפיע) = חברתי, דברן, אופטימי. מזהה: "אחי", "ואללה", סיפורים, התלהבות.
- S (יציב) = מעריך ביטחון, לא אוהב שינויים, מדבר לאט. מזהה: "בוא נראה", "צריך לחשוב", "בשקט", "משפחה".
- C (מחושב) = חשדן, רוצה נתונים, שואל שאלות מדויקות. מזהה: "תוכיח", "איך אתה יודע", "מה המספרים".

שיחה:
{transcript}"""

        response = self.client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}]
        )

        raw = response.content[0].text
        
        # חלץ JSON — קלוד לפעמים עוטף
        for delimiter in ["```json", "```"]:
            if delimiter in raw:
                raw = raw.split(delimiter, 1)[1]
                if "```" in raw:
                    raw = raw.split("```", 1)[0]
                raw = raw.strip()
                break

        self.profile = json.loads(raw)
        self.analysis_count += 1
        logger.info(
            f"🧠 Analysis #{self.analysis_count}: "
            f"DISC={self.profile.get('disc_profile')}, "
            f"Tactic={self.profile.get('recommended_tactic')}, "
            f"Resistance={self.profile.get('persuasion_resistance')}"
        )
        return self.profile

    def build_prompt_update(self) -> str:
        """בונה בלוק עדכון ל-System Prompt של ה-Fast LLM"""
        if not self.profile:
            return ""

        p = self.profile

        persona_map = {"D": "אלון", "I": "מיה", "S": "דוד", "C": "רונית"}

        style_map = {
            "D": "דבר מהר, ישיר, ענייני. תחתית שורה. אל תבזבז מילים.",
            "I": "התלהב, ספר סיפורים, צור התרגשות. 'ביחד', 'ואללה', 'מדהים'.",
            "S": "דבר לאט, הרגע, היה חם ומשפחתי. 'צעד צעד', 'ביטחון', 'הקהילה'.",
            "C": "ציין מספרים ועובדות מדויקות. אל תשתמש בסופרלטיבים. תן לו להרגיש חכם."
        }

        tactic_map = {
            "loss_aversion": "הדגש מה הבוחר יפסיד אם לא יתמוך. 'אם המועמד השני ייבחר — [איום] יחמיר.'",
            "social_proof": "ציין שרבים בשכונה/בעיר כבר תומכים. '87% מהשכנים שלך איתנו.'",
            "scarcity": "הדגש דחיפות — זמן אוזל. 'נשארו X ימים. אם לא נתגייס — נפסיד.'",
            "reciprocity": "תן ערך קטן (מידע, דו\"ח), ואז בקש. 'בדקתי לך — עכשיו תעזור לנו?'",
            "anchoring": "הצג מספר גדול, ואז את ההצעה. 'יודע מה התקציב? 120 מיליון. יודע כמה הגיע? אפס.'",
            "foot_in_door": "התחל בהתחייבות קטנה. 'חשוב לך שהשכונה בטוחה? → תבוא להפגנה קטנה?'",
            "door_in_face": "בקש משהו גדול, ואז את הבקשה האמיתית. 'תתנדב 10 שעות? לא? לפחות תביא חבר להצבעה.'",
            "fear_then_relief": "תאר מצב חמור, הפסקה, ואז פתרון. 'המצב [קשה]... [שתיקה] אבל יש פתרון.'"
        }

        move_map = {
            "deepen_rapport": "חזק את הקשר האישי. שאל שאלה אישית קלה.",
            "attack_issue": "התמקד בנושא שמפעיל את הבוחר. תן דוגמה קונקרטית.",
            "commitment_ask": "הבוחר בשל. בקש התחייבות. 'אפשר לסמן אותך כתומך?'",
            "handle_objection": "הסכם → שאל → הצע אלטרנטיבה. אל תתווכח.",
            "plant_seed": "שתול זרע לעתיד. סיים בחיוב גם בלי Commit.",
            "close": "סכם וסיים. חם, קצר, עם פתח להמשך.",
            "deescalate": "הבוחר כועס/מתוח. הרגע. הסכם. אל תעלה הילוך."
        }

        return f"""
## 🔴 עדכון מודיעין (זמן אמת):
- **DISC**: {p['disc_profile']} → **פרסונה**: {persona_map.get(p['disc_profile'], 'דוד')}
- **מצב רגשי**: {p['emotional_state']}
- **התנגדות**: {p['persuasion_resistance']}/1.0
- **תמיכה משוערת**: {p.get('voter_support_estimated', 0)}/5
- **נושאים חמים**: {', '.join(p.get('key_issues', []))}
- **טריגר אובדן**: "{p.get('loss_aversion_trigger', '')}"

## 🎯 טקטיקה: {p['recommended_tactic']}
{tactic_map.get(p['recommended_tactic'], '')}

## 🗣 סגנון: {style_map.get(p['disc_profile'], '')}

## 📍 מהלך: {p['next_move']}
{move_map.get(p.get('next_move', 'deepen_rapport'), '')}

## 💬 נקודות להדגשה:
{chr(10).join('- ' + pt for pt in p.get('talking_points', []))}
"""
