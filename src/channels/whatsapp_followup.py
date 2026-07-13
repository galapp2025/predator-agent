"""WhatsApp Multi-Channel Follow-Up — מעקב וואטסאפ אחרי שיחה"""
import logging
import os
from datetime import datetime
from typing import Dict, Optional

from twilio.rest import Client as TwilioClient
from twilio.base.exceptions import TwilioRestException

logger = logging.getLogger("whatsapp-followup")

# ── Per-State Message Templates (Hebrew) ───────────────
# Each template adapts to the call outcome and the voter's state

WHATSAPP_TEMPLATES = {
    "closing": {
        "header": "תודה שדיברנו! 🗳️",
        "templates": [
            "היי {first_name}, תודה על השיחה! רק תזכורת — הקלפי ב{location}, מחכים לך. יום טוב!",
            "{first_name}, כיף שדיברנו. נתראה בקלפי ב{location}. שבוע טוב!",
            "היי {first_name}, שמח שהצלחנו לדבר. הקלפי ב{location} — אל תשכח!",
        ],
        "delay_minutes": 0,  # Send immediately after call
    },
    "commitment": {
        "header": "כיף שאתנו! 🤝",
        "templates": [
            "{first_name}, תודה על התמיכה! הקלפי ב{location}, שעות: {hours}. רוצה שגם נשלח טרמפ?",
            "היי {first_name}! אדיר שבאת. רק מוודא — {day_of_week}, נכון? הקלפי ב{location}. נשלח תזכורת.",
            "{first_name}, איזה כיף! רשום — {location}, {day_of_week} ב{hours}. מחכים לך!",
        ],
        "delay_minutes": 5,
    },
    "gotv": {
        "header": "מחר בקלפי! 🚗",
        "templates": [
            "{first_name}, תזכורת אחרונה — מחר הקלפי ב{location}, {hours}. צריך טרמפ? יש לנו מתנדבים!",
            "היי {first_name}! מחר יום הבוחר. קלפי: {location}, שעות: {hours}. בוא להכריע!",
            "{first_name}, מחר! 📍{location} ⏰{hours}. אל תפספס — הקול שלך קובע.",
        ],
        "delay_minutes": 0,
    },
    "objection_handling": {
        "header": "חשבתי על מה שאמרת...",
        "templates": [
            "היי {first_name}, חשבתי על השיחה שלנו. יש משהו שאולי פספסת — {candidate_name} באמת עשה {achievement}. שווה לבדוק.",
            "{first_name}, שמע, הבנתי את ההתלבטות. שלחתי לך קישור — אולי זה ישנה לך את הזווית.",
            "היי {first_name}. אני יודע שהיית סקפטי, אבל תבדוק את זה: {link}. אין לחץ.",
        ],
        "delay_minutes": 30,  # Give them time to cool off
    },
    "seed_planting": {
        "header": "רק שתדע... 🌱",
        "templates": [
            "היי {first_name}, רק שתדע — {candidate_name} עשה היום {achievement}. חשבתי שתרצה לדעת.",
            "{first_name}, מחשבה קטנה: {fact}. אין לחץ, רק שיהיה לך מידע.",
            "היי {first_name}. זוכר מה דיברנו? הנה כתבה שקשורה: {link}. שבת שלום!",
        ],
        "delay_minutes": 60,  # Let the seed germinate
    },
    "exploration": {
        "header": "דרך אגב...",
        "templates": [
            "היי {first_name}, חשבתי על מה שאמרת על {topic}. תראה את זה: {link}.",
            "{first_name}, דיברנו על {topic} — הנה משהו שקשור. אשמח לשמוע מה דעתך.",
        ],
        "delay_minutes": 20,
    },
    "profiling": {
        "header": "בדיוק בשבילך",
        "templates": [
            "היי {first_name}, לפי השיחה שלנו חשבתי שזה ידבר אליך: {link}.",
            "{first_name}, מצאתי משהו שמתאים בדיוק למה שאכפת לך ממנו. תבדוק.",
        ],
        "delay_minutes": 15,
    },
    "default": {
        "header": "תודה על הזמן!",
        "templates": [
            "היי {first_name}, תודה על השיחה. אם תרצה להמשיך — אני פה. יום טוב!",
            "{first_name}, תודה! אם בא לך להמשיך לדבר — שלח הודעה.",
        ],
        "delay_minutes": 10,
    },
}

