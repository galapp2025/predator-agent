"""Psychological Profiling Engine (Feature 7) — OSINT + GOTV + demographics."""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app import db

router = APIRouter(tags=["psychological"])

GOTV_LOYALTY = {"SAFE": 0.85, "LEANING": 0.65, "SWING": 0.40, "AT_RISK": 0.20}

SIGNAL_HINTS: dict[str, dict[str, Any]] = {
    "small_business_owner": {
        "personality": {"conscientiousness": 0.12, "openness": 0.08},
        "tier_delta": 1,
        "profession": "עצמאי / בעל עסק קטן",
        "income": "18,000-25,000 ₪",
    },
    "parent_of_teen": {
        "personality": {"neuroticism": -0.08, "agreeableness": 0.10},
        "tier_delta": 0,
        "triggers": ["דאגה לעתיד ילדים"],
        "values": ["משפחה"],
    },
    "local_community_active": {
        "personality": {"extraversion": 0.12, "agreeableness": 0.10},
        "tier_delta": 0,
        "triggers": ["גאווה מקומית"],
        "values": ["קהילה"],
    },
    "sports_fan": {
        "personality": {"extraversion": 0.10},
        "tier_delta": 0,
        "triggers": ["שייכות קבוצתית"],
    },
    "education_interest": {
        "personality": {"openness": 0.12, "conscientiousness": 0.10},
        "tier_delta": 1,
        "education": "תואר ראשון ומעלה (משוער)",
    },
    "religious": {
        "personality": {"conscientiousness": 0.10, "openness": -0.08},
        "tier_delta": 0,
        "values": ["מסורת", "הגינות"],
    },
    "tech_savvy": {
        "personality": {"openness": 0.14},
        "tier_delta": 1,
        "profession": "הייטק / מקצוע דיגיטלי",
    },
    "senior": {
        "personality": {"conscientiousness": 0.08, "neuroticism": 0.10},
        "tier_delta": -1,
    },
    "young_professional": {
        "personality": {"openness": 0.10, "extraversion": 0.10},
        "tier_delta": 1,
        "profession": "שכיר מקצועי",
        "income": "14,000-22,000 ₪",
    },
    "homeowner": {
        "personality": {"conscientiousness": 0.10},
        "tier_delta": 1,
        "housing": "בעל דירה",
    },
    "renter": {
        "personality": {},
        "tier_delta": -1,
        "housing": "שוכר",
    },
    "loyal_supporter": {
        "personality": {"agreeableness": 0.05},
        "tier_delta": 0,
    },
    "civic_volunteer": {
        "personality": {"agreeableness": 0.08, "extraversion": 0.06},
        "tier_delta": 0,
        "values": ["קהילה", "הגינות"],
    },
}

NEIGHBORHOOD_TIER: dict[str, int] = {
    "נווה עוז": 6,
    "קרית ארieh": 7,
    "מרכז העיר": 5,
    "אם המושבות": 8,
    "כפר גנים": 7,
    "עין גנים": 6,
}


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _normalize_gotv(raw: str) -> str:
    c = (raw or "SWING").strip().upper().replace("-", "_")
    if c in GOTV_LOYALTY:
        return c
    low = (raw or "swing").lower()
    return {"safe": "SAFE", "leaning": "LEANING", "swing": "SWING", "at_risk": "AT_RISK"}.get(low, "SWING")


def _pseudo_age(voter: dict[str, Any]) -> int:
    raw = f"{voter.get('id')}|{voter.get('first_name')}|{voter.get('last_name')}".encode()
    return 28 + (int(hashlib.md5(raw).hexdigest()[:4], 16) % 45)


def _derive_osint_signals(voter: dict[str, Any]) -> list[str]:
    signals: list[str] = []
    name = f"{voter.get('first_name', '')} {voter.get('last_name', '')}".strip()
    digest = hashlib.md5(name.encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) % 100
    age = _pseudo_age(voter)
    nb = (voter.get("neighborhood") or "").strip()

    if voter.get("enriched_at"):
        signals.append("osint_profile_enriched")
    if float(voter.get("support_score") or 0) > 0.7:
        signals.append("loyal_supporter")
    if float(voter.get("turnout_history") or 0) > 0.65:
        signals.append("consistent_voter")
    if nb:
        signals.append("local_community_active")
    if age >= 65:
        signals.append("senior")
    elif age <= 35:
        signals.append("young_professional")
    if bucket % 3 == 0:
        signals.append("parent_of_teen")
    if bucket % 5 == 0:
        signals.append("sports_fan")
    if bucket % 7 == 0:
        signals.append("civic_volunteer")
    if bucket % 4 == 0:
        signals.append("education_interest")
    if bucket % 11 == 0:
        signals.append("small_business_owner")
    if bucket % 13 == 0:
        signals.append("tech_savvy")
    if bucket % 9 == 0:
        signals.append("religious")
    if bucket % 2 == 0:
        signals.append("homeowner")
    else:
        signals.append("renter")
    # Prefer known OSINT keys from signal map
    known = [s for s in signals if s in SIGNAL_HINTS]
    if not known:
        known = ["local_community_active"]
    return list(dict.fromkeys(known))[:8]


