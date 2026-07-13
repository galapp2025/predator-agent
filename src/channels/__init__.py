"""channels — WhatsApp and messaging adapters."""

from .whatsapp_followup import WhatsAppFollowup, build_followup_body, should_send_followup

__all__ = ["WhatsAppFollowup", "build_followup_body", "should_send_followup"]
