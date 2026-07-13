"""Inbound Handler — שיחות נכנסות מסומנות מראש (pre-marked whitelist)"""
import csv
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

PredatorAgent = Any  # runtime-optional to avoid circular import

logger = logging.getLogger("inbound-handler")

@dataclass
class WhitelistEntry:
    phone: str
    full_name: str
    address: str = ""
    city: str = ""
    registered_branch: str = ""
    support_score: float = 0.5
    campaign_id: str = ""
    priority: int = 1
    metadata: Dict = field(default_factory=dict)

class PreMarkedRegistry:
    """
    רישום שיחות נכנסות מסומנות מראש.
    טוען מ-CSV את הרשימה הלבנה של הבוחרים שצפויים לחזור אלינו.
    """

    def __init__(self, csv_path: str = "data/inbound_whitelist.csv"):
        self.csv_path = csv_path
        self._entries: Dict[str, WhitelistEntry] = {}
        self.reload()

    def reload(self):
        self._entries = {}
        if not os.path.exists(self.csv_path):
            logger.warning(f"Whitelist CSV not found at {self.csv_path} — inbound pre-marking disabled")
            return
        with open(self.csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader, start=1):
                phone = (row.get("phone") or "").strip()
                if not phone:
                    continue
                first = (row.get("first_name") or "").strip()
                last = (row.get("last_name") or "").strip()
                address = ", ".join(filter(None, [
                    (row.get("street") or "").strip(),
                    (row.get("house_number") or "").strip(),
                ]))
                entry = WhitelistEntry(
                    phone=self._normalize_phone(phone),
                    full_name=f"{first} {last}".strip(),
                    address=address,
                    city=(row.get("city") or "").strip(),
                    registered_branch=(row.get("registered_branch") or "").strip(),
                    support_score=float(row.get("support_score") or 0.5),
                    campaign_id=(row.get("campaign_id") or "").strip(),
                    priority=int(row.get("priority") or 1),
                )
                self._entries[entry.phone] = entry
        logger.info(f"Loaded {len(self._entries)} pre-marked inbound numbers")

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        digits = "".join(ch for ch in phone if ch.isdigit())
        if digits.startswith("972"):
            digits = "0" + digits[3:]
        if not digits.startswith("0"):
            digits = "0" + digits
        return digits

    def is_pre_marked(self, phone: str) -> bool:
        return self._normalize_phone(phone) in self._entries

    def get_entry(self, phone: str) -> Optional[WhitelistEntry]:
        return self._entries.get(self._normalize_phone(phone))

    def get(self, phone: str) -> Optional[WhitelistEntry]:
        return self.get_entry(phone)

    def all_phones(self) -> Set[str]:
        return set(self._entries.keys())

class InboundHandler:
    """רק מספרים שסומנו מראש מקבלים מענה אנושי."""

    def __init__(
        self,
        agent: PredatorAgent,
        queue=None,
        whitelist_csv: str = "data/inbound_whitelist.csv",
    ):
        self.agent = agent
        self.queue = queue
        self.registry = PreMarkedRegistry(whitelist_csv)
        self.log_path = "data/inbound_log.json"
        self._log: List[Dict] = []

    def screen_call(self, caller_phone: str) -> Dict:
        if not self.registry.is_pre_marked(caller_phone):
            logger.info(f"[inbound] REJECTED (not pre-marked): {caller_phone}")
            return {
                "caller_phone": caller_phone,
                "pre_marked": False,
                "action": "polite_decline",
                "priority": 0,
                "message": "מספר זה אינו רשום במאגר. אנא השאר הודעה או חזור מאוחר יותר.",
            }
        entry = self.registry.get_entry(caller_phone)
        logger.info(
            f"[inbound] ACCEPTED pre-marked: {caller_phone} "
            f"({entry.full_name}, branch={entry.registered_branch})"
        )
        return {
            "caller_phone": caller_phone,
            "pre_marked": True,
            "action": "route_to_agent",
            "priority": entry.priority,
            "voter_entry": entry.__dict__,
        }

    def route_to_session(self, call_data: Dict):
        from ..enrichment.voter_context import VoterContextBuilder

        if not call_data.get("pre_marked"):
            return None

        entry_dict = call_data.get("voter_entry", {})
        name_parts = entry_dict.get("full_name", "").split()
        first = name_parts[0] if name_parts else ""
        last = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""
        address = entry_dict.get("address", "")
        addr_parts = [p.strip() for p in address.split(",")]
        street = addr_parts[0] if len(addr_parts) >= 1 else ""
        house_number = addr_parts[1] if len(addr_parts) >= 2 else ""

        builder = VoterContextBuilder()
        ctx = builder.build(
            first_name=first,
            last_name=last,
            city=entry_dict.get("city", ""),
            street=street,
            house_number=house_number,
            registered_branch=entry_dict.get("registered_branch", ""),
            support_score=entry_dict.get("support_score", 0.5),
            campaign_type="primaries",
        )
        session_id = f"in-{call_data['caller_phone']}-{int(datetime.now().timestamp())}"
        session = self.agent.create_session(session_id, voter_context=ctx)
        self._log.append({
            "ts": datetime.now().isoformat(),
            "type": "inbound_accepted",
            "phone": call_data["caller_phone"],
            "full_name": entry_dict.get("full_name"),
        })
        self._persist_log()
        return session

    def handle(self, caller_phone: str):
        decision = self.screen_call(caller_phone)
        if decision["action"] == "route_to_agent":
            return self.route_to_session(decision)
        return None

    def _persist_log(self):
        os.makedirs(os.path.dirname(self.log_path) or ".", exist_ok=True)
        with open(self.log_path, "w", encoding="utf-8") as f:
            json.dump(self._log, f, ensure_ascii=False, indent=2)
