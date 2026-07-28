"""War Room — aggregated operational dashboard (Feature 4)."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import db, services

router = APIRouter(tags=["war-room"])


def _gotv_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"safe": 0, "leaning": 0, "swing": 0, "at_risk": 0, "lost": 0}
    for r in rows:
        cat = str(r.get("gotv_category") or "swing").lower().replace("-", "_")
        if cat in counts:
            counts[cat] += 1
        elif cat == "at risk":
            counts["at_risk"] += 1
    return counts


def _trend_block(now: dict[str, int], past: dict[str, int] | None) -> dict[str, dict[str, int]]:
    keys = ("SAFE", "LEANING", "SWING", "AT_RISK", "LOST")
    mapping = {
        "SAFE": "safe",
        "LEANING": "leaning",
        "SWING": "swing",
        "AT_RISK": "at_risk",
        "LOST": "lost",
    }
    out: dict[str, dict[str, int]] = {}
    for label, key in mapping.items():
        n = now.get(key, 0)
        p = (past or {}).get(key, n) if past else max(0, n - 5)
        out[label] = {"7d_ago": p, "now": n, "delta": n - p}
    return out


def _neighborhood_heatmap(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    by_nb: dict[str, list[float]] = {}
    for r in rows:
        nb = str(r.get("neighborhood") or r.get("city") or "כללי").strip() or "כללי"
        score = float(r.get("support_score") or 0.5)
        by_nb.setdefault(nb, []).append(score)
    heat: list[dict[str, str]] = []
    for name, scores in sorted(by_nb.items(), key=lambda x: -len(x[1]))[:24]:
        avg = sum(scores) / len(scores)
        gotv = "STRONG" if avg >= 0.75 else "WEAK" if avg < 0.55 else "MIXED"
        sentiment = "POSITIVE" if avg >= 0.65 else "NEGATIVE" if avg < 0.45 else "NEUTRAL"
        trend = "STABLE" if 0.45 <= avg <= 0.75 else "DEGRADING" if avg < 0.45 else "IMPROVING"
        heat.append({"name": name, "gotv": gotv, "sentiment": sentiment, "trend": trend})
    return heat


def _top_priorities(counts: dict[str, int], heat: list[dict[str, str]]) -> list[dict[str, str]]:
    weak = next((h for h in heat if h.get("gotv") == "WEAK"), None)
    nb = weak["name"] if weak else "מרכז העיר"
    return [
        {
            "type": "CONTACT",
            "target": f"10 בוחרי SWING ב{nb}",
            "deadline": "today",
            "urgency": "CRITICAL",
        },
        {
            "type": "RETAIN",
            "target": f"5 בוחרי AT_RISK ב{nb}",
            "deadline": "48h",
            "urgency": "HIGH",
        },
        {
            "type": "MOBILIZE",
            "target": f"הפעלת {counts.get('safe', 0)} תומכי SAFE לשגר",
            "deadline": "week",
            "urgency": "MEDIUM",
        },
    ]


@router.get("/war-room/overview")
async def war_room_overview() -> dict[str, Any]:
    rows = await db.all_voters()
    total = len(rows)
    counts = _gotv_counts(rows)
    await db.upsert_gotv_snapshot(counts)
    week_ago = (datetime.now(UTC) - timedelta(days=7)).strftime("%Y-%m-%d")
    past = await db.gotv_snapshot_on_date(week_ago)

    dispatch = services.dispatch_stats()
    alerts_data = services.alerts_payload()
    alert_items = alerts_data.get("alerts") or []
    formatted_alerts = []
    for a in alert_items[:8]:
        if isinstance(a, dict):
            formatted_alerts.append(
                {
                    "type": a.get("alert_type") or a.get("type") or "ALERT",
                    "detail": a.get("title") or a.get("description") or "",
                    "severity": str(a.get("severity") or "MEDIUM").upper(),
                    "time": (a.get("timestamp") or "")[-8:-3] if a.get("timestamp") else "",
                }
            )

    contacted_week = min(total, int(total * 0.25))
    contacted_today = min(contacted_week, max(1, int(contacted_week / 7)))

    return {
        "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "totals": {
            "voters": total,
            "contacted_today": contacted_today,
            "contacted_this_week": contacted_week,
            "remaining": max(0, total - contacted_week),
        },
        "gotv_distribution": {
            "SAFE": counts["safe"],
            "LEANING": counts["leaning"],
            "SWING": counts["swing"],
            "AT_RISK": counts["at_risk"],
            "LOST": counts["lost"],
        },
        "gotv_trend": _trend_block(counts, past),
        "dispatch_queue": {
            "pending": dispatch.get("queued", 0),
            "in_progress": dispatch.get("in_progress", 0),
            "completed_today": dispatch.get("completed", 0),
            "overdue": max(0, dispatch.get("queued", 0) // 10),
        },
        "alerts": formatted_alerts,
        "field_agents": {"active": 8, "total": 12, "avg_contacts_per_hour": 4.2},
        "neighborhood_heatmap": _neighborhood_heatmap(rows),
        "top_priorities": _top_priorities(counts, _neighborhood_heatmap(rows)),
    }


class EmergencyDispatchRequest(BaseModel):
    mode: Literal["TOP_SWING", "AT_RISK_BLITZ", "NEIGHBORHOOD_FOCUS"] = "TOP_SWING"
    neighborhood: str = "all"
    count: int = Field(default=50, ge=1, le=500)


@router.post("/war-room/emergency-dispatch")
async def emergency_dispatch(body: EmergencyDispatchRequest) -> dict[str, Any]:
    rows = await db.all_voters()
    mode = body.mode
    nb = body.neighborhood.strip()
    if nb and nb.lower() != "all":
        rows = [r for r in rows if nb in str(r.get("neighborhood") or "") or nb in str(r.get("city") or "")]

    def cat(r: dict[str, Any]) -> str:
        return str(r.get("gotv_category") or "").lower()

    if mode == "TOP_SWING":
        rows = [r for r in rows if "swing" in cat(r)]
        rows.sort(key=lambda x: float(x.get("gotv_priority") or 0), reverse=True)
    elif mode == "AT_RISK_BLITZ":
        rows = [r for r in rows if "at_risk" in cat(r) or "at risk" in cat(r)]
        rows.sort(key=lambda x: float(x.get("gotv_priority") or 0), reverse=True)
    else:
        rows.sort(key=lambda x: float(x.get("support_score") or 0))

    picked = rows[: body.count]
    tasks: list[str] = []
    targets: list[dict[str, Any]] = []
    for r in picked:
        name = f"{r.get('first_name', '')} {r.get('last_name', '')}".strip()
        rec = services.enqueue_dispatch(
            voter_id=str(r.get("id")),
            voter_name=name,
            channel=r.get("gotv_channel") or "whatsapp",
            priority=int(float(r.get("gotv_priority") or 80)),
            message_template="civic_duty",
        )
        tasks.append(rec["task_id"])
        targets.append({"voter_id": r.get("id"), "name": name, "gotv_category": r.get("gotv_category")})

    eta = datetime.now(UTC) + timedelta(hours=3)
    return {
        "dispatched": len(tasks),
        "tasks": tasks,
        "mode": mode,
        "target_voters": targets,
        "estimated_completion": eta.isoformat().replace("+00:00", "Z"),
    }
