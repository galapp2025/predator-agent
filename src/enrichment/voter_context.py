"""Voter Context Enrichment — Pre-Call Context"""
from dataclasses import dataclass
from typing import Optional, List, Dict

FEMALE_FIRST_NAMES = {"רחל", "לאה", "שרה", "רבקה", "אסתר", "מרים", "דבורה", "חנה", "רות", "יהודית", "תמר", "יעל", "אילנה", "רונית", "דליה", "אורלי", "סיגל", "ענת", "מירב", "ליאת", "קרן", "טלי", "מיכל", "דנה", "שירלי", "הילה", "מורן", "לימור", "גלית", "ורד", "איריס", "נועה", "עדי", "מאיה", "שירה", "איילת", "נטלי", "אולגה", "טטיאנה", "אירינה", "ילנה", "סבטלנה", "רינה", "אביבה", "ציפי", "אתי", "ריקי", "יפה", "נורית", "עדן", "שני", "רוני", "לי", "נועם", "מעיין", "הדר", "שחר", "אגם", "ירדן", "אלמוג", "כרמל", "שיר", "זהבה", "גילה", "בתיה", "פנינה", "שושנה", "מלכה", "אסנת", "אורנה", "רחלי", "אפרת", "שלומית"}

MALE_FIRST_NAMES = {"אברהם", "יצחק", "יעקב", "משה", "אהרון", "דוד", "שלמה", "יוסף", "דניאל", "מיכאל", "רפאל", "גבריאל", "שמואל", "אליהו", "ישראל", "מאיר", "חיים", "פנחס", "יהודה", "רון", "אלון", "עומר", "ניר", "אורי", "אבי", "יוסי", "רן", "גיל", "אייל", "עופר", "דורון", "בועז", "גדי", "מוטי", "שי", "קובי", "רמי", "עמיר", "איתן", "יגאל", "בוריס", "איגור", "ולדימיר", "אלכס", "סרגיי", "מנחם", "בנימין", "צבי", "דב", "נחום", "מרדכי", "שמעון", "תום", "עידו", "יואב", "איתי", "שחר", "ליאור", "אוהד", "אור", "אביב", "יניב", "אריאל", "אדיר", "בן"}

OLDER_GENERATION_NAMES = {"רחל", "שרה", "אברהם", "משה", "אהרון", "מרים", "דבורה", "חנה", "מנחם", "בנימין", "צבי", "שלמה", "מרדכי", "שמעון", "אביבה", "רינה", "יפה", "נורית", "זהבה", "גילה", "בתיה", "פנינה", "שושנה", "מלכה", "אסתר", "יצחק", "יעקב"}

MIDDLE_GENERATION_NAMES = {"אילנה", "רונית", "דליה", "ישראל", "מאיר", "חיים", "אתי", "ריקי", "ציפי", "דב", "פנחס", "יהודה", "שלומית", "אורנה", "אסנת", "רחלי"}

YOUNGER_NAMES = {"רון", "אלון", "עומר", "ניר", "אורי", "שירלי", "הילה", "קרן", "טלי", "ליאת", "מיכל", "דנה", "ענת", "סיגל", "תום", "עידו", "יואב", "איתי", "שחר", "ליאור", "אוהד", "אור", "אביב", "יניב", "אריאל", "אדיר", "עדן", "שני", "לי", "נועם", "מעיין", "הדר", "אלמוג", "כרמל", "ירדן", "אגם"}

ETHIOPIAN_SURNAMES = {"אבבה", "אבגאז", "אבדייב", "אבורוס", "אדנה", "איינאו", "אלמו", "אספה", "בוגלה", "ביינא", "גטהון", "דסה", "טסמה", "מנגיסטו", "נגוסה", "פרדה", "צגה", "קבטה", "שבטו", "טקה", "וורקו", "יימר", "זאודה", "גברה", "אדמו", "ברהון", "טקלה", "מסרט", "קסאי", "אברה"}

RUSSIAN_SURNAMES = {"איבנוב", "פטרוב", "סמירנוב", "קוזנצוב", "פופוב", "סוקולוב", "מיכאילוב", "נוביקוב", "מורוזוב", "וולקוב", "פדורוב", "אלכסייב", "אנדרייב", "רומנוב", "בוריסוב", "בלוב", "גולוב", "דמיטרייב", "זייצב", "קיסלב", "ברקוב", "לזרב", "מקסימוב", "סטפנוב", "טרב"}


@dataclass
class VoterContext:
    first_name: str
    last_name: str
    gender: str
    age_group: str
    household_members: int
    residency_tenure: str
    ethnic_hint: str
    support_score: float
    geo_anomaly: bool
    city: str
    street: str
    house_number: str
    registered_branch: str = ""
    campaign_type: str = "primaries"


