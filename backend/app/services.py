"""Business logic for BlackOpps FastAPI — keep main.py routing-only."""

from __future__ import annotations

import hashlib
import logging
import secrets
from collections import Counter
from datetime import UTC, datetime
from typing import Any, BinaryIO

import openpyxl

from app import db
from app.intelligence.api_integration import get_pipeline, pipeline_summary, profile_to_dict
from app.intelligence.gotv import GOTVPredictor, GOTVProfile, VoterCategory, gotv_battleplan
from app.intelligence.opposition import OppositionResearch, comparison_to_dict
from app.intelligence.pdf_generator import generate_briefing_pdf
from app.intelligence.scoring import InfluenceProfile, InfluenceTier
from app.schemas import VoterCreate

logger = logging.getLogger("blackopps.services")

_predictor = GOTVPredictor()
_dispatch_queue: list[dict[str, Any]] = []

HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "first_name": ("first_name", "firstname", "שם פרטי", "פרטי", "first"),
    "last_name": ("last_name", "lastname", "שם משפחה", "משפחה", "last"),
    "city": ("city", "ישוב", "עיר", "town"),
    "neighborhood": ("neighborhood", "שכונה", "רחוב", "street", "address"),
    "phone": ("phone", "טלפון", "מס טלפון 1", "mobile", "cell"),
    "email": ("email", "מייל", "e-mail"),
}

MESSAGE_TEMPLATES: dict[str, str] = {
    "civic_duty": "היום יום הבחירות — הצבעתך חשובה לדמוקרטיה המקומית.",
    "community_pride": "הקהילה שלנו צריכה אותך בקלפי — בוא להיות חלק מהשינוי.",
    "fear_of_loss": "כל קול קובע. בלי ההשתתפות שלך — הקול שלנו עלול להיחלש.",
    "personal_benefit": "יש לך הזדמנות להשפיע על השירותים והעתיד בשכונה שלך.",
}


def _normalize_header(value: Any) -> str:
    return str(value or "").strip().lower()


def _map_headers(headers: list[Any]) -> dict[str, int]:
    normalized = [_normalize_header(h) for h in headers]
    mapping: dict[str, int] = {}
    for field, aliases in HEADER_ALIASES.items():
        alias_set = {a.lower() for a in aliases}
        for idx, header in enumerate(normalized):
            if header in alias_set:
                mapping[field] = idx
                break
    return mapping


def influence_from_scores(
    name: str,
    support_score: float = 0.5,
    turnout_history: float = 0.55,
) -> InfluenceProfile:
    """Build a lightweight InfluenceProfile from GOTV-style numeric inputs."""
    support = max(0.0, min(1.0, float(support_score)))
    turnout = max(0.0, min(1.0, float(turnout_history)))
    political = round(support * 100, 1)
    voter = round(turnout * 100, 1)
    community = round((support * 0.55 + turnout * 0.45) * 100, 1)
    financial = round(max(5.0, support * 40 + 10), 1)
    composite = round(political * 0.3 + community * 0.25 + voter * 0.25 + financial * 0.2, 1)
    if composite >= 85:
        tier = InfluenceTier.CRITICAL
    elif composite >= 70:
        tier = InfluenceTier.HIGH
    elif composite >= 50:
        tier = InfluenceTier.MODERATE
    elif composite >= 30:
        tier = InfluenceTier.LOW
    else:
        tier = InfluenceTier.NEGLIGIBLE
    return InfluenceProfile(
        name=name,
        political_capital=political,
        community_influence=community,
        voter_reliability=voter,
        financial_leverage=financial,
        composite_score=composite,
        tier=tier,
        confidence=0.55,
        recommendation="GOTV synthetic profile — run OSINT enrich for higher confidence",
        engagement_strategy="Contact via optimal GOTV channel",
    )


def voting_history_from_turnout(turnout_history: float) -> dict[str, Any]:
    t = max(0.0, min(1.0, float(turnout_history)))
    if t >= 0.8:
        consistency = "always"
    elif t >= 0.55:
        consistency = "usually"
    elif t >= 0.35:
        consistency = "sometimes"
    elif t >= 0.15:
        consistency = "rarely"
    else:
        consistency = "never"
    years = {"always": 15, "usually": 10, "sometimes": 5, "rarely": 3, "never": 1}
    voted_n = {"always": 5, "usually": 4, "sometimes": 3, "rarely": 1, "never": 0}[consistency]
    elections = [{"election": f"202{2 - i}", "voted": i < voted_n} for i in range(5)]
    return {
        "consistency": consistency,
        "years_registered": years[consistency],
        "recent_elections": elections,
    }


