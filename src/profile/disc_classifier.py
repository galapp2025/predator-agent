"""
DISC Classifier — מקומי, מהיר, בלי API
מזהה D/I/S/C מסמנים לשוניים בעברית
"""

D_MARKERS = [
    "תכל'ס", "בשורה התחתונה", "תכלית", "בתכל'ס",
    "קצר", "אין לי זמן", "קדימה", "יאללה", "נו",
    "מה יצא מזה", "זוז", "אז?", "נו?", "ישר לעניין",
    "דבר אליי במספרים", "תוצאות", "מה בפועל",
    "לא מעניין אותי", "סיפורים", "תחסוך"
]

I_MARKERS = [
    "ואללה", "וואי", "אחי", "מגניב", "אדיר", "איזה כיף",
    "תשמע סיפור", "אהבתי", "יופי", "ברוך השם",
    "הכל טוב", "חגיגה", "מדהים", "איזה יופי",
    "כיף לשמוע", "לגמרי", "אש", "קטלני"
]

S_MARKERS = [
    "בסדר", "בוא נראה", "אני לא ממהר", "בשקט",
    "בנחת", "צעד צעד", "בזהירות", "מפחיד",
    "לא בטוח", "צריך לחשוב", "משפחה", "ילדים",
    "הבית", "הקהילה", "ביטחון", "שכונה", "שכנים",
    "אני מעדיף", "לאט", "לא עכשיו", "אולי אחר כך"
]

C_MARKERS = [
    "מה המספרים", "תראה לי נתונים", "איך אתה יודע",
    "מי אמר", "מה המקור", "תוכיח", "בדיוק",
    "אחוזים", "סטטיסטיקה", "עובדות", "זה לא הגיוני",
    "תסביר", "לא מסתדר לי", "מה ההיגיון",
    "אין הוכחות", "מי בדק", "מאיפה המידע"
]


def classify_disc(text: str) -> tuple:
    """
    מחזיר (primary_disc, scores_dict)
    primary_disc: "D" | "I" | "S" | "C"
    scores: {"D": int, "I": int, "S": int, "C": int}
    """
    text_lower = text.lower()

    scores = {
        "D": sum(1 for m in D_MARKERS if m in text_lower),
        "I": sum(1 for m in I_MARKERS if m in text_lower),
        "S": sum(1 for m in S_MARKERS if m in text_lower),
        "C": sum(1 for m in C_MARKERS if m in text_lower),
    }

    total = sum(scores.values())
    if total == 0:
        return "S", scores  # default: יציב

    primary = max(scores, key=scores.get)
    return primary, scores


def classify_from_multiple(texts: list) -> tuple:
    """מנתח מספר טקסטים (שיחה מצטברת)"""
    combined = " ".join(texts)
    return classify_disc(combined)
