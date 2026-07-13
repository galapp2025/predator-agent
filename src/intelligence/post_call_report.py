"""Post-call Report — סיכום מובנה לכל שיחה + אגרגציה + דחיפה למנהל קמפיין"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("post-call-report")


@dataclass
class PostCallReport:
    voter: str
    call_duration: str
    final_state: str
    resistance_peak: str
    top_issue: str
    commitment: str
    recommended_followup: str
    sentiment_trajectory: List[str] = field(default_factory=list)
    phone: str = ""
    persona: str = "S"
    resistance: str = "medium"
    poll_location: str = ""
    session_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


EXAMPLE_REPORT = {
    "voter": "ישראל ישראלי",
    "call_duration": "3:42",
    "final_state": "closing",
    "resistance_peak": "high (exchange 5: 'אתה רובוט?')",
    "top_issue": "חינוך",
    "commitment": "הבטיח להגיע ביום שלישי בערב",
    "recommended_followup": "שלח וואטסאפ יום לפני עם מיקום קלפי",
    "sentiment_trajectory": ["neutral", "positive", "angry", "positive", "committed"],
}


ISSUE_KEYWORDS = {
    "חינוך": ["חינוך", "בית ספר", "גן", "מורה", "בגרות", "מלגה"],
    "ביטחון": ["ביטחון", "פשיעה", "מצלמות", "תאורה", "אלימות"],
    "תחבורה": ["פקקים", "חניה", "אוטובוס", "רכבת", "כביש"],
    "דיור": ["דיור", "שכירות", "ארנונה", "דירה"],
    "יוקר מחיה": ["יוקר", "מחירים", "חשמל", "מים", "ארנונה"],
}

SENTIMENT_POS = ["כן", "סבבה", "אשמח", "בטח", "מסכים", "תומך", "מעולה"]
SENTIMENT_NEG = ["לא", "די", "תעזוב", "רובוט", "בוט", "נגד", "כועס"]
SENTIMENT_ANGRY = ["תעזוב", "רובוט", "בוט", "מחשב", "הציק", "חצוף"]


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    return f"{m}:{s:02d}"


def _detect_issue(text: str) -> str:
    scores = {k: 0 for k in ISSUE_KEYWORDS}
    for issue, words in ISSUE_KEYWORDS.items():
        for w in words:
            if w in text:
                scores[issue] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "כללי"


def _sentiment_of(text: str) -> str:
    t = text.lower()
    if any(w in t for w in SENTIMENT_ANGRY):
        return "angry"
    if any(w in text for w in SENTIMENT_POS):
        return "positive"
    if any(w in text for w in SENTIMENT_NEG):
        return "negative"
    return "neutral"


def _extract_commitment(history: List[Dict[str, str]]) -> str:
    blob = " ".join(m.get("content", "") for m in history)
    if re.search(r"יום שלישי.*(ערב|בוקר)", blob):
        return "הבטיח להגיע ביום שלישי" + (" בערב" if "ערב" in blob else "")
    if "אגיע" in blob or "בוא" in blob or "אשמח להגיע" in blob:
        return "הביע נכונות להגיע לקלפי"
    if "לא מעוניין" in blob or "אל תתקשר" in blob:
        return "אין התחייבות"
    return "לא סווגה התחייבות ברורה"


def _resistance_peak(history: List[Dict[str, str]], resistance_events: Optional[List[dict]] = None) -> str:
    if resistance_events:
        peak = max(resistance_events, key=lambda e: e.get("score", 0))
        ex = peak.get("exchange", "?")
        quote = peak.get("quote") or peak.get("text") or ""
        level = peak.get("level", "high")
        if quote:
            return f"{level} (exchange {ex}: '{quote[:40]}')"
        return f"{level} (exchange {ex})"
    for i, msg in enumerate(history, start=1):
        if msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if any(x in content for x in ("רובוט", "בוט", "מחשב", "AI")):
            return f"high (exchange {i}: '{content[:40]}')"
    return "medium"


def build_report_heuristic(
    *,
    voter: str,
    history: List[Dict[str, str]],
    final_state: str,
    duration_seconds: float = 0,
    persona: str = "S",
    resistance: str = "medium",
    phone: str = "",
    poll_location: str = "",
    session_id: str = "",
    resistance_events: Optional[List[dict]] = None,
) -> PostCallReport:
    user_text = " ".join(m["content"] for m in history if m.get("role") == "user")
    trajectory = [_sentiment_of(m["content"]) for m in history if m.get("role") == "user"]
    if final_state in ("closing", "commitment", "gotv") and trajectory:
        trajectory = list(trajectory) + ["committed"]

    commitment = _extract_commitment(history)
    followup = "שלח וואטסאפ יום לפני עם מיקום קלפי"
    if "אין התחייבות" in commitment:
        followup = "לא לשלוח follow-up — דגל DNC אם ביקש"
    elif final_state == "seed_planting":
        followup = "הודעת ערך קצרה בעוד 3 ימים — בלי לחץ"

    return PostCallReport(
        voter=voter or "לא ידוע",
        call_duration=_format_duration(duration_seconds),
        final_state=final_state or "closing",
        resistance_peak=_resistance_peak(history, resistance_events),
        top_issue=_detect_issue(user_text),
        commitment=commitment,
        recommended_followup=followup,
        sentiment_trajectory=trajectory or ["neutral"],
        phone=phone,
        persona=persona,
        resistance=resistance,
        poll_location=poll_location,
        session_id=session_id,
    )


class PostCallReporter:
    """
    Per-call: structured summary via LLM extraction (fallback heuristic)
    Aggregate: JSONL/Parquet-ready rows → insights
    Push: Slack / Telegram / WhatsApp למנהל קמפיין
    """

    def __init__(
        self,
        store_dir: str = "data/reports",
        openai_api_key: Optional[str] = None,
    ):
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        self.jsonl_path = self.store_dir / "calls.jsonl"

    async def extract_with_llm(self, history: List[Dict[str, str]], meta: dict) -> Optional[PostCallReport]:
        if not self.openai_api_key:
            return None
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=self.openai_api_key)
            schema_hint = json.dumps(EXAMPLE_REPORT, ensure_ascii=False, indent=2)
            transcript = "\n".join(f"{m.get('role')}: {m.get('content')}" for m in history)
            prompt = (
                "חלץ סיכום שיחת קמפיין בעברית כ-JSON בלבד לפי הסכמה הבאה:\n"
                f"{schema_hint}\n\n"
                f"meta: {json.dumps(meta, ensure_ascii=False)}\n\n"
                f"transcript:\n{transcript}"
            )
            resp = await client.chat.completions.create(
                model=os.getenv("POSTCALL_LLM_MODEL", "gpt-4.1-mini"),
                temperature=0.2,
                max_tokens=500,
                messages=[
                    {"role": "system", "content": "You extract structured JSON only. No markdown."},
                    {"role": "user", "content": prompt},
                ],
            )
            raw = resp.choices[0].message.content or ""
            raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(raw)
            return PostCallReport(
                voter=data.get("voter") or meta.get("voter", ""),
                call_duration=data.get("call_duration") or _format_duration(meta.get("duration_seconds", 0)),
                final_state=data.get("final_state") or meta.get("final_state", "closing"),
                resistance_peak=data.get("resistance_peak", "medium"),
                top_issue=data.get("top_issue", "כללי"),
                commitment=data.get("commitment", ""),
                recommended_followup=data.get("recommended_followup", ""),
                sentiment_trajectory=list(data.get("sentiment_trajectory") or []),
                phone=meta.get("phone", ""),
                persona=meta.get("persona", "S"),
                resistance=meta.get("resistance", "medium"),
                poll_location=meta.get("poll_location", ""),
                session_id=meta.get("session_id", ""),
            )
        except Exception as e:
            logger.warning("LLM extraction failed: %s", e)
            return None

    async def build(
        self,
        *,
        voter: str,
        history: List[Dict[str, str]],
        final_state: str,
        duration_seconds: float = 0,
        persona: str = "S",
        resistance: str = "medium",
        phone: str = "",
        poll_location: str = "",
        session_id: str = "",
        resistance_events: Optional[List[dict]] = None,
        use_llm: bool = True,
    ) -> PostCallReport:
        meta = {
            "voter": voter,
            "final_state": final_state,
            "duration_seconds": duration_seconds,
            "persona": persona,
            "resistance": resistance,
            "phone": phone,
            "poll_location": poll_location,
            "session_id": session_id,
        }
        report = None
        if use_llm:
            report = await self.extract_with_llm(history, meta)
        if report is None:
            report = build_report_heuristic(
                voter=voter,
                history=history,
                final_state=final_state,
                duration_seconds=duration_seconds,
                persona=persona,
                resistance=resistance,
                phone=phone,
                poll_location=poll_location,
                session_id=session_id,
                resistance_events=resistance_events,
            )
        self.persist(report)
        return report

    def persist(self, report: PostCallReport) -> Path:
        with self.jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(report.to_dict(), ensure_ascii=False) + "\n")
        single = self.store_dir / f"{report.session_id or 'call'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        single.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return single

    def load_all(self) -> List[dict]:
        if not self.jsonl_path.exists():
            return []
        rows = []
        for line in self.jsonl_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def aggregate_insights(self) -> dict:
        """Aggregate JSONL → insights (pandas אם זמין, אחרת pure Python)."""
        rows = self.load_all()
        if not rows:
            return {"calls": 0, "insights": []}

        try:
            import pandas as pd

            df = pd.DataFrame(rows)
            insights = {
                "calls": int(len(df)),
                "by_final_state": df["final_state"].value_counts().to_dict() if "final_state" in df else {},
                "top_issues": df["top_issue"].value_counts().head(5).to_dict() if "top_issue" in df else {},
                "commitment_rate": float(
                    df["commitment"].astype(str).str.contains("הבטיח|נכונות").mean()
                )
                if "commitment" in df
                else 0.0,
            }
            # optional parquet snapshot
            parquet_path = self.store_dir / "calls.parquet"
            try:
                df.to_parquet(parquet_path, index=False)
                insights["parquet"] = str(parquet_path)
            except Exception:
                pass
            return insights
        except ImportError:
            from collections import Counter

            states = Counter(r.get("final_state") for r in rows)
            issues = Counter(r.get("top_issue") for r in rows)
            commits = sum(
                1
                for r in rows
                if any(x in str(r.get("commitment", "")) for x in ("הבטיח", "נכונות"))
            )
            return {
                "calls": len(rows),
                "by_final_state": dict(states),
                "top_issues": dict(issues.most_common(5)),
                "commitment_rate": commits / max(1, len(rows)),
            }

    def push_to_manager(self, report: PostCallReport, channels: Optional[List[str]] = None) -> dict:
        """Push סיכום ל-Slack/Telegram/WhatsApp (webhooks מ-.env)."""
        channels = channels or ["slack", "telegram", "whatsapp"]
        text = (
            f"📞 סיכום שיחה — {report.voter}\n"
            f"משך: {report.call_duration} | מצב: {report.final_state}\n"
            f"שיא התנגדות: {report.resistance_peak}\n"
            f"נושא: {report.top_issue}\n"
            f"התחייבות: {report.commitment}\n"
            f"Follow-up: {report.recommended_followup}\n"
            f"Sentiment: {' → '.join(report.sentiment_trajectory)}"
        )
        results = {}
        if "slack" in channels:
            results["slack"] = self._push_webhook(os.getenv("SLACK_WEBHOOK_URL"), {"text": text})
        if "telegram" in channels:
            results["telegram"] = self._push_telegram(text)
        if "whatsapp" in channels:
            # מנהל קמפיין — מספר ייעודי
            manager = os.getenv("CAMPAIGN_MANAGER_WHATSAPP", "")
            if manager:
                try:
                    from ..channels.whatsapp_followup import WhatsAppFollowup

                    wa = WhatsAppFollowup()
                    # שליחה ישירה של הטקסט המלא
                    if wa.configured:
                        from twilio.rest import Client

                        client = Client(wa.account_sid, wa.auth_token)
                        to = manager if manager.startswith("whatsapp:") else f"whatsapp:{manager}"
                        msg = client.messages.create(from_=wa.from_whatsapp, to=to, body=text)
                        results["whatsapp"] = {"status": "sent", "sid": msg.sid}
                    else:
                        results["whatsapp"] = {"status": "dry_run", "body": text}
                except Exception as e:
                    results["whatsapp"] = {"status": "error", "error": str(e)}
            else:
                results["whatsapp"] = {"status": "skipped", "reason": "no CAMPAIGN_MANAGER_WHATSAPP"}
        return results

    def _push_webhook(self, url: Optional[str], payload: dict) -> dict:
        if not url:
            return {"status": "skipped", "reason": "no webhook"}
        try:
            import urllib.request

            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return {"status": "sent", "code": resp.status}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _push_telegram(self, text: str) -> dict:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            return {"status": "skipped", "reason": "no telegram creds"}
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        return self._push_webhook(url, {"chat_id": chat_id, "text": text})
