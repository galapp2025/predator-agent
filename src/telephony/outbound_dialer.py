"""Outbound Dialer — חיוג יוצא מקובץ leads.csv (טלפון+שם מלא+כתובת)"""
import asyncio
import csv
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

PredatorAgent = Any  # runtime-optional to avoid circular import

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

    def load_sorted_by_persuadability(self, campaign_type: str = "primaries") -> List[Dict]:
        """מיון DESC לפי persuadability לפני חיוג."""
        from ..scoring.persuadability import score_leads

        leads = self.load()
        scored = score_leads(leads, campaign_type=campaign_type)
        out = []
        for item in scored:
            row = dict(item.lead)
            row["persuadability"] = item.score
            out.append(row)
        return out

    def load_by_branch(self, branch: str) -> List[Dict]:
        return [l for l in self.load() if l.get("registered_branch") == branch]

class OutboundDialer:
    """מבצע חיוג יזום לרשימת הבוחרים."""

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
            # ב-dev מאפשרים דיאל גם מחוץ לשעות אם DIALER_FORCE=1
            if os.getenv("DIALER_FORCE", "").lower() not in ("1", "true", "yes"):
                return None
        async with self._semaphore:
            await self._rate_limit()
            record = self.build_call_record(lead)
            logger.info(
                f"[{record.session_id}] dialing {record.full_name} "
                f"<{record.phone}> addr={record.address} branch={record.registered_branch} "
                f"support={record.support_score:.2f} score={lead.get('persuadability', 'n/a')}"
            )

            # תור + session אצל הסוכן
            if self.queue is not None:
                try:
                    self.queue.enqueue_outbound(lead)
                except Exception as e:
                    logger.warning("queue enqueue failed: %s", e)

            if self.agent is not None:
                try:
                    from ..enrichment.voter_context import VoterContextBuilder

                    ctx = VoterContextBuilder().build(
                        first_name=lead.get("first_name", ""),
                        last_name=lead.get("last_name", ""),
                        city=lead.get("city", ""),
                        street=lead.get("street", ""),
                        house_number=lead.get("house_number", ""),
                        registered_branch=lead.get("registered_branch", ""),
                        support_score=float(lead.get("support_score") or 0.5),
                    )
                    self.agent.create_session(
                        record.session_id, voter_context=ctx, phone=lead.get("phone", "")
                    )
                    record.result = "session_ready"
                except Exception as e:
                    logger.error("create_session failed: %s", e)
                    record.result = "session_error"

            # SIP אמיתי אם מוגדר
            if os.getenv("TWILIO_ACCOUNT_SID") and os.getenv("ENABLE_SIP_DIAL", "").lower() in (
                "1",
                "true",
                "yes",
            ):
                try:
                    from .sip_manager import SIPManager

                    webhook = os.getenv("SIP_CALL_WEBHOOK_URL", "")
                    if not webhook:
                        raise RuntimeError("SIP_CALL_WEBHOOK_URL required for SIP dial")
                    sip = SIPManager()
                    sip.make_call(lead["phone"], webhook)
                    record.result = "dialed"
                except Exception as e:
                    logger.error("SIP dial failed: %s", e)
                    record.result = "sip_error"
            return record

    async def batch_dial(self, leads: Optional[List[Dict]] = None) -> List[CallRecord]:
        leads = leads if leads is not None else self.loader.load_sorted_by_persuadability()
        results = []
        for lead in leads:
            record = await self.dial_lead(lead)
            if record:
                results.append(record)
        return results

    async def run_campaign_from_csv(self) -> List[CallRecord]:
        """Pipeline: Scoring ממיין → Dial/Session → WhatsApp (אחרי end_session אם יש agent)."""
        from ..channels.whatsapp_followup import WhatsAppFollowup

        leads = self.loader.load_sorted_by_persuadability()
        logger.info(
            "Starting outbound campaign: %s leads (sorted by persuadability)",
            len(leads),
        )
        if leads:
            logger.info(
                "Top lead: %s score=%.3f",
                leads[0].get("full_name"),
                float(leads[0].get("persuadability") or 0),
            )
        records = await self.batch_dial(leads)
        self.save_history(records)

        dry = os.getenv("WHATSAPP_DRY_RUN", "true").lower() in ("1", "true", "yes")
        wa = WhatsAppFollowup()
        for rec in records:
            if self.agent is not None and rec.session_id in getattr(
                self.agent, "active_sessions", {}
            ):
                try:
                    ended = await self.agent.end_session(
                        rec.session_id,
                        outcome=rec.result or "answered",
                        duration_seconds=0,
                        send_whatsapp=True,
                        dry_run_whatsapp=dry,
                    )
                    rec.result = ended.get("final_state", rec.result)
                    rec.notes = str((ended.get("report") or {}).get("commitment", ""))
                except Exception as e:
                    logger.error("end_session failed: %s", e)
            else:
                wa.maybe_send_after_call(
                    {
                        "phone": rec.phone,
                        "full_name": rec.full_name,
                        "final_state": "closing",
                        "persona": "S",
                        "resistance": "low",
                    },
                    dry_run=dry,
                )
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