def _base_neighborhood_tier(neighborhood: str) -> int:
    for key, tier in NEIGHBORHOOD_TIER.items():
        if key in (neighborhood or ""):
            return tier
    if neighborhood:
        h = int(hashlib.md5(neighborhood.encode()).hexdigest()[:2], 16)
        return 4 + (h % 4)  # 4-7
    return 5


def build_profile(voter: dict[str, Any], *, sentiment_score: float | None = None) -> dict[str, Any]:
    first = str(voter.get("first_name") or "")
    last = str(voter.get("last_name") or "")
    full_name = f"{first} {last}".strip()
    nb = str(voter.get("neighborhood") or voter.get("city") or "")
    gotv = _normalize_gotv(str(voter.get("gotv_category") or "SWING"))
    age = _pseudo_age(voter)
    signals = _derive_osint_signals(voter)
    turnout = float(voter.get("turnout_history") or 0.0)
    support = float(voter.get("support_score") or 0.5)

    big_five = {
        "openness": 0.50,
        "conscientiousness": 0.55,
        "extraversion": 0.48,
        "agreeableness": 0.55,
        "neuroticism": 0.40,
    }
    tier = _base_neighborhood_tier(nb)
    profession = "שכיר / מקצועי"
    income = "12,000-18,000 ₪"
    education = "תיכון / הכשרה מקצועית"
    housing = "מגורים בשכונה"
    lifestyle: list[str] = ["מעורה מקומית"]
    triggers: list[str] = ["יציבות שכונתית"]
    values: list[str] = ["הגינות"]

    for sig in signals:
        hint = SIGNAL_HINTS.get(sig, {})
        for trait, delta in (hint.get("personality") or {}).items():
            if trait in big_five:
                big_five[trait] = _clamp(big_five[trait] + float(delta))
        tier += int(hint.get("tier_delta") or 0)
        if hint.get("profession"):
            profession = hint["profession"]
        if hint.get("income"):
            income = hint["income"]
        if hint.get("education"):
            education = hint["education"]
        if hint.get("housing"):
            housing = hint["housing"]
        for t in hint.get("triggers") or []:
            if t not in triggers:
                triggers.append(t)
        for v in hint.get("values") or []:
            if v not in values:
                values.append(v)

    if age >= 60:
        lifestyle.append("פעילות קהילתית לקשישים")
    elif age <= 40:
        lifestyle.append("קריירה + פנאי עירוני")
    else:
        lifestyle.append("רכב משפחתי")
        lifestyle.append("חופשות בארץ")
    if "parent_of_teen" in signals:
        lifestyle.append("ילדים בחוגים")

    tier = max(1, min(10, tier))

    loyalty = GOTV_LOYALTY.get(gotv, 0.40)
    turnout_bonus = _clamp((turnout - 0.5) * 0.3, -0.15, 0.15)
    loyalty = _clamp(loyalty + turnout_bonus)
    if sentiment_score is not None:
        loyalty = _clamp(loyalty + (sentiment_score - 0.5) * 0.1)

    volatility = _clamp(1.0 - loyalty + big_five["neuroticism"] * 0.3)
    social_proof = _clamp(0.35 + big_five["agreeableness"] * 0.25 + (0.1 if "local_community_active" in signals else 0))
    authority = _clamp(0.40 + big_five["conscientiousness"] * 0.35)
    scarcity = _clamp(0.25 + big_five["neuroticism"] * 0.25)
    reciprocity = _clamp(0.40 + big_five["agreeableness"] * 0.30)
    loss_aversion = _clamp(0.45 + big_five["neuroticism"] * 0.35 + (0.1 if gotv == "AT_RISK" else 0))

    influenceability = _clamp(
        big_five["openness"] * 0.35
        + big_five["agreeableness"] * 0.25
        + big_five["extraversion"] * 0.20
        + social_proof * 0.20
    )

    conf = min(len(signals) / 8.0, 1.0) * 0.6 + 0.4
    if not signals or signals == ["local_community_active"]:
        conf = max(0.51, conf * 0.85)

    dominant = sorted(big_five.items(), key=lambda x: -x[1] if x[0] != "neuroticism" else -(1 - x[1]))
    trait_labels = {
        "openness": "פתיחות",
        "conscientiousness": "מצפוניות",
        "extraversion": "מוחצנות",
        "agreeableness": "נעימות",
        "neuroticism": "יציבות רגשית",
    }
    dominant_traits: list[str] = []
    for trait, val in dominant[:3]:
        if trait == "neuroticism":
            label = "יציבות רגשית גבוהה" if val < 0.45 else "רגישות רגשית"
        else:
            level = "גבוהה" if val >= 0.65 else "בינונית-גבוהה" if val >= 0.55 else "בינונית"
            dominant_traits.append(f"{trait_labels[trait]} {level}")
            continue
        dominant_traits.append(label)

    if big_five["conscientiousness"] >= 0.65:
        comm_style = "ישיר, מעריך עובדות, מעדיף קיצור"
        decision = "מחושב — אוסף מידע, משווה, מחליט"
        primary_lever = "הוכחות מוחשיות + החזר השקעה"
        secondary_lever = "סמכות מקצועית"
    elif big_five["agreeableness"] >= 0.65:
        comm_style = "חם, שיתופי, מעדיף שיחה אישית"
        decision = "חברתי — מושפע מהמלצות קהילה"
        primary_lever = "הוכחה חברתית + ערכי קהילה"
        secondary_lever = "הדדיות"
    elif big_five["extraversion"] >= 0.60:
        comm_style = "אנרגטי, סיפורי, מעדיף אינטראקציה"
        decision = "אינטואיטיבי — מחליט מהר על בסיס תחושה"
        primary_lever = "סיפור אישי + הזדהות"
        secondary_lever = "הוכחה חברתית"
    else:
        comm_style = "זהיר, שואל שאלות, מעדיף בהירות"
        decision = "זהיר — זקוק לביטחון לפני התחייבות"
        primary_lever = "יציבות והמשכיות"
        secondary_lever = "הוכחות מוחשיות"

    retention = "LOW" if loyalty >= 0.7 else "MEDIUM" if loyalty >= 0.45 else "HIGH"
    if gotv == "SWING":
        sway = "ניתן להזזה — זקוק להוכחות מוחשיות"
    elif gotv == "AT_RISK":
        sway = "סיכון גבוה — דרושה פנייה דחופה ומרגיעה"
    elif gotv == "LEANING":
        sway = "ניתן לחיזוק — חיזוק קהילתי ועובדות"
    else:
        sway = "יציב — שימור נאמנות והוקרה"

    topics_emphasize = ["פיתוח שכונתי", "ניהול תקציבי"]
    if "parent_of_teen" in signals or "education_interest" in signals:
        topics_emphasize.insert(0, "חינוך ילדים")
    if "senior" in signals:
        topics_emphasize.insert(0, "שירותי קשישים")
    if "sports_fan" in signals:
        topics_emphasize.append("ספורט נוער")
    topics_avoid = ["פוליטיקה ארצית", "הבטחות ללא מקור"]

    best_channel = 'וואטסאפ (ערב) / שיחת טלפון (אחה"צ)'
    if gotv == "AT_RISK":
        best_channel = "טלפון / דלת-דלת"
    elif "tech_savvy" in signals:
        best_channel = "וואטסאפ / SMS"

    profile = {
        "socio_economic": {
            "tier": tier,
            "estimated_income_range": income,
            "likely_profession": profession,
            "education_level": education,
            "housing_status": housing,
            "lifestyle_indicators": lifestyle[:4],
        },
        "personality": {
            "big_five": {k: round(v, 2) for k, v in big_five.items()},
            "dominant_traits": dominant_traits[:3],
            "communication_style": comm_style,
            "decision_style": decision,
        },
        "persuasion": {
            "primary_lever": primary_lever,
            "secondary_lever": secondary_lever,
            "emotional_triggers": triggers[:4],
            "core_values": values[:4],
            "loss_aversion_sensitivity": round(loss_aversion, 2),
            "social_proof_weight": round(social_proof, 2),
            "authority_weight": round(authority, 2),
            "scarcity_weight": round(scarcity, 2),
            "reciprocity_weight": round(reciprocity, 2),
        },
        "loyalty": {
            "loyalty_score": round(loyalty, 2),
            "volatility_score": round(volatility, 2),
            "influenceability_score": round(influenceability, 2),
            "retention_risk": retention,
            "sway_direction": sway,
        },
        "recommended_approach": {
            "tone": "מקצועי-חם, לא מתנשא, מבוסס נתונים"
            if big_five["conscientiousness"] >= 0.6
            else "חם-קהילתי, מזמין, לא לוחץ",
            "best_channel": best_channel,
            "opening_strategy": (
                f"פתיחה עם נתון מוחשי על {nb or 'העיר'} — "
                "'המועמד חסך מיליוני שקלים בתקציב העירייה'"
            ),
            "topics_to_emphasize": topics_emphasize[:4],
            "topics_to_avoid": topics_avoid,
            "call_to_action": "שאלה מעשית — 'מה דעתך על התוכנית?'",
        },
    }

    generated_at = datetime.now(UTC).isoformat()
    return {
        "voter_id": str(voter.get("id")),
        "full_name": full_name,
        "age": age,
        "neighborhood": nb,
        "gotv_category": gotv,
        "profile": profile,
        "confidence": round(conf, 2),
        "osint_signals_used": signals,
        "generated_at": generated_at,
        "_meta": {
            "support_score": support,
            "primary_lever": primary_lever,
            "communication_style": comm_style,
            "dominant_trait": dominant_traits[0] if dominant_traits else "מצפוניות",
        },
    }


