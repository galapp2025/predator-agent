"""Micro-Targeting Message Engine (Feature 1)."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import db

router = APIRouter(tags=["messaging"])

TOPIC_HE: dict[str, str] = {
    "education": "חינוך",
    "community": "קהילה",
    "safety": "בטחון",
    "infrastructure": "תשתיות",
    "religion": "דת",
    "youth": "נוער",
    "elderly": "קשישים",
    "business": "עסקים",
    "environment": "סביבה",
    "housing": "דיור",
    "taxes": "מיסים",
    "health": "בריאות",
    "transportation": "תחבורה",
    "culture": "תרבות",
    "technology": "טכנולוגיה",
}


class TopicKey(str, Enum):
    education = "education"
    community = "community"
    safety = "safety"
    infrastructure = "infrastructure"
    religion = "religion"
    youth = "youth"
    elderly = "elderly"
    business = "business"
    environment = "environment"
    housing = "housing"
    taxes = "taxes"
    health = "health"
    transportation = "transportation"
    culture = "culture"
    technology = "technology"


def _infer_signals(voter: dict[str, Any]) -> list[str]:
    signals: list[str] = []
    nb = str(voter.get("neighborhood") or "")
    city = str(voter.get("city") or "")
    support = float(voter.get("support_score") or 0.5)
    gotv = str(voter.get("gotv_category") or "swing").lower()
    if "נווה" in nb or "שכונה" in nb:
        signals.append("community_leader")
    if support >= 0.8:
        signals.append("loyal_supporter")
    if "swing" in gotv:
        signals.append("persuadable")
    if "at_risk" in gotv:
        signals.append("needs_urgency")
    if voter.get("phone"):
        signals.append("reachable_mobile")
    if voter.get("email"):
        signals.append("digital_channel")
    if "פתח" in city:
        signals.append("local_petah_tikva")
    if not signals:
        signals = ["general_voter", "local_resident"]
    return signals[:5]


def _pick_topic(signals: list[str], override: str | None = None) -> tuple[str, str]:
    if override and override in TOPIC_HE.values():
        inv = {v: k for k, v in TOPIC_HE.items()}
        return inv.get(override, "community"), override
    if "community_leader" in signals or "local_petah_tikva" in signals:
        return "education", TOPIC_HE["education"]
    if "persuadable" in signals:
        return "community", TOPIC_HE["community"]
    if "needs_urgency" in signals:
        return "safety", TOPIC_HE["safety"]
    return "community", TOPIC_HE["community"]


def _tone(gotv: str) -> str:
    g = gotv.lower()
    if "safe" in g:
        return "מחזקים נאמנות והוקרה"
    if "leaning" in g:
        return "מעודדים ומחזקים"
    if "at_risk" in g:
        return "דחוף וישיר"
    if "lost" in g:
        return "קצר ומינימלי"
    return "רך ומזמין"


def _build_channels(
    first: str,
    last: str,
    nb: str,
    topic_he: str,
    tone: str,
) -> dict[str, str]:
    full = f"{first} {last}".strip()
    return {
        "whatsapp": (
            f"שלום {first}, כתושב/ת {nb or 'פתח תקווה'}, חשוב לך לדעת שתוכנית המועמד בנושא {topic_he} "
            f"כוללת צעדים ממשיים לשכונה. {tone}. אפשר לדבר?"
        ),
        "sms": f"{first} 👋 מידע על {topic_he} בפתח תקווה. שלח/י 'כן' לפרטים >>",
        "phone_script": (
            f"פתיחה: 'שלום {full}, מדבר/ת מטעם הקמפיין, שמתי/תי לב שאת/ה מ{nb or 'העיר'}.' | "
            f"גוף: 3 נקודות על {topic_he} | סגירה: קריאה להצביע ולשתף"
        ),
        "door_knock": (
            f"TOPIC: {topic_he} | ICE BREAKER: 'שמעתי על האתגרים בשכונת {nb or 'העיר'}...' | "
            f"TALKING POINTS: 1. {topic_he} 2. שקיפות 3. מעורבות קהילתית"
        ),
    }


def _confidence(signals: list[str], topic_key: str, voter: dict[str, Any]) -> float:
    base = min(len(signals) / 5.0, 1.0) * 0.6
    bonus = 0.25 if voter.get("enriched_at") else 0.15
    if topic_key == "education" and "community_leader" in signals:
        bonus += 0.15
    return round(min(0.98, base + bonus), 2)


async def _generate_for_voter(voter: dict[str, Any], topic_override: str | None = None) -> dict[str, Any]:
    first = str(voter.get("first_name") or "")
    last = str(voter.get("last_name") or "")
    nb = str(voter.get("neighborhood") or voter.get("city") or "")
    gotv = str(voter.get("gotv_category") or "SWING").upper()
    signals = _infer_signals(voter)
    topic_key, topic_he = _pick_topic(signals, topic_override)
    channels = _build_channels(first, last, nb, topic_he, _tone(gotv))
    conf = _confidence(signals, topic_key, voter)
    ts = datetime.now(UTC).isoformat()
    vid = str(voter.get("id"))
    for ch, text in channels.items():
        await db.insert_generated_message(
            message_id=secrets.token_hex(8),
            voter_id=vid,
            channel=ch,
            text=text,
            target_topic=topic_he,
            confidence=conf,
            timestamp=ts,
        )
    return {
        "voter_id": vid,
        "full_name": f"{first} {last}".strip(),
        "gotv_category": gotv,
        "neighborhood": nb,
        "osint_signals": signals,
        "channels": channels,
        "target_topic": topic_he,
        "confidence": conf,
    }


class GenerateMessageRequest(BaseModel):
    voter_id: str


@router.post("/intel/messages/generate")
async def generate_message(body: GenerateMessageRequest) -> dict[str, Any]:
    voter = await db.resolve_voter(body.voter_id)
    if not voter:
        raise HTTPException(status_code=404, detail="בוחר לא נמצא")
    return await _generate_for_voter(voter)


class BatchGenerateRequest(BaseModel):
    voter_ids: list[str] = Field(default_factory=list)
    topic: str | None = None
    max_count: int = Field(default=200, ge=1, le=500)


@router.post("/intel/messages/batch-generate")
async def batch_generate(body: BatchGenerateRequest) -> dict[str, Any]:
    topic_he = body.topic
    results: list[dict[str, Any]] = []
    for vid in body.voter_ids[: body.max_count]:
        voter = await db.resolve_voter(vid)
        if not voter:
            continue
        results.append(await _generate_for_voter(voter, topic_he))
    topics_used: dict[str, int] = {}
    for r in results:
        t = r.get("target_topic") or "קהילה"
        topics_used[t] = topics_used.get(t, 0) + 1
    return {"generated": len(results), "voters": results, "topics_used": topics_used}


@router.get("/intel/messages/topics")
async def message_topics() -> dict[str, Any]:
    topics = list(TOPIC_HE.values())
    coverage = {t: round(0.55 + (hash(t) % 30) / 100.0, 2) for t in topics}
    return {"topics": topics, "coverage": coverage}


@router.get("/intel/messages/history/{voter_id}")
async def message_history(voter_id: str) -> dict[str, Any]:
    voter = await db.resolve_voter(voter_id)
    if not voter:
        raise HTTPException(status_code=404, detail="בוחר לא נמצא")
    rows = await db.list_generated_messages(str(voter["id"]))
    messages = [
        {
            "timestamp": r.get("timestamp"),
            "channel": r.get("channel"),
            "text": r.get("text"),
            "target_topic": r.get("target_topic"),
            "confidence": r.get("confidence"),
        }
        for r in rows
    ]
    return {"voter_id": voter["id"], "messages": messages}
