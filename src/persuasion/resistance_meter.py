"""
Resistance Meter — מודד התנגדות בזמן אמת
0.0 = משוכנע לחלוטין | 1.0 = מתנגד בתוקף
"""

RESISTANCE_WORDS = [
    "לא", "אבל", "אולי", "לא יודע", "לא בטוח",
    "צריך לחשוב", "תן לי לבדוק", "אני לא סגור",
    "מפחיד", "בעייתי", "לא נראה לי", "ספק",
    "מסוכן", "לא מתאים", "בהמשך", "לא עכשיו",
    "אני מעדיף שלא", "תשאיר פרטים", "אחזור אליך",
    "שלח לי במייל", "לא החלטתי", "זהירות"
]

COMMITMENT_WORDS = [
    "כן", "בטח", "ברור", "סבבה", "יאללה",
    "מעוניין", "אני בא", "מתאים", "בוא נקבע",
    "אחלה", "בכיף", "נשמע טוב", "יוצא מן הכלל",
    "תרשום אותי", "אני תומך", "מגניב"
]


def measure_resistance(text: str) -> float:
    """0.0 = משוכנע, 1.0 = מתנגד לחלוטין"""
    text_lower = text.lower()

    r_count = sum(1 for w in RESISTANCE_WORDS if w in text_lower)
    c_count = sum(1 for w in COMMITMENT_WORDS if w in text_lower)

    total = r_count + c_count
    if total == 0:
        return 0.5  # ניטרלי

    return r_count / total


def is_escalating(previous_resistance: float, current_resistance: float) -> bool:
    """האם ההתנגדות בעלייה? (קפיצה של 30%+)"""
    return current_resistance - previous_resistance > 0.3


def is_deescalating(previous_resistance: float, current_resistance: float) -> bool:
    """האם ההתנגדות בירידה?"""
    return previous_resistance - current_resistance > 0.2
