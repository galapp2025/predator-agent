"""Outbound Dialer — חיוג יוצא מקובץ leads.csv (טלפון+שם מלא+כתובת)"""
import asyncio
import csv
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from ..agent.predator import PredatorAgent

logger = logging.getLogger("outbound-dialer")


@dataclass
class CallRecord:
    phone: str
    first_name: str
    last_name: str
    full_name: str
    address: str
    city: str
    street: str
    house_number: str
    registered_branch: str
    support_score: float
    session_id: str
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    result: str = "pending"
    transcript: list = field(default_factory=list)
    notes: str = ""


class LeadLoader:
    """קורא את קובץ הבוחרים (CSV) — טלפון + שם מלא + כתובת."""

    REQUIRED_COLUMNS = ["phone", "first_name", "last_name"]
    OPTIONAL_COLUMNS = ["city", "street", "house_number", "registered_branch", "support_score"]

    def __init__(self, csv_path: str = "data/leads.csv"):
        self.csv_path = csv_path

    def load(self) -> List[Dict]:
        if not os.path.exists(self.csv_path):
            logger.error(f"leads.csv not found: {self.csv_path}")
            return []

        leads = []
        with open(self.csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader, start=1):
                phone = (row.get("phone") or "").strip()
                if not phone:
                    logger.warning(f"Row {idx}: missing phone, skipped")
                    continue
                first = (row.get("first_name") or "").strip()
                last = (row.get("last_name") or "").strip()
                if not first and not last:
                    logger.warning(f"Row {idx}: missing name, skipped")
                    continue
                lead = {
                    "phone": phone,
                    "first_name": first,
                    "last_name": last,
                    "full_name": f"{first} {last}".strip(),
                    "city": (row.get("city") or "").strip(),
                    "street": (row.get("street") or "").strip(),
                    "house_number": (row.get("house_number") or "").strip(),
                    "address": ", ".join(filter(None, [
                        (row.get("street") or "").strip(),
                        (row.get("house_number") or "").strip(),
                        (row.get("city") or "").strip(),
                    ])),
                    "registered_branch": (row.get("registered_branch") or "").strip(),
                    "support_score": float(row.get("support_score") or 0.5),
                }
                leads.append(lead)
        logger.info(f"Loaded {len(leads)} leads from {self.csv_path}")
        return leads

    def load_by_branch(self, branch: str) -> List[Dict]:
        return [l for l in self.load() if l.get("registered_branch") == branch]


