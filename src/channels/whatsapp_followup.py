"""WhatsApp Follow-up — Twilio WhatsApp / WhatsApp Business API"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger("whatsapp-followup")


@dataclass
class FollowupMessage:
    to_phone: str
    body: str
    template_key: str
    state: str
    persona: str
    resistance: str
    candidate_name: str = ""
    poll_location: str = ""
    poll_hours: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def campaign_defaults() -> dict:
    return {
        "candidate_name": _env("CANDIDATE_NAME", "המועמד"),
        "poll_location": _env("POLL_LOCATION", "בית הספר השכונתי"),
        "poll_hours": _env("POLL_HOURS", "07:00-22:00"),
    }


# תבניות לפי state × resistance — persona משנה טון
TEMPLATES: Dict[tuple, Dict[str, str]] = {
    ("closing", "low"): {
        "D": "היי {name}, אלון מהמטה של {candidate}. רשמתי אותך ליום שלישי. קלפי: {poll} ({hours}). נתראה.",
        "I": "היי {name}! מיה מצוות {candidate} 😊 רשמתי — יום שלישי, קלפי {poll}. שעות {hours}. אם משהו משתנה תכתוב לי.",
        "S": "שלום {name}, דוד מהמטה של {candidate}. תודה על השיחה. הקלפי: {poll}, שעות {hours}. אין לחץ — רק תזכורת.",
        "C": "{name}, רונית / {candidate}. סיכום: יום שלישי | קלפי {poll} | {hours}.",
    },
    ("commitment", "low"): {
        "D": "{name} — יום שלישי. קלפי {poll}. {candidate} סופר עליך. בוא.",
        "I": "יאללה {name}! יום שלישי, קלפי {poll} ({hours}). {candidate} מחכה לקול שלך 💪",
        "S": "{name}, תזכורת רכה ליום שלישי — קלפי {poll}. אם צריך עזרה בהגעה, תגיד.",
        "C": "תזכורת: {name} | יום שלישי | קלפי {poll} | {hours} | מועמד: {candidate}.",
    },
    ("commitment", "medium"): {
        "D": "{name}, רשמנו התחייבות. קלפי {poll}. יום שלישי. לא לפספס.",
        "I": "{name}, איזה כיף שאתה איתנו! תזכורת: {poll}, {hours}.",
        "S": "{name}, רק לוודא שנוח לך — קלפי {poll}, שעות {hours}.",
        "C": "{name}: סטטוס=commitment | קלפי={poll} | שעות={hours}.",
    },
    ("seed_planting", "high"): {
        "D": "{name}, רק משפט: ביום שלישי כל קול נספר. קלפי {poll}.",
        "I": "היי {name}, חשבתי עליך אחרי השיחה. אם תשנה דעה — קלפי {poll} מחכה.",
        "S": "{name}, בלי לחץ. אם תרצה — פרטי הקלפי: {poll} ({hours}).",
        "C": "{name}: מידע בלבד — קלפי {poll}. אפשר להתעלם.",
    },
    ("seed_planting", "medium"): {
        "D": "{name} — אם תשקול: {poll}, {hours}. {candidate}.",
        "I": "היי {name}, רק עדכון קטן על {candidate}: הקלפי {poll}.",
        "S": "{name}, שלחתי פרטים לשמירה — {poll}.",
        "C": "מידע: קלפי {poll} | {hours} | {candidate}.",
    },
    ("gotv", "any"): {
        "D": "GOTV: {name} — מחר קלפי {poll} ({hours}). תגיע. {candidate}.",
        "I": "מחר הבחירות! {name}, קלפי {poll}. {candidate} סומך עליך 🙌",
        "S": "{name}, תזכורת למחר — קלפי {poll}, שעות {hours}. שיהיה יום טוב.",
        "C": "מחר | {name} | קלפי {poll} | {hours} | הביא תעודה | {candidate}.",
    },
    ("closing", "medium"): {
        "D": "{name}, תודה. אם הגעת למסקנה — קלפי {poll}.",
        "I": "תודה {name}! אם תרצה, הנה הקלפי: {poll}.",
        "S": "תודה על הזמן, {name}. פרטים: {poll}, {hours}.",
        "C": "סיכום שיחה | קלפי {poll} | {hours}.",
    },
    ("objection_handling", "high"): {
        "D": "{name}, מכבד את העמדה. אם משהו ישתנה — {poll}.",
        "I": "{name}, תודה שהיית כנה. הדלת פתוחה — {candidate}.",
        "S": "{name}, בסדר גמור. לא נלחץ. פרטים לשמירה: {poll}.",
        "C": "סטטוס=objection | אין follow-up לוחץ | קלפי={poll}.",
    },
}


def _normalize_whatsapp_number(phone: str) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if digits.startswith("0"):
        digits = "972" + digits[1:]
    if not digits.startswith("972") and len(digits) <= 10:
        digits = "972" + digits.lstrip("0")
    return f"whatsapp:+{digits}"


def select_template(state: str, persona: str, resistance: str) -> str:
    state = (state or "closing").lower()
    persona = (persona or "S").upper()
    resistance = (resistance or "medium").lower()
    for key in ((state, resistance), (state, "any"), ("closing", "low"), ("gotv", "any")):
        bucket = TEMPLATES.get(key)
        if bucket and persona in bucket:
            return bucket[persona]
    return TEMPLATES[("closing", "low")]["S"]


def build_followup_body(
    *,
    name: str,
    state: str,
    persona: str,
    resistance: str,
    poll_location: Optional[str] = None,
    poll_hours: Optional[str] = None,
    candidate_name: Optional[str] = None,
) -> FollowupMessage:
    defaults = campaign_defaults()
    poll = poll_location or defaults["poll_location"]
    hours = poll_hours or defaults["poll_hours"]
    candidate = candidate_name or defaults["candidate_name"]
    template = select_template(state, persona, resistance)
    body = template.format(
        name=name or "שלום",
        poll=poll,
        hours=hours,
        candidate=candidate,
    )
    return FollowupMessage(
        to_phone="",
        body=body,
        template_key=f"{state}:{persona}:{resistance}",
        state=state,
        persona=persona,
        resistance=resistance,
        candidate_name=candidate,
        poll_location=poll,
        poll_hours=hours,
    )


def should_send_followup(state: str, resistance: str, commitment: str = "") -> bool:
    state = (state or "").lower()
    resistance = (resistance or "").lower()
    if "אל תתקשר" in (commitment or "") or "DNC" in (commitment or "").upper():
        return False
    if state in ("closing", "commitment", "gotv"):
        return True
    if state == "seed_planting" and resistance in ("medium", "high", "very_high"):
        return True
    return False


class WhatsAppFollowup:
    """שליחה אוטומטית אחרי שיחה — לפי state + persona + resistance."""

    def __init__(
        self,
        account_sid: Optional[str] = None,
        auth_token: Optional[str] = None,
        from_whatsapp: Optional[str] = None,
    ):
        self.account_sid = account_sid or _env("TWILIO_ACCOUNT_SID")
        self.auth_token = auth_token or _env("TWILIO_AUTH_TOKEN")
        raw_from = from_whatsapp or _env("TWILIO_WHATSAPP_FROM", "+14155238886")
        if raw_from and not raw_from.startswith("whatsapp:"):
            if raw_from.startswith("+"):
                raw_from = f"whatsapp:{raw_from}"
            else:
                raw_from = _normalize_whatsapp_number(raw_from)
        self.from_whatsapp = raw_from
        self._client = None
        self.sent_log: List[dict] = []

    @property
    def configured(self) -> bool:
        return bool(self.account_sid and self.auth_token and self.from_whatsapp)

    def _get_client(self):
        if self._client is None:
            from twilio.rest import Client

            self._client = Client(self.account_sid, self.auth_token)
        return self._client

    def preview(
        self,
        *,
        name: str,
        state: str,
        persona: str,
        resistance: str,
        **kwargs,
    ) -> dict:
        msg = build_followup_body(
            name=name, state=state, persona=persona, resistance=resistance, **kwargs
        )
        return asdict(msg)

    def send(
        self,
        to_phone: str,
        *,
        name: str,
        state: str,
        persona: str,
        resistance: str,
        poll_location: Optional[str] = None,
        poll_hours: Optional[str] = None,
        candidate_name: Optional[str] = None,
        dry_run: bool = False,
    ) -> dict:
        msg = build_followup_body(
            name=name,
            state=state,
            persona=persona,
            resistance=resistance,
            poll_location=poll_location,
            poll_hours=poll_hours,
            candidate_name=candidate_name,
        )
        msg.to_phone = _normalize_whatsapp_number(to_phone)
        payload = {
            "to": msg.to_phone,
            "from": self.from_whatsapp,
            "body": msg.body,
            "template_key": msg.template_key,
            "state": state,
            "persona": persona,
            "resistance": resistance,
            "candidate_name": msg.candidate_name,
            "poll_location": msg.poll_location,
            "poll_hours": msg.poll_hours,
        }

        if dry_run or not self.configured:
            logger.info("[whatsapp] dry_run → %s (%s)", msg.to_phone, msg.template_key)
            result = {**payload, "status": "dry_run"}
            self.sent_log.append(result)
            return result

        try:
            client = self._get_client()
            result_msg = client.messages.create(
                from_=self.from_whatsapp,
                to=msg.to_phone,
                body=msg.body,
            )
            logger.info("[whatsapp] sent sid=%s to=%s", result_msg.sid, msg.to_phone)
            result = {**payload, "status": "sent", "sid": result_msg.sid}
            self.sent_log.append(result)
            return result
        except Exception as e:
            logger.error("[whatsapp] send failed: %s", e)
            result = {**payload, "status": "error", "error": str(e)}
            self.sent_log.append(result)
            return result

    def maybe_send_after_call(self, call_summary: dict, dry_run: bool = False) -> Optional[dict]:
        state = (call_summary.get("final_state") or call_summary.get("state") or "").lower()
        resistance = call_summary.get("resistance", "medium")
        commitment = call_summary.get("commitment", "")
        if not should_send_followup(state, resistance, commitment):
            logger.info("[whatsapp] skip follow-up for state=%s", state)
            return None
        phone = call_summary.get("phone") or call_summary.get("to_phone")
        if not phone:
            return None
        return self.send(
            phone,
            name=call_summary.get("voter") or call_summary.get("name") or call_summary.get("full_name") or "",
            state=state,
            persona=call_summary.get("persona", "S"),
            resistance=resistance,
            poll_location=call_summary.get("poll_location"),
            poll_hours=call_summary.get("poll_hours"),
            candidate_name=call_summary.get("candidate_name"),
            dry_run=dry_run,
        )

    def send_poll_reminder(
        self,
        to_phone: str,
        name: str,
        persona: str = "S",
        dry_run: bool = False,
    ) -> dict:
        """תזכורת יום לפני — GOTV."""
        return self.send(
            to_phone,
            name=name,
            state="gotv",
            persona=persona,
            resistance="any",
            dry_run=dry_run,
        )