def normalize_analyze_profile(raw: dict[str, Any]) -> dict[str, Any]:
    scores = raw.get("scores") or {}
    evidence = raw.get("evidence")
    if isinstance(evidence, dict):
        evidence_list = [str(k) for k in evidence.keys()]
    else:
        evidence_list = list(evidence or [])
    tier = raw.get("tier", "")
    tier_str = tier.value if hasattr(tier, "value") else str(tier)
    return {
        "name": raw.get("name"),
        "scores": {
            "political": scores.get("political", scores.get("political_capital", 0)),
            "community": scores.get("community", scores.get("community_influence", 0)),
            "voter": scores.get("voter", scores.get("voter_reliability", 0)),
            "financial": scores.get("financial", scores.get("financial_leverage", 0)),
            "composite": scores.get("composite", 0),
            **scores,
        },
        "tier": tier_str.upper() if tier_str else "UNKNOWN",
        "confidence": raw.get("confidence", 0),
        "recommendation": raw.get("recommendation", ""),
        "engagement_strategy": raw.get("engagement_strategy", ""),
        "risks": raw.get("risk_factors") or raw.get("risks") or [],
        "opportunities": raw.get("opportunities") or [],
        "evidence": evidence_list,
        "sources": raw.get("sources") or [],
    }


def gotv_profile_to_dict(profile: GOTVProfile) -> dict[str, Any]:
    category = profile.category.value if isinstance(profile.category, VoterCategory) else str(profile.category)
    channel = (
        profile.optimal_channel.value
        if hasattr(profile.optimal_channel, "value")
        else str(profile.optimal_channel)
    )
    return {
        "name": profile.name,
        "category": category.upper(),
        "category_confidence": profile.category_confidence,
        "turnout_probability": profile.turnout_probability,
        "persuasion_score": profile.persuasion_score,
        "priority_score": profile.priority_score,
        "optimal_channel": channel,
        "contact_frequency": profile.contact_frequency,
        "messaging_frame": profile.messaging_frame,
        "recommended_action": profile.recommended_action,
        "dropout_risk": profile.dropout_risk,
        "competitor_risk": profile.competitor_risk,
    }


def classify_batch(items: list[dict[str, Any]]) -> list[GOTVProfile]:
    """Batch GOTV classification — predictor.predict per voter (no N+1 OSINT)."""
    results: list[GOTVProfile] = []
    for item in items:
        name = str(item.get("name") or "").strip()
        if not name:
            first = str(item.get("first_name") or "").strip()
            last = str(item.get("last_name") or "").strip()
            name = f"{first} {last}".strip()
        if not name:
            continue
        support = float(item.get("support_score", 0.5) or 0.5)
        turnout = float(item.get("turnout_history", 0.55) or 0.55)
        influence = influence_from_scores(name, support, turnout)
        history = voting_history_from_turnout(turnout)
        results.append(_predictor.predict(name, influence, history))
    return sorted(results, key=lambda p: p.priority_score, reverse=True)


def battle_plan_payload(profiles: list[GOTVProfile]) -> dict[str, Any]:
    categories = Counter(p.category.value for p in profiles)
    battle = gotv_battleplan(profiles)
    channel_counter: Counter[str] = Counter()
    for p in profiles:
        ch = p.optimal_channel.value if hasattr(p.optimal_channel, "value") else str(p.optimal_channel)
        channel_counter[ch] += 1
    top_swing = [
        gotv_profile_to_dict(p)
        for p in profiles
        if p.category == VoterCategory.SWING
    ][:20]
    return {
        "classified": len(profiles),
        "categories": {
            "safe": categories.get("safe", 0),
            "leaning": categories.get("leaning", 0),
            "swing": categories.get("swing", 0),
            "at_risk": categories.get("at_risk", 0),
            "lost": categories.get("lost", 0),
        },
        "battle_plan": {
            "field_ops": (battle.get("resource_allocation") or {}).get("recommended_field_ops", 0),
            "channels": dict(channel_counter),
            "top_swing": top_swing,
            "top_priority": battle.get("top_10_priority", []),
            "resource_allocation": battle.get("resource_allocation", {}),
        },
        "voters": [gotv_profile_to_dict(p) for p in profiles],
        "battleplan": battle,
    }


