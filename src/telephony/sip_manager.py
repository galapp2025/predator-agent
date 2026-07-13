import os
from dataclasses import dataclass
try:
 from twilio.rest import Client
except ImportError:
 Client=None
@dataclass(frozen=True)
class SIPConfig:
 account_sid:str;auth_token:str;from_number:str;sip_domain:str="";livekit_sip_trunk_id:str=""
 @classmethod
 def from_env(cls):return cls(os.getenv("TWILIO_ACCOUNT_SID",""),os.getenv("TWILIO_AUTH_TOKEN",""),os.getenv("TWILIO_PHONE_NUMBER",""),os.getenv("TWILIO_SIP_DOMAIN",""),os.getenv("LIVEKIT_SIP_TRUNK_ID",""))
class SIPManager:
 def __init__(self,config=None):self.config=config or SIPConfig.from_env();self.client=Client(self.config.account_sid,self.config.auth_token) if Client and self.config.account_sid and self.config.auth_token else None
 def configured(self):return bool(self.client and self.config.from_number)
 def make_call(self,to,webhook_url):
  if not self.configured():raise RuntimeError("Twilio SIP is not configured")
  return self.client.calls.create(to=to,from_=self.config.from_number,url=webhook_url)