class VoterContextBuilder:
    @staticmethod
    def detect_gender(first_name: str) -> str:
        name = first_name.strip()
        if name in FEMALE_FIRST_NAMES:
            return "female"
        if name in MALE_FIRST_NAMES:
            return "male"
        if name.endswith(("ה", "ת", "ית")):
            return "female"
        if name.endswith(("ם", "ן", "אל")):
            return "male"
        return "unknown"

    @staticmethod
    def detect_age_group(first_name: str) -> str:
        name = first_name.strip()
        if name in OLDER_GENERATION_NAMES:
            return "65+"
        if name in MIDDLE_GENERATION_NAMES:
            return "45-65"
        if name in YOUNGER_NAMES:
            return "25-45"
        return "unknown"

    @staticmethod
    def detect_ethnic_hint(last_name: str, first_name: str = "") -> str:
        name = last_name.strip()
        if name in ETHIOPIAN_SURNAMES:
            return "ethiopian"
        if name in RUSSIAN_SURNAMES:
            return "russian"
        return "general"

    @staticmethod
    def detect_household(first_name, last_name, street, house_number, all_voters=None) -> int:
        if not all_voters:
            return 1
        address = f"{street} {house_number}".strip()
        count = 1
        for v in all_voters:
            if (v.get("last_name", "").strip() == last_name and f"{v.get('street', '')} {v.get('house_number', '')}".strip() == address and v.get("first_name", "").strip() != first_name):
                count += 1
        return count

    @staticmethod
    def check_geo_anomaly(registered_branch: str, actual_city: str) -> bool:
        if not registered_branch or not actual_city:
            return False
        return registered_branch.strip() != actual_city.strip()

    def build(self, first_name, last_name, city, street="", house_number="", registered_branch="", support_score=0.5, campaign_type="primaries", all_voters=None):
        gender = self.detect_gender(first_name)
        age_group = self.detect_age_group(first_name)
        ethnic_hint = self.detect_ethnic_hint(last_name, first_name)
        geo_anomaly = self.check_geo_anomaly(registered_branch, city)
        household = self.detect_household(first_name, last_name, street, house_number, all_voters)
        return VoterContext(first_name=first_name, last_name=last_name, gender=gender, age_group=age_group, household_members=household, residency_tenure="unknown", ethnic_hint=ethnic_hint, support_score=support_score, geo_anomaly=geo_anomaly, city=city, street=street, house_number=house_number, registered_branch=registered_branch, campaign_type=campaign_type)

    def to_prompt_context(self, ctx: VoterContext) -> str:
        lines = ["[VOTER_CONTEXT — מידע מודיעיני מקדים]"]
        lines.append(f"שם: {ctx.first_name} {ctx.last_name}")
        gender_he = {"male": "זכר", "female": "נקבה", "unknown": "לא ידוע"}
        lines.append(f"מין: {gender_he[ctx.gender]}")
        lines.append(f"קבוצת גיל משוערת: {ctx.age_group}")
        lines.append(f"נפשות בתא משפחתי: {ctx.household_members}")
        lines.append(f"עיר מגורים: {ctx.city}")
        if ctx.ethnic_hint != "general":
            ethnic_he = {"ethiopian": "יוצאי אתיופיה — חם, משפחתי", "russian": "יוצאי בריה״מ — ישיר, מעשי"}
            lines.append(f"רמז עדתי: {ethnic_he.get(ctx.ethnic_hint)}")
        lines.append(f"ציון תמיכה צפוי: {ctx.support_score:.2f}")
        if ctx.support_score > 0.7:
            lines.append("  → תומך בטוח. אסטרטגיה: GOTV — המרצה. בלי שכנוע מיותר.")
        elif ctx.support_score < 0.3:
            lines.append("  → לא תומך. אסטרטגיה: SCREENING. בלי שכנוע אגרסיבי.")
        else:
            lines.append("  → קול צף. אסטרטגיה: FULL_PERSUASION — שכנוע מלא.")
        if ctx.geo_anomaly:
            lines.append("⚠️ חריגה גאוגרפית: גר בעיר אחרת מהסניף")
            if ctx.campaign_type == "primaries":
                lines.append("   → בפריימריז: נכס. קשר חזק לסניף.")
            elif ctx.campaign_type == "municipal":
                lines.append("   → במוניציפלי: כנראה לא רלוונטי.")
        if ctx.street:
            lines.append(f"רחוב: {ctx.street} {ctx.house_number}")
        return "\n".join(lines)
