"""8 טקטיקות קלאסיות + 5 טקטיקות פסיכולוגיה שחורה"""
from typing import Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class Tactic:
    name: str
    category: str
    trigger: str
    mechanism: str
    hebrew_templates: List[str]
    rule: str
    forbidden_in_states: List[str] = field(default_factory=list)


CLASSICAL_TACTICS: Dict[str, Tactic] = {
    "loss_aversion": Tactic("אבדן / הפסד", "classical", "closing / objection_handling", "המוח חש פי 2 יותר מהפסד מאשר מרווח שווה ערך.", [
        "תשמע, אם לא תגיע ביום שלישי — זה עלול ליפול ב-20 קולות. ראיתי את זה קורה.",
        "אם אתה לא מצביע, יש סיכוי טוב שהמועמד השני ינצח. ואז [תוצאה שלילית].",
        "בשנה שעברה היו 30 קולות הפרש בפריימריז. 30. אתה מבין כמה זה קרוב?",
    ], "תמיד פי 2 חזק יותר מסקרי רווח. לעולם לא 'תרוויח' — תמיד 'תאבד'."),

    "social_proof": Tactic("הוכחה חברתית", "classical", "exploration / persuasion", "בני אדם מסתכלים על מה שאחרים עושים.", [
        "השכנים שלך ברחוב הרצל כבר דיברו איתי. 8 מתוכם אמרו שזה מה שצריך.",
        "ראיתי ש[שם מועמד] מקבל תמיכה מאנשים בדיוק כמוך.",
        "ביום שישי האחרון היו 47 שיחות כמו שלנו. 38 אמרו שיגיעו.",
    ], "תמיד מספרים ספציפיים. 'הרבה אנשים' לא עובד. '47 אנשים' עובד."),

    "scarcity_urgency": Tactic("מחסור + דחיפות", "classical", "closing", "משאב נדיר = בעל ערך גבוה יותר.", [
        "תקשיב, יש לי עוד 3 שיחות היום ברחוב שלך. אחרי זה הסגירה.",
        "הקלפי שלך נסגרת ב-22:00. אחרי זה אין הזדמנות שנייה.",
        "הסניף שלנו סוגר את הרישום בעוד שבוע.",
    ], "תמיד זמן אמיתי או כמות אמיתית. אסור להמציא."),

    "reciprocity": Tactic("הדדיות", "classical", "before_commitment_ask", "מי שקיבל משהו מרגיש חייב להחזיר.", [
        "תראה, לא ביקשת — אבל בדקתי בשבילך איפה אתה רשום. הקלפי שלך בית ספר [שם]. 3 דקות ממך. אז תגיע?",
        "אני אגיד לך משהו: שלחתי לך הודעה עם כל הפרטים. בלי שביקשת. תן לי לשאול אותך משהו.",
    ], "תן ערך אמיתי לפני שאתה שואל. אסור 'תן לי X ואז אתן לך Y'."),

    "anchoring": Tactic("עוגן", "classical", "opening / persuasion", "המספר הראשון הופך לנקודת הייחוס.", [
        "תדמיין — 14,000 שקל. זה מה שהמועמד שלנו השיג לאנשים בדיוק כמוך. עכשיו תגיד לי — חמש דקות שלך שווה את זה?",
        "בסביבות 800 שיחות כאלה יש בסניף שלנו. אנחנו בערך באמצע. כל שיחה כמו שלנו מקרבת.",
    ], "תמיד מספר גדול לפני מספר קטן."),

    "foot_in_door": Tactic("דלת קטנה", "classical", "closing", "מי שהסכים לקטן נוטה להסכים לגדול יותר.", [
        "אז בוא נתחיל ממשהו פשוט. תאשר לי שאתה רשום ב[עיר]? יופי. עכשיו — תאשר לי שאתה רוצה להצביע? יופי. עכשיו — תגיע ביום שלישי?",
    ], "קטן לפני גדול. תמיד."),

    "door_in_face": Tactic("דלת גדולה", "classical", "closing_last_attempt", "מי שדחה גדול נוטה להסכים לקטן אחריו.", [
        "אוקיי, אני רואה שאתה מתלבט. אז בוא נעשה משהו הרבה יותר קטן: פשוט תגיע לחמש דקות, תשים פתק, ותלך.",
    ], "תמיד קטן אחרי גדול. ההפרש משמעותי."),

    "fear_then_relief": Tactic("פחד-ואז-הקלה", "classical", "closing_last_attempt", "פחד משתק. הקלה פותחת.", [
        "אני אגיד לך משהו בכנות. בפריימריז האלה — זה הולך להיות צמוד. 20 קולות יכולים להכריע. אבל יש לך דרך פשוטה. להגיע, לשים פתק, וללכת. 5 דקות.",
    ], "פחד ראשון. תן לו לשקוע. ואז — הקלה. אסור לערבב."),
}