async def persist_gotv(profiles: list[GOTVProfile], name_to_id: dict[str, str]) -> None:
    now = datetime.now(UTC).isoformat()
    for profile in profiles:
        voter_id = name_to_id.get(profile.name)
        if not voter_id:
            continue
        await db.update_voter(
            voter_id,
            {
                "gotv_category": profile.category.value,
                "gotv_priority": int(round(profile.priority_score)),
                "gotv_channel": profile.optimal_channel.value
                if hasattr(profile.optimal_channel, "value")
                else str(profile.optimal_channel),
                "gotv_frequency": profile.contact_frequency,
                "gotv_message": profile.messaging_frame,
                "enriched_at": now,
            },
        )


async def classify_db_voters() -> dict[str, Any]:
    rows = await db.all_voters()
    items = [
        {
            "name": f"{r['first_name']} {r['last_name']}".strip(),
            "support_score": r.get("support_score") or 0.5,
            "turnout_history": r.get("turnout_history") or 0.55,
        }
        for r in rows
    ]
    profiles = classify_batch(items)
    name_to_id = {f"{r['first_name']} {r['last_name']}".strip(): r["id"] for r in rows}
    await persist_gotv(profiles, name_to_id)
    return battle_plan_payload(profiles)


async def classify_request_voters(
    *,
    voters: list[dict[str, Any]] | None = None,
    names: list[str] | None = None,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    if voters:
        items.extend(voters)
    elif names:
        items.extend({"name": n, "support_score": 0.5, "turnout_history": 0.55} for n in names if n.strip())
    else:
        return await classify_db_voters()
    profiles = classify_batch(items)
    return battle_plan_payload(profiles)


async def create_voter(payload: VoterCreate) -> dict[str, Any]:
    existing = await db.find_by_name(payload.first_name, payload.last_name)
    if existing:
        return existing
    voter_id = secrets.token_hex(8)
    return await db.insert_voter(
        {
            "id": voter_id,
            "first_name": payload.first_name.strip(),
            "last_name": payload.last_name.strip(),
            "city": payload.city or "",
            "neighborhood": payload.neighborhood or "",
            "phone": payload.phone or "",
            "email": payload.email or "",
            "support_score": payload.support_score,
            "turnout_history": payload.turnout_history,
        }
    )


async def import_excel(file_obj: BinaryIO) -> dict[str, Any]:
    wb = openpyxl.load_workbook(file_obj, read_only=True, data_only=True)
    ws = wb.active
    rows_iter = ws.iter_rows(values_only=True)
    try:
        header_row = next(rows_iter)
    except StopIteration as exc:
        raise ValueError("Excel file is empty") from exc
    mapping = _map_headers(list(header_row))
    if "first_name" not in mapping or "last_name" not in mapping:
        # fallback: first two columns
        mapping.setdefault("first_name", 0)
        mapping.setdefault("last_name", 1)

    imported = 0
    duplicates = 0
    for row in rows_iter:
        if not row:
            continue

        def cell(field: str) -> str:
            idx = mapping.get(field)
            if idx is None or idx >= len(row):
                return ""
            return str(row[idx] or "").strip()

        first = cell("first_name")
        last = cell("last_name")
        if not first or not last:
            continue
        if await db.find_by_name(first, last):
            duplicates += 1
            continue
        await db.insert_voter(
            {
                "id": hashlib.sha256(f"{first}:{last}:{cell('phone')}".encode()).hexdigest()[:16],
                "first_name": first,
                "last_name": last,
                "city": cell("city"),
                "neighborhood": cell("neighborhood"),
                "phone": cell("phone")[:32],
                "email": cell("email"),
                "support_score": 0.5,
                "turnout_history": 0.55,
            }
        )
        imported += 1

    wb.close()
    gotv = await classify_db_voters()
    return {
        "imported": imported,
        "duplicates": duplicates,
        "total": imported + duplicates,
        "classified": gotv.get("classified", 0),
        "categories": gotv.get("categories", {}),
    }


async def enrich_names(names: list[str], location: str = "", jurisdiction: str = "il") -> dict[str, Any]:
    pipeline = get_pipeline()
    cleaned = [n.strip() for n in names if n and str(n).strip()]
    if not cleaned:
        raise ValueError("No names provided")
    profiles = await pipeline.enrich(cleaned, location=location, jurisdiction=jurisdiction)
    return {
        "profiles": [normalize_analyze_profile(profile_to_dict(p)) for p in profiles],
        "summary": pipeline_summary(pipeline),
    }


async def enrich_voter(voter_id: str) -> dict[str, Any]:
    voter = await db.get_voter(voter_id)
    if not voter:
        raise LookupError(f"Voter '{voter_id}' not found")
    name = f"{voter['first_name']} {voter['last_name']}".strip()
    result = await enrich_names([name], location=voter.get("city") or "")
    profile = (result.get("profiles") or [None])[0]
    await db.update_voter(voter_id, {"enriched_at": datetime.now(UTC).isoformat()})
    return {"voter_id": voter_id, "name": name, "profile": profile}


async def predict_voter(name: str, support_score: float, turnout_history: float) -> dict[str, Any]:
    profiles = classify_batch(
        [{"name": name, "support_score": support_score, "turnout_history": turnout_history}]
    )
    if not profiles:
        raise ValueError("Prediction failed")
    return gotv_profile_to_dict(profiles[0])


async def compare_candidates(name_a: str, name_b: str, location: str = "", jurisdiction: str = "il") -> dict[str, Any]:
    pipeline = get_pipeline()
    research = OppositionResearch(pipeline)
    result = await research.compare(name_a, name_b, location=location, jurisdiction=jurisdiction)
    return comparison_to_dict(result)


async def briefing_json(name: str) -> dict[str, Any]:
    pipeline = get_pipeline()
    if not pipeline.get_profile(name):
        await pipeline.enrich([name])
    return pipeline.generate_briefing(name)


async def briefing_pdf_bytes(name: str) -> bytes:
    pipeline = get_pipeline()
    if not pipeline.get_profile(name):
        await pipeline.enrich([name])
    briefing = pipeline.generate_briefing(name)
    if briefing.get("error"):
        raise LookupError(briefing["error"])
    return generate_briefing_pdf(name, briefing, pipeline=pipeline)


def enqueue_dispatch(
    *,
    voter_id: str | None,
    voter_name: str | None,
    channel: str,
    priority: int,
    message: str,
    message_template: str | None,
) -> dict[str, Any]:
    body = (message or "").strip()
    if not body and message_template:
        body = MESSAGE_TEMPLATES.get(message_template, message_template)
    if not body:
        body = "תזכורת הצבעה — נשמח לראותך בקלפי."
    message_id = f"MSG-{int(datetime.now(UTC).timestamp() * 1000)}-{secrets.token_hex(3)}"
    queued_at = datetime.now(UTC).isoformat()
    record = {
        "message_id": message_id,
        "task_id": message_id,
        "status": "queued",
        "channel": channel or "WhatsApp",
        "priority": priority,
        "voter_id": voter_id,
        "voter_name": voter_name,
        "message": body,
        "queued_at": queued_at,
    }
    _dispatch_queue.append(record)
    return record


def dispatch_stats() -> dict[str, Any]:
    queued = sum(1 for r in _dispatch_queue if r.get("status") == "queued")
    in_progress = sum(1 for r in _dispatch_queue if r.get("status") == "in_progress")
    completed = sum(1 for r in _dispatch_queue if r.get("status") == "completed")
    failed = sum(1 for r in _dispatch_queue if r.get("status") == "failed")
    return {
        "queued": queued,
        "in_progress": in_progress,
        "completed": completed,
        "failed": failed,
        "agents_active": 1 if queued or in_progress else 0,
        "queue": "blackopps:dispatch:queue",
        "length": queued,
    }


def alerts_payload(severity: str | None = None) -> dict[str, Any]:
    pipeline = get_pipeline()
    alerts = pipeline.get_alerts(severity)
    summary = pipeline.alert_manager.summary()
    return {"alerts": alerts, "summary": summary, "total": len(alerts)}


def network_payload(name: str, depth: int = 2) -> dict[str, Any]:
    pipeline = get_pipeline()
    cluster = pipeline.get_network_cluster(name, depth)
    return {
        **cluster,
        "hubs": pipeline.get_hubs(),
        "summary": pipeline.get_network_summary(),
    }


def timeline_payload(name: str) -> dict[str, Any]:
    pipeline = get_pipeline()
    return {"name": name, "timeline": pipeline.get_timeline(name)}