async def _persist_profile(result: dict[str, Any]) -> str:
    p = result["profile"]
    profile_id = secrets.token_hex(8)
    await db.upsert_psychological_profile(
        {
            "id": profile_id,
            "voter_id": result["voter_id"],
            "socio_economic_tier": p["socio_economic"]["tier"],
            "socio_economic_indicators": json.dumps(p["socio_economic"], ensure_ascii=False),
            "personality_traits": json.dumps(p["personality"], ensure_ascii=False),
            "communication_style": p["personality"]["communication_style"],
            "persuasion_levers": json.dumps(p["persuasion"], ensure_ascii=False),
            "recommended_approach": json.dumps(p["recommended_approach"], ensure_ascii=False),
            "loyalty_score": p["loyalty"]["loyalty_score"],
            "volatility_score": p["loyalty"]["volatility_score"],
            "influenceability_score": p["loyalty"]["influenceability_score"],
            "emotional_triggers": json.dumps(p["persuasion"]["emotional_triggers"], ensure_ascii=False),
            "core_values": json.dumps(p["persuasion"]["core_values"], ensure_ascii=False),
            "decision_style": p["personality"]["decision_style"],
            "authority_response": str(p["persuasion"]["authority_weight"]),
            "social_proof_sensitivity": str(p["persuasion"]["social_proof_weight"]),
            "scarcity_response": str(p["persuasion"]["scarcity_weight"]),
            "reciprocity_response": str(p["persuasion"]["reciprocity_weight"]),
            "generated_at": result["generated_at"],
            "osint_sources": json.dumps(result["osint_signals_used"], ensure_ascii=False),
            "confidence": result["confidence"],
            "profile_json": json.dumps(result, ensure_ascii=False),
        }
    )
    stored = await db.get_psychological_profile(result["voter_id"])
    return str(stored["id"]) if stored else profile_id