class OutboundDialer:
    """
    מבצע חיוג יזום לרשימת הבוחרים.
    כל בוחר מקבל CallRecord עם שם מלא + כתובת + סניף + ציון תמיכה.
    """

    def __init__(
        self,
        agent: PredatorAgent,
        queue=None,
        history_path: str = "data/call_history.json",
        csv_path: str = "data/leads.csv",
    ):
        self.agent = agent
        self.queue = queue
        self.history_path = history_path
        self.loader = LeadLoader(csv_path)
        self.max_concurrent = int(os.getenv("DIALER_MAX_CONCURRENT", "3"))
        self.retry_attempts = int(os.getenv("DIALER_RETRY_ATTEMPTS", "2"))
        self.rate_limit_per_minute = int(os.getenv("DIALER_RATE_LIMIT", "10"))
        self._semaphore = asyncio.Semaphore(self.max_concurrent)
        self._last_dial_times: List[float] = []

    def is_working_hours(self) -> bool:
        hour = datetime.now().hour
        return 9 <= hour < 21

    def _format_address(self, lead: Dict) -> str:
        return lead.get("address") or ", ".join(filter(None, [
            lead.get("street", ""),
            lead.get("house_number", ""),
            lead.get("city", ""),
        ]))

    def build_call_record(self, lead: Dict) -> CallRecord:
        session_id = f"out-{lead['phone']}-{int(datetime.now().timestamp())}"
        return CallRecord(
            phone=lead["phone"],
            first_name=lead.get("first_name", ""),
            last_name=lead.get("last_name", ""),
            full_name=lead.get("full_name", ""),
            address=self._format_address(lead),
            city=lead.get("city", ""),
            street=lead.get("street", ""),
            house_number=lead.get("house_number", ""),
            registered_branch=lead.get("registered_branch", ""),
            support_score=float(lead.get("support_score", 0.5)),
            session_id=session_id,
            started_at=datetime.now().isoformat(),
        )

    async def _rate_limit(self):
        import time
        now = time.time()
        self._last_dial_times = [t for t in self._last_dial_times if now - t < 60]
        if len(self._last_dial_times) >= self.rate_limit_per_minute:
            sleep_for = 60 - (now - self._last_dial_times[0]) + 0.5
            logger.info(f"Rate limit hit, sleeping {sleep_for:.1f}s")
            await asyncio.sleep(sleep_for)
        self._last_dial_times.append(time.time())

    async def dial_lead(self, lead: Dict) -> Optional[CallRecord]:
        if not self.is_working_hours():
            logger.info("Outside working hours (9-21), skipping")
            return None

        async with self._semaphore:
            await self._rate_limit()
            record = self.build_call_record(lead)
            logger.info(
                f"[{record.session_id}] dialing {record.full_name} "
                f"<{record.phone}> addr={record.address} branch={record.registered_branch} "
                f"support={record.support_score:.2f}"
            )
            return record

    async def batch_dial(self, leads: Optional[List[Dict]] = None) -> List[CallRecord]:
        leads = leads if leads is not None else self.loader.load()
        results = []
        for lead in leads:
            if not self.is_working_hours():
                logger.info("Working hours ended, stopping batch")
                break
            record = await self.dial_lead(lead)
            if record:
                results.append(record)
        return results

    async def run_campaign_from_csv(self, use_scoring: bool = True) -> List[CallRecord]:
        """מצב קמפיין: טוען CSV, מנקד בוחרים, ממיין לפי סיכוי שכנוע, מחייג."""
        leads = self.loader.load()

        # ── Scoring integration ──
        if use_scoring:
            try:
                from ..scoring.persuadability import PersudadabilityScorer
                scorer = PersudadabilityScorer(history_path=self.history_path)
                scored = scorer.score_csv(self.loader.csv_path)
                # Sort leads by persuadability score (highest first)
                scored_map = {s.phone: s.persuadability_score for s in scored}
                leads.sort(key=lambda l: scored_map.get(l["phone"], 0.5), reverse=True)
                top_score = scored_map.get(leads[0]['phone'], '?')
                logger.info(
                    f"Scoring enabled: {len(leads)} leads sorted by persuadability. "
                    f"Top: {leads[0].get('full_name', '?')} ({top_score})"
                )
            except ImportError:
                logger.warning("Scoring module not available, using original order")
            except Exception as e:
                logger.warning(f"Scoring failed: {e}, using original order")

        logger.info(f"Starting outbound campaign: {len(leads)} leads")
        records = await self.batch_dial(leads)
        self.save_history(records)

        # ── WhatsApp follow-up integration ──
        self._send_followups(records)

        return records

    def save_history(self, records: List[CallRecord]):
        os.makedirs(os.path.dirname(self.history_path) or ".", exist_ok=True)
        history = []
        if os.path.exists(self.history_path):
            try:
                with open(self.history_path, "r", encoding="utf-8") as f:
                    history = json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                history = []
        history.extend([r.__dict__ for r in records])
        with open(self.history_path, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {len(records)} records to {self.history_path}")

    def _send_followups(self, records: List[CallRecord]):
        """Send WhatsApp follow-ups after campaign batch completes."""
        try:
            from ..channels.whatsapp_followup import WhatsAppSender
            sender = WhatsAppSender()
            if not sender._enabled:
                return
            for record in records:
                if record.result == "pending":
                    continue
                try:
                    sender.send_followup(
                        phone=record.phone,
                        state="closing",
                        first_name=record.first_name,
                    )
                except Exception as e:
                    logger.debug(f"Follow-up skipped for {record.phone}: {e}")
        except ImportError:
            pass
        except Exception as e:
            logger.warning(f"WhatsApp follow-up error: {e}")
