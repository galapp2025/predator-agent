"""Telephony module — SIP, dialer, queue, inbound"""
from .sip_manager import SIPManager, SIPConfig
from .outbound_dialer import OutboundDialer, CallRecord
from .call_queue import CallQueue, QueueItem
from .inbound_handler import InboundHandler