BLACK_PSYCH_TACTICS: Dict[str, Tactic] = {
    "micro_yes_ladder": Tactic("סולם מיקרו-כן", "black_psych", "call_start", "כל 'כן' משחרר דופמין. 3 'כן' = מחסום נשבר.", [
        "אתה [שם]? יופי.",
        "אתה רשום ב[עיר], נכון? אוקיי.",
        "אתה בטח שומע את כל הדיבורים על [הבחירות/פריימריז]…",
    ], "לעולם לא לדלג על שלב 1. לעולם לא לשאול שאלה אמיתית לפני שלב 3."),

    "limited_choice": Tactic("אשליית בחירה מוגבלת", "black_psych", "closing", "המוח בוחר איך, לא שואל אם.", [
        "אתה בא ביום שלישי בבוקר, או שיותר נוח לך בערב?",
        "להביא אותך לקלפי ברכב, או שאתה מסתדר?",
        "להזכיר לך בבוקר של הבחירות, או שאתה זוכר לבד?",
    ], "לעולם לא 'אתה רוצה?'. תמיד 'או X או Y?'. שתי האפשרויות = כן."),

    "emotional_time_travel": Tactic("מסע בזמן רגשי", "black_psych", "after_profiling / persuasion", "המוח לא מבדיל בין דמיון למציאות.", [
        "תדמיין שעוד שנתיים הבת שלך מסיימת תיכון עם בגרות מלאה ומלגת לימודים. כי מישהו השקיע בחינוך. מישהו שבחרת.",
        "דמיין שאתה יוצא מהבית בבוקר, אין פקקים בשכונה, חניה מסודרת, פארק ליד.",
        "תאר לך שאתה חוזר בערב, מצלמות בכל פינה, תאורה. הילדה שלך הולכת לבד. ואתה רגוע.",
    ], "תמיד זמן הווה לגבי העתיד. גרום לו להרגיש, לא לחשוב."),

    "debt_creation": Tactic("יצירת חוב", "black_psych", "before_commitment_ask", "מי שקיבל ערך בחינם מרגיש חייב — תת-הכרתי.", [
        "תראה, בדקתי בשבילך איפה אתה רשום בפנקס. הנה. קלפי בית ספר [שם], 3 דקות ממך ברגל. [שתיקה] אז תגיע?",
        "אני אגיד לך משהו: בדקתי בשבילך את כל הפרטים מול הוועדה. לקח לי 5 דקות. [שתיקה] תן לי לשאול אותך משהו.",
    ], "תן ערך אמיתי. שתוק. תן לחוב לשקוע. אחר כך שאל."),

    "three_cards": Tactic("3 הקלפים", "black_psych", "closing_last_attempt", "3 ניסיונות מתואמים. אחרי 3 = יציאה מכובדת.", [
        "תראה, הרגע בדקתי בשבילך את כל הפרטים. בלי שביקשת. המינימום… זה לבוא ליום הבחירות, לא? זה חמש דקות.",
        "אם אתה לא בא והמועמד שלנו מפסיד ב-20 קולות… תגיד, איך תרגיש?",
        "אוקיי, אני רואה שאתה מתלבט. אז בוא נעשה משהו קטן: פשוט תגיע לחמש דקות, תשים פתק, ותלך.",
    ], "קלף 1 = הדדיות. קלף 2 = אבדן. קלף 3 = דלת בפנים. אחרי 3 = יציאה מכובדת."),
}

TACTIC_BY_STATE_AND_RESISTANCE = {
    ("opening", "any"): "micro_yes_ladder",
    ("exploration", "low"): "emotional_time_travel",
    ("exploration", "medium"): "social_proof",
    ("exploration", "high"): None,
    ("profiling", "any"): "debt_creation",
    ("persuasion", "low"): "emotional_time_travel",
    ("persuasion", "medium"): "loss_aversion",
    ("persuasion", "high"): "social_proof",
    ("persuasion", "very_high"): "anchoring",
    ("closing", "low"): "limited_choice",
    ("closing", "medium"): "limited_choice",
    ("closing", "high"): "three_cards",
    ("closing", "very_high"): "fear_then_relief",
    ("objection_handling", "any"): "reciprocity",
    ("commitment", "low"): "foot_in_door",
    ("commitment", "high"): "door_in_face",
    ("gotv", "any"): "loss_aversion",
}


def get_tactic_for_moment(state, resistance="any", support_score=0.5):
    if support_score > 0.7 and state in ("closing", "commitment", "persuasion", "gotv"):
        return CLASSICAL_TACTICS["loss_aversion"]
    key = (state, resistance)
    tactic_name = TACTIC_BY_STATE_AND_RESISTANCE.get(key)
    if not tactic_name:
        key_any = (state, "any")
        tactic_name = TACTIC_BY_STATE_AND_RESISTANCE.get(key_any)
    if not tactic_name:
        return None
    if tactic_name in CLASSICAL_TACTICS:
        return CLASSICAL_TACTICS[tactic_name]
    if tactic_name in BLACK_PSYCH_TACTICS:
        return BLACK_PSYCH_TACTICS[tactic_name]
    return None


def get_all_tactics():
    return {**CLASSICAL_TACTICS, **BLACK_PSYCH_TACTICS}
