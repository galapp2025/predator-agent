"""SIP Manager — LiveKit SIP Bridge"""
import os
from typing import Optional
from dataclasses import dataclass


@dataclass
class SIPConfig:
    trunk_id: str
    phone_number: str
    account_sid: str
    auth_token: str
    livekit_sip_url: str


class SIPManager:
    def __init__(self):
        self.config = SIPConfig(
            trunk_id=os.getenv("TWILIO_SIP_TRUNK_ID", ""),
            phone_number=os.getenv("TWILIO_PHONE_NUMBER", ""),
            account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
            auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
            livekit_sip_url=os.getenv("LIVEKIT_URL", "wss://predator-gnzrgpca.livekit.cloud"),
        )

    def is_configured(self):
        return all([self.config.trunk_id, self.config.phone_number, self.config.account_sid])

    def get_dispatch_rule(self):
        return {
            "rule": {
                "dispatchRuleIndividual": {
                    "roomPrefix": "call-"
                }
            }
        }
