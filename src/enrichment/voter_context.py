"""Voter Context Enrichment — Pre-Call Context"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


FEMALE_FIRST_NAMES = {
    "רחל", "לאה", "שרה", "רבקה", "אסתר", "מרים", "דבורה", "חנה", "רות", "יהודית",
    "תמר", "יעל", "אילנה", "רונית", "דליה", "אורלי", "סיגל", "ענת", "מירב", "ליאת",
    "קרן", "טלי", "מיכל", "דנה", "שירלי", "הילה", "מורן", "לימור", "גלית", "ורד",
    "איריס", "נועה", "עדי", "מאיה", "שירה", "איילת", "נטלי", "אולגה", "טטיאנה",
    "אירינה", "ילנה", "סבטלנה", "רינה", "אביבה", "ציפי", "אתי", "ריקי", "יפה",
    "נורית", "עדן", "שני", "רוני", "לי", "נועם", "מעיין", "הדר", "שחר", "אגם",
    "ירדן", "אלמוג", "כרמל", "שיר", "זהבה", "גילה", "בתיה", "פנינה", "שושנה",
    "מלכה", "אסנת", "אורנה", "רחלי", "אפרת", "שלומית", "רותי",
}

MALE_FIRST_NAMES = {
    "אברהם", "יצחק", "יעקב", "משה", "אהרון", "דוד", "שלמה", "יוסף", "דניאל",
    "מיכאל", "רפאל", "גבריאל", "שמואל", "אליהו", "ישראל", "מאיר", "חיים",
    "פנחס", "יהודה", "רון", "אלון", "עומר", "ניר", "אורי", "אבי", "יוסי",
    "רן", "גיל", "אייל", "עופר", "דורון", "בועז", "גדי", "מוטי", "שי", "קובי",
    "רמי", "עמיר", "איתן", "יגאל", "בוריס", "איגור", "ולדימיר", "אלכס",
    "סרגיי", "מנחם", "בנימין", "צבי", "דב", "נחום", "מרדכי", "שמעון", "תום",
    "עידו", "יואב", "איתי", "שחר", "ליאור", "אוהד", "אור", "אביב", "יניב",
    "אריאל", "אדיר", "בן",
}

OLDER_GENERATION_NAMES = {
    "רחל", "שרה", "אברהם", "משה", "אהרון", "מרים", "דבורה", "חנה", "מנחם",
    "בנימין", "צבי", "שלמה", "מרדכי", "שמעון", "אביבה", "רינה", "יפה", "נורית",
    "זהבה", "גילה", "בתיה", "פנינה", "שושנה", "מלכה", "אסתר", "יצחק", "יעקב",
}

MIDDLE_GENERATION_NAMES = {
    "אילנה", "רונית", "דליה", "ישראל", "מאיר", "חיים", "אתי", "ריקי", "ציפי",
    "דב", "פנחס", "יהודה", "שלומית", "אורנה", "אסנת", "רחלי",
}

YOUNGER_NAMES = {
    "רון", "אלון", "עומר", "ניר", "אורי", "שירלי", "הילה", "קרן", "טלי", "ליאת",
    "מיכל", "דנה", "ענת", "סיגל", "תום", "עידו", "יואב", "איתי", "שחר", "ליאור",
    "אוהד", "אור", "אביב", "יניב", "אריאל", "אדיר", "עדן", "שני", "לי", "נועם",
    "מעיין", "הדר", "אלמוג", "כרמל", "ירדן", "אגם",
}

ETHIOPIAN_SURNAMES = {
    "אבבה", "אבגאז", "אבדייב", "אבורוס", "אדנה", "איינאו", "אלמו", "אספה",
    "בוגלה", "ביינא", "גטהון", "דסה", "טסמה", "מנגיסטו", "נגוסה", "פרדה",
    "צגה", "קבטה", "שבטו", "טקה", "וורקו", "יימר", "זאודה", "גברה", "אדמו",
    "ברהון", "טקלה", "מסרט", "קסאי", "אברה",
}

RUSSIAN_SURNAMES = {
    "איבנוב", "פטרוב", "סמירנוב", "קוזנצוב", "פופוב", "סוקולוב", "מיכאילוב",
    "נוביקוב", "מורוזוב", "וולקוב", "פדורוב", "אלכסייב", "אנדרייב", "רומנוב",
    "בוריסוב", "בלוב", "גולוב", "דמיטרייב", "זייצב", "קיסלב", "ברקוב",
    "לזרב", "מקסימוב", "סטפנוב", "טרב",
}


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
    def detect_household(
        first_name,
        last_name,
        street,
        house_number,
        all_voters=None,
    ) -> int:
        if not all_voters:
            return 1
        address = f"{street} {house_number}".strip()
        count = 1
        for v in all_voters:
            same_family = v.get("last_name", "").strip() == last_name
            same_addr = (
                f"{v.get('street', '')} {v.get('house_number', '')}".strip()
                == address
            )
            different_person = v.get("first_name", "").strip() != first_name
            if same_family and same_addr and different_person:
                count += 1
        return count

    @staticmethod
    def check_geo_anomaly(registered_branch: str, actual_city: str) -> bool:
        if not registered_branch or not actual_city:
            return False
        return registered_branch.strip() != actual_city.strip()

    def build(
        self,
        first_name: str = "",
        last_name: str = "",
        city: str = "",
        street: str = "",
        house_number: str = "",
        registered_branch: str = "",
        support_score: float = 0.5,
        campaign_type: str = "primaries",
        all_voters=None,
        **kwargs,
    ) -> VoterContext:
        gender = kwargs.get("gender") or ""
        if isinstance(first_name, dict):
            v = first_name
            first_name = v.get("first_name", "")
            last_name = v.get("last_name", "")
            city = v.get("city", "")
            street = v.get("street", "")
            house_number = v.get("house_number", "")
            registered_branch = v.get("registered_branch", "")
            support_score = float(v.get("support_score", 0.5) or 0.5)
            campaign_type = v.get("campaign_type", "primaries")
            all_voters = v.get("all_voters", all_voters)
            gender = v.get("gender") or gender

        gender_norm = str(gender or "").strip().lower()
        if gender_norm in ("female", "f", "נקבה", "אישה", "אשה"):
            gender = "female"
        elif gender_norm in ("male", "m", "זכר", "גבר"):
            gender = "male"
        else:
            gender = self.detect_gender(first_name)
        age_group = self.detect_age_group(first_name)
        ethnic_hint = self.detect_ethnic_hint(last_name, first_name)
        geo_anomaly = self.check_geo_anomaly(registered_branch, city)
        household = self.detect_household(
            first_name, last_name, street, house_number, all_voters
        )
        return VoterContext(
            first_name=first_name,
            last_name=last_name,
            gender=gender,
            age_group=age_group,
            household_members=household,
            residency_tenure="unknown",
            ethnic_hint=ethnic_hint,
            support_score=float(support_score or 0.5),
            geo_anomaly=geo_anomaly,
            city=city,
            street=street,
            house_number=house_number,
            registered_branch=registered_branch,
            campaign_type=campaign_type,
        )

    def to_prompt_context(self, ctx: VoterContext) -> str:
        gender_he = {"male": "זכר", "female": "נקבה", "unknown": "לא ידוע"}
        if ctx.gender == "female":
            address = "פנה רק בנקבה: את / שלך / לך / אותך. אסור אתה/לך הזכרי."
        elif ctx.gender == "male":
            address = "פנה רק בזכר: אתה / שלך / לך / אותך. אסור את/לך הנקבי."
        else:
            address = "מגדר לא ידוע — הימנע מאתה/את; השתמש בשם או בניסוח ניטרלי."
        lines = [
            f"שם הבוחר: {ctx.first_name}".strip(),
            f"משפחה: {ctx.last_name}" if ctx.last_name else "",
            f"מין: {gender_he.get(ctx.gender, 'לא ידוע')}",
            address,
            f"עיר: {ctx.city}" if ctx.city else "",
        ]
        return "\n".join(x for x in lines if x)