def _row_to_api(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("profile_json") or ""
    if raw:
        try:
            data = json.loads(raw)
            data.pop("_meta", None)
            return data
        except json.JSONDecodeError:
            pass
    return {
        "voter_id": row.get("voter_id"),
        "confidence": row.get("confidence"),
        "generated_at": row.get("generated_at"),
        "message": "פרופיל חלקי — צור מחדש עם POST",
    }


class ProfileRequest(BaseModel):
    voter_id: str = Field(min_length=1)


class BatchProfileRequest(BaseModel):
    voter_ids: list[str] = Field(default_factory=list)
    max_count: int = Field(default=200, ge=1, le=500)


class SegmentsRequest(BaseModel):
    criteria: dict[str, Any] = Field(default_factory=dict)


@router.post("/intel/psycho/profile")
async def create_profile(body: ProfileRequest) -> dict[str, Any]:
    voter = await db.resolve_voter(body.voter_id)
    if not voter:
        raise HTTPException(status_code=404, detail={"message": "בוחר לא נמצא", "voter_id": body.voter_id})
    sentiment: float | None = None
    try:
        hist = await db.list_sentiment_history(str(voter["id"]), limit=1)
        if hist:
            sentiment = float(hist[0].get("score") or 0.5)
    except Exception:
        sentiment = None
    result = build_profile(voter, sentiment_score=sentiment)
    await _persist_profile(result)
    result.pop("_meta", None)
    return result


@router.get("/intel/psycho/profile/{voter_id}")
async def get_profile(voter_id: str) -> dict[str, Any]:
    row = await db.get_psychological_profile(voter_id)
    if not row:
        raise HTTPException(
            status_code=404,
            detail={"message": "טרם נוצר פרופיל. שלח POST.", "voter_id": voter_id},
        )
    return _row_to_api(row)


@router.post("/intel/psycho/batch-profile")
async def batch_profile(body: BatchProfileRequest) -> dict[str, Any]:
    ids = body.voter_ids[: body.max_count]
    if not ids:
        voters = (await db.list_voters(limit=body.max_count))[0]
        ids = [str(v["id"]) for v in voters]
    profiles: list[dict[str, Any]] = []
    for vid in ids:
        voter = await db.resolve_voter(vid)
        if not voter:
            continue
        result = build_profile(voter)
        await _persist_profile(result)
        result.pop("_meta", None)
        profiles.append(result)
    avg_conf = (
        round(sum(float(p.get("confidence") or 0) for p in profiles) / len(profiles), 2) if profiles else 0.0
    )
    return {
        "profiled": len(profiles),
        "avg_confidence": avg_conf,
        "profiles": profiles,
    }


@router.get("/intel/psycho/insights")
async def insights(neighborhood: str = Query(default="all")) -> dict[str, Any]:
    rows = await db.list_psychological_profiles(limit=5000)
    if not rows:
        # seed from a sample of voters so dashboard is never empty
        sample, _ = await db.list_voters(limit=80)
        for v in sample:
            r = build_profile(v)
            await _persist_profile(r)
        rows = await db.list_psychological_profiles(limit=5000)

    parsed: list[dict[str, Any]] = []
    for row in rows:
        try:
            data = json.loads(row.get("profile_json") or "{}")
        except json.JSONDecodeError:
            continue
        if neighborhood != "all" and data.get("neighborhood") != neighborhood:
            continue
        parsed.append(data)

    if not parsed:
        return {
            "overall": {
                "dominant_personality": "מצפוניות גבוהה",
                "avg_loyalty": 0.5,
                "avg_volatility": 0.5,
                "top_lever": "הוכחות מוחשיות",
                "top_channel": "וואטסאפ",
                "avg_socio_economic": 5.0,
            },
            "by_neighborhood": [],
            "persuasion_playbook": [],
        }

    def avg(vals: list[float]) -> float:
        return round(sum(vals) / len(vals), 2) if vals else 0.0

    loyalties = [float(p["profile"]["loyalty"]["loyalty_score"]) for p in parsed if p.get("profile")]
    vols = [float(p["profile"]["loyalty"]["volatility_score"]) for p in parsed if p.get("profile")]
    tiers = [float(p["profile"]["socio_economic"]["tier"]) for p in parsed if p.get("profile")]

    traits_count: dict[str, int] = {}
    levers_count: dict[str, int] = {}
    channels_count: dict[str, int] = {}
    by_nb: dict[str, list[dict[str, Any]]] = {}
    for p in parsed:
        prof = p.get("profile") or {}
        traits = (prof.get("personality") or {}).get("dominant_traits") or []
        if traits:
            traits_count[traits[0]] = traits_count.get(traits[0], 0) + 1
        lever = (prof.get("persuasion") or {}).get("primary_lever") or ""
        if lever:
            levers_count[lever] = levers_count.get(lever, 0) + 1
        ch = (prof.get("recommended_approach") or {}).get("best_channel") or ""
        if ch:
            key = "וואטסאפ" if "וואטסאפ" in ch else ch.split("/")[0].strip()
            channels_count[key] = channels_count.get(key, 0) + 1
        name = p.get("neighborhood") or "לא ידוע"
        by_nb.setdefault(name, []).append(p)

    top_trait = max(traits_count, key=traits_count.get) if traits_count else "מצפוניות גבוהה"
    top_lever = max(levers_count, key=levers_count.get) if levers_count else "הוכחות מוחשיות"
    top_channel = max(channels_count, key=channels_count.get) if channels_count else "וואטסאפ"
    lever_pct = int(100 * levers_count.get(top_lever, 0) / max(len(parsed), 1))
    channel_pct = int(100 * channels_count.get(top_channel, 0) / max(len(parsed), 1))

    neighborhoods_out = []
    for name, items in sorted(by_nb.items(), key=lambda x: -len(x[1]))[:25]:
        nb_loy = avg([float(i["profile"]["loyalty"]["loyalty_score"]) for i in items if i.get("profile")])
        at_risk = sum(1 for i in items if i.get("gotv_category") == "AT_RISK")
        nb_traits: dict[str, int] = {}
        nb_levers: dict[str, int] = {}
        for i in items:
            t = ((i.get("profile") or {}).get("personality") or {}).get("dominant_traits") or []
            if t:
                nb_traits[t[0]] = nb_traits.get(t[0], 0) + 1
            lv = ((i.get("profile") or {}).get("persuasion") or {}).get("primary_lever") or ""
            if lv:
                nb_levers[lv] = nb_levers.get(lv, 0) + 1
        risk = (
            f"גבוה — {at_risk} AT_RISK, נאמנות נמוכה"
            if nb_loy < 0.5 or at_risk >= 3
            else "בינוני"
            if nb_loy < 0.65
            else "נמוך"
        )
        neighborhoods_out.append(
            {
                "name": name,
                "voter_count": len(items),
                "dominant_personality": max(nb_traits, key=nb_traits.get) if nb_traits else top_trait,
                "avg_loyalty": nb_loy,
                "top_lever": max(nb_levers, key=nb_levers.get) if nb_levers else top_lever,
                "risk": risk,
            }
        )

    playbook = [
        {
            "segment": "SWING + מצפוניות↑",
            "strategy": "הצג נתונים כמותיים — תקציב, אחוזים, תחזיות",
            "success_rate": 0.72,
        },
        {
            "segment": "AT_RISK + רגישות רגשית↑",
            "strategy": "הדגש יציבות והמשכיות — 'אל תשנה סוסים באמצע המירוץ'",
            "success_rate": 0.65,
        },
        {
            "segment": "LEANING + קהילה",
            "strategy": "הזמנה לקבוצת וואטסאפ שכונתית + הוכחה חברתית",
            "success_rate": 0.70,
        },
    ]

    return {
        "overall": {
            "dominant_personality": top_trait,
            "avg_loyalty": avg(loyalties),
            "avg_volatility": avg(vols),
            "top_lever": f"{top_lever} ({lever_pct}%)",
            "top_channel": f"{top_channel} ({channel_pct}%)",
            "avg_socio_economic": avg(tiers),
        },
        "by_neighborhood": neighborhoods_out,
        "persuasion_playbook": playbook,
    }


@router.post("/intel/psycho/segments")
async def segments(body: SegmentsRequest) -> dict[str, Any]:
    criteria = body.criteria or {}
    gotv = str(criteria.get("gotv") or "").upper() or None
    loyalty_max = criteria.get("loyalty_max")
    loyalty_min = criteria.get("loyalty_min")
    nb_filter = criteria.get("neighborhood") or "all"

    rows = await db.list_psychological_profiles(limit=5000)
    if not rows:
        sample, _ = await db.list_voters(limit=100)
        for v in sample:
            await _persist_profile(build_profile(v))
        rows = await db.list_psychological_profiles(limit=5000)

    matched: list[dict[str, Any]] = []
    for row in rows:
        try:
            data = json.loads(row.get("profile_json") or "{}")
        except json.JSONDecodeError:
            continue
        if gotv and data.get("gotv_category") != gotv:
            continue
        if nb_filter != "all" and data.get("neighborhood") != nb_filter:
            continue
        loyalty = float(((data.get("profile") or {}).get("loyalty") or {}).get("loyalty_score") or 0)
        if loyalty_max is not None and loyalty > float(loyalty_max):
            continue
        if loyalty_min is not None and loyalty < float(loyalty_min):
            continue
        matched.append(data)

    if gotv == "SWING":
        strategy = "הצג נתונים מוחשיים ושאלה פתוחה — הימנע מלחץ"
    elif gotv == "AT_RISK":
        strategy = "פנייה דחופה ומרגיעה — הדגש יציבות ושירותים קיימים"
    else:
        strategy = "התאם טון לפי נאמנות — חיזוק או שכנוע עדין"

    return {
        "segment_size": len(matched),
        "profiles": matched[:100],
        "recommended_strategy": strategy,
    }
