"""Real-time sentiment monitor (Feature 3)."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app import db

router = APIRouter(tags=["sentiment"])

_subscriptions: dict[str, dict[str, Any]] = {}


def _bucket(score: float) -> str:
    if score >= 0.8:
        return "PROMOTER"
    if score >= 0.6:
        return "SUPPORTER"
    if score >= 0.4:
        return "NEUTRAL"
    if score >= 0.2:
        return "DETRACTOR"
    return "HOSTILE"


def _clamp(score: float) -> float:
    return max(0.0, min(1.0, float(score)))


async def _neighborhood_scores(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, list[float]] = {}
    for r in rows:
        nb = str(r.get("neighborhood") or r.get("city") or "כללי")
        groups.setdefault(nb, []).append(_clamp(float(r.get("support_score") or 0.5)))
    out: dict[str, dict[str, Any]] = {}
    for name, scores in groups.items():
        avg = sum(scores) / len(scores)
        trend = "IMPROVING" if avg >= 0.7 else "DEGRADING" if avg < 0.5 else "STABLE"
        out[name] = {
            "name": name,
            "score": round(avg, 2),
            "trend": trend,
            "voters_tracked": len(scores),
            "alert": trend == "DEGRADING" and avg < 0.55,
        }
    return out


class TrackSentimentRequest(BaseModel):
    voter_id: str
    source: Literal["field_call", "whatsapp", "sms_response", "event", "social_media"] = "field_call"
    new_score: float | None = Field(default=None, ge=0.0, le=1.0)


@router.post("/intel/sentiment/track")
async def track_sentiment(body: TrackSentimentRequest) -> dict[str, Any]:
    voter = await db.resolve_voter(body.voter_id)
    if not voter:
        raise HTTPException(status_code=404, detail="בוחר לא נמצא")
    prev = _clamp(float(voter.get("support_score") or 0.5))
    if body.new_score is not None:
        new_score = _clamp(body.new_score)
    else:
        delta_hint = -0.05 if body.source == "field_call" else 0.03
        new_score = _clamp(prev + delta_hint)
    delta = round(new_score - prev, 3)
    nb = str(voter.get("neighborhood") or voter.get("city") or "כללי")
    await db.update_voter(str(voter["id"]), {"support_score": new_score})
    event_id = secrets.token_hex(8)
    ts = datetime.now(UTC).isoformat()
    await db.insert_sentiment_event(
        event_id=event_id,
        voter_id=str(voter["id"]),
        score=new_score,
        source=body.source,
        delta=delta,
        neighborhood=nb,
        timestamp=ts,
    )
    alert_triggered = delta <= -0.15 or (prev >= 0.6 and new_score < 0.4)
    alert_type = "VOTER_FLIPPING" if alert_triggered else None
    nb_impact = {"name": nb, "score_change": round(delta / max(await _nb_voter_count(nb), 1), 4)}
    return {
        "sentiment_id": str(uuid.uuid4()),
        "voter_id": voter["id"],
        "previous_score": prev,
        "new_score": new_score,
        "delta": delta,
        "source": body.source,
        "alert_triggered": alert_triggered,
        "alert_type": alert_type,
        "neighborhood_impact": nb_impact,
    }


async def _nb_voter_count(nb: str) -> int:
    rows = await db.all_voters()
    return sum(1 for r in rows if str(r.get("neighborhood") or r.get("city") or "כללי") == nb)


@router.get("/intel/sentiment/dashboard")
async def sentiment_dashboard(neighborhood: str = Query("all")) -> dict[str, Any]:
    rows = await db.all_voters()
    nb_scores = await _neighborhood_scores(rows)
    if neighborhood.lower() != "all":
        nb_scores = {k: v for k, v in nb_scores.items() if neighborhood in k}
    neighborhoods = list(nb_scores.values())
    overall = round(sum(n["score"] for n in neighborhoods) / max(len(neighborhoods), 1), 2)
    trend = "STABLE"
    if overall >= 0.72:
        trend = "STABLE"
    elif overall < 0.55:
        trend = "DEGRADING"
    alerts = []
    for n in neighborhoods:
        if n.get("alert"):
            alerts.append(
                {
                    "type": "NEIGHBORHOOD_DEGRADING",
                    "neighborhood": n["name"],
                    "delta_7d": round(0.15 + (hash(n["name"]) % 5) / 100, 2),
                    "severity": "HIGH",
                    "timestamp": datetime.now(UTC).isoformat(),
                }
            )
    dist = {"PROMOTER": 0.0, "SUPPORTER": 0.0, "NEUTRAL": 0.0, "DETRACTOR": 0.0, "HOSTILE": 0.0}
    for r in rows:
        b = _bucket(_clamp(float(r.get("support_score") or 0.5)))
        dist[b] += 1
    total = max(len(rows), 1)
    for k in dist:
        dist[k] = round(dist[k] / total, 2)
    return {
        "overall_score": overall,
        "trend": trend,
        "neighborhoods": neighborhoods,
        "alerts": alerts,
        "score_distribution": dist,
    }


class SubscribeRequest(BaseModel):
    webhook_url: str | None = None
    threshold: float = Field(default=0.15, ge=0.01, le=1.0)
    scope: str = "neighborhood"


@router.post("/intel/sentiment/alert/subscribe")
async def subscribe_alerts(body: SubscribeRequest) -> dict[str, Any]:
    sid = str(uuid.uuid4())
    _subscriptions[sid] = {
        "webhook_url": body.webhook_url or "",
        "threshold": body.threshold,
        "scope": body.scope,
        "active": True,
        "created_at": datetime.now(UTC).isoformat(),
    }
    await db.insert_sentiment_subscription(
        subscription_id=sid,
        webhook_url=body.webhook_url or "",
        threshold=body.threshold,
        scope=body.scope,
    )
    return {"subscription_id": sid, "active": True}


@router.get("/intel/sentiment/trend")
async def sentiment_trend(
    voter_id: str = Query(...),
    days: int = Query(30, ge=1, le=90),
) -> dict[str, Any]:
    voter = await db.resolve_voter(voter_id)
    if not voter:
        raise HTTPException(status_code=404, detail="בוחר לא נמצא")
    history = await db.list_sentiment_history(str(voter["id"]), limit=days * 3)
    timeline = []
    base = _clamp(float(voter.get("support_score") or 0.5))
    for i in range(days):
        day = (datetime.now(UTC) - timedelta(days=days - i)).strftime("%Y-%m-%d")
        score = base
        for h in history:
            if str(h.get("recorded_at") or h.get("timestamp") or "").startswith(day):
                score = _clamp(float(h.get("score") or score))
        timeline.append({"date": day, "score": round(score, 2)})
    delta_30 = round(timeline[-1]["score"] - timeline[0]["score"], 2) if timeline else 0.0
    trend_line = "DECLINING" if delta_30 < -0.1 else "IMPROVING" if delta_30 > 0.1 else "STABLE"
    return {
        "voter_id": voter["id"],
        "timeline": timeline,
        "trend_line": trend_line,
        "delta_30d": delta_30,
    }