# ── Fallback facts / achievements ──────────────────────
DEFAULT_ACHIEVEMENTS = [
    "הוביל את המאבק להורדת מחירי הדיור בעיר",
    "הביא תקציב של 50 מיליון שקל לשיפוץ בתי ספר",
    "סגר את המזבלה שקלקלה את האוויר בשכונה",
    "פתח 3 מעונות יום חדשים בשנה אחת",
    "העביר חוק שקיפות — כל הוצאה עירונית גלויה לציבור",
]

DEFAULT_FACTS = [
    "73% מהתושבים בשכונה שלך תומכים",
    "השכונה קיבלה פי 2 תקציב מאז שהוא נכנס",
    "כל ראשי השכונות חתמו על מכתב תמיכה",
    "העיר עלתה בדירוג איכות החיים ב-12 מקומות",
]


class WhatsAppSender:
    """
    שולח הודעת וואטסאפ מותאמת אישית אחרי כל שיחה.
    
    משתמש ב-Twilio WhatsApp Business API.
    מגדיר: TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM
    
    ה-from חייב להיות מספר וואטסאפ עסקי מאומת ב-Twilio.
    """
    
    def __init__(
        self,
        account_sid: Optional[str] = None,
        auth_token: Optional[str] = None,
        from_number: Optional[str] = None,
        candidate_name: Optional[str] = None,
        poll_location: Optional[str] = None,
        poll_hours: Optional[str] = None,
    ):
        self.account_sid = account_sid or os.getenv("TWILIO_ACCOUNT_SID", "")
        self.auth_token = auth_token or os.getenv("TWILIO_AUTH_TOKEN", "")
        self.from_number = from_number or os.getenv("TWILIO_WHATSAPP_FROM", "")
        self.candidate_name = candidate_name or os.getenv("CANDIDATE_NAME", "המועמד")
        self.poll_location = poll_location or os.getenv("POLL_LOCATION", "בית הספר השכונתי")
        self.poll_hours = poll_hours or os.getenv("POLL_HOURS", "07:00-22:00")
        self._client: Optional[TwilioClient] = None
        self._sent_count = 0
        self._enabled = bool(self.account_sid and self.auth_token and self.from_number)
        
        if not self._enabled:
            logger.warning("WhatsApp follow-up disabled: missing Twilio credentials")

    @property
    def client(self) -> Optional[TwilioClient]:
        if self._client is None and self._enabled:
            try:
                self._client = TwilioClient(self.account_sid, self.auth_token)
            except Exception as e:
                logger.error(f"Failed to init Twilio client: {e}")
                self._enabled = False
        return self._client

    def _pick_template(self, template_list: list) -> str:
        """Simple round-robin template selection."""
        return template_list[self._sent_count % len(template_list)]

    def _format_message(
        self,
        template: str,
        first_name: str,
        location: Optional[str] = None,
        hours: Optional[str] = None,
        day_of_week: Optional[str] = None,
        candidate_name: Optional[str] = None,
        achievement: Optional[str] = None,
        fact: Optional[str] = None,
        link: Optional[str] = None,
        topic: Optional[str] = None,
    ) -> str:
        """Format a template with voter-specific variables."""
        import random
        
        variables = {
            "first_name": first_name,
            "location": location or self.poll_location,
            "hours": hours or self.poll_hours,
            "day_of_week": day_of_week or "יום שלישי",
            "candidate_name": candidate_name or self.candidate_name,
            "achievement": achievement or random.choice(DEFAULT_ACHIEVEMENTS),
            "fact": fact or random.choice(DEFAULT_FACTS),
            "link": link or "",
            "topic": topic or "הנושא שדיברנו עליו",
        }
        
        result = template
        for key, val in variables.items():
            result = result.replace("{" + key + "}", str(val))
        
        # Remove empty link references
        result = result.replace(": \n", "\n").replace(": ", ": ")
        
        return result.strip()

    def _resolve_state(self, state: str) -> str:
        """Map any state value to a known template key."""
        known_states = {
            "opening": "default",
            "exploration": "exploration",
            "deescalation": "default",
            "amplification": "profiling",
            "profiling": "profiling",
            "persuasion": "default",
            "commitment": "commitment",
            "objection_handling": "objection_handling",
            "seed_planting": "seed_planting",
            "gotv": "gotv",
            "closing": "closing",
        }
        return known_states.get(state, "default")

    def send_followup(
        self,
        phone: str,
        state: str,
        first_name: str = "",
        voter_context: Optional[Dict] = None,
        metadata: Optional[Dict] = None,
        dry_run: bool = False,
    ) -> Dict:
        """
        Send a WhatsApp follow-up message after a call.
        
        Args:
            phone: Voter's phone number (E.164 format, e.g., +972501234567)
            state: Final conversation state (closing, objection_handling, etc.)
            first_name: Voter's first name
            voter_context: Optional voter context dict with extra info
            metadata: Optional metadata about the call
            dry_run: If True, returns the message without sending
        
        Returns:
            Dict with status, message_sid, and sent_text
        """
        if not self._enabled:
            return {"status": "disabled", "reason": "missing_twilio_credentials"}
        
        if not phone:
            return {"status": "skipped", "reason": "no_phone"}
        
        template_key = self._resolve_state(state)
        template_config = WHATSAPP_TEMPLATES.get(template_key, WHATSAPP_TEMPLATES["default"])
        template_text = self._pick_template(template_config["templates"])
        
        voter_ctx = voter_context or {}
        
        message_body = self._format_message(
            template_text,
            first_name=first_name or voter_ctx.get("first_name", ""),
            location=voter_ctx.get("poll_location"),
            hours=voter_ctx.get("poll_hours"),
            day_of_week=metadata.get("day_of_week") if metadata else None,
            candidate_name=self.candidate_name,
            topic=metadata.get("topic") if metadata else None,
            link=metadata.get("link") if metadata else None,
        )
        
        if dry_run:
            logger.info(f"[DRY RUN] Would send to {phone}: {message_body[:80]}...")
            return {
                "status": "dry_run",
                "phone": phone,
                "state": state,
                "template_key": template_key,
                "message": message_body,
            }
        
        try:
            twilio = self.client
            if not twilio:
                return {"status": "failed", "reason": "twilio_client_init_failed"}
            
            msg = twilio.messages.create(
                from_=f"whatsapp:{self.from_number}",
                body=message_body,
                to=f"whatsapp:{phone}",
            )
            
            self._sent_count += 1
            logger.info(
                f"WhatsApp sent to {phone} [{template_key}]: "
                f"sid={msg.sid}, status={msg.status}"
            )
            
            return {
                "status": "sent",
                "message_sid": msg.sid,
                "twilio_status": msg.status,
                "phone": phone,
                "state": state,
                "template_key": template_key,
                "message": message_body,
            }
            
        except TwilioRestException as e:
            logger.error(f"Twilio error sending to {phone}: {e}")
            return {"status": "failed", "reason": f"twilio_error: {e.code}", "detail": str(e)}
        except Exception as e:
            logger.error(f"Unexpected error sending to {phone}: {e}")
            return {"status": "failed", "reason": str(e)}

    def send_bulk_followup(
        self,
        recipients: list,
        dry_run: bool = False,
    ) -> list:
        """
        Send follow-ups to multiple recipients.
        
        Args:
            recipients: List of dicts with: phone, state, first_name, voter_context, metadata
            dry_run: If True, returns messages without sending
        
        Returns:
            List of result dicts
        """
        results = []
        for r in recipients:
            result = self.send_followup(
                phone=r.get("phone", ""),
                state=r.get("state", "closing"),
                first_name=r.get("first_name", ""),
                voter_context=r.get("voter_context"),
                metadata=r.get("metadata"),
                dry_run=dry_run,
            )
            results.append(result)
        
        sent = sum(1 for r in results if r.get("status") == "sent")
        logger.info(f"Bulk follow-up: {sent}/{len(results)} sent")
        return results

    def get_stats(self) -> Dict:
        """Return sender statistics."""
        return {
            "enabled": self._enabled,
            "sent_count": self._sent_count,
            "from_number": self.from_number,
            "candidate_name": self.candidate_name,
        }


# ── Integration Hook for Outbound Dialer ───────────────

def create_followup_hook(
    account_sid: Optional[str] = None,
    auth_token: Optional[str] = None,
    from_number: Optional[str] = None,
    **kwargs
):
    """
    Creates a hook function that can be attached to the outbound dialer.
    
    Usage:
        followup = create_followup_hook()
        dialer = OutboundDialer(agent, followup_hook=followup.send_after_call)
    
    The hook receives (phone, state, first_name, voter_context, metadata)
    and sends a WhatsApp message.
    """
    sender = WhatsAppSender(
        account_sid=account_sid,
        auth_token=auth_token,
        from_number=from_number,
        **kwargs,
    )
    
    async def send_after_call(
        phone: str,
        state: str,
        first_name: str = "",
        voter_context: Optional[Dict] = None,
        metadata: Optional[Dict] = None,
    ):
        """Async-compatible hook for outbound dialer integration."""
        import asyncio
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            sender.send_followup,
            phone, state, first_name, voter_context, metadata,
        )
    
    send_after_call.sender = sender
    return send_after_call
