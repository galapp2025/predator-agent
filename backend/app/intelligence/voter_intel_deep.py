"""Deep per-voter OSINT intelligence (BlackOpps v5 FINAL V2)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

from app import db

logger = logging.getLogger("blackopps.voter_intel_deep")

router = APIRouter(tags=["voter-intel-deep"])

STALE_DAYS = 7

SYSTEM_PROMPT = (
    "You are a Mossad-level intelligence analyst specializing in HUMINT and OSINT "
    "for Israeli municipal elections. Analyze voters deeply and personally. "
    "Cover social presence, topic stances, behavioral patterns, social network, "
    "communication profile, triggers, and intelligence assessment. "
    "All output in natural authentic Israeli Hebrew. Be specific to name and neighborhood. "
    "Be honest about gaps. Return ONLY valid JSON."
)


class DeepProfileRequest(BaseModel):
    voter_id: str = Field(..., min_length=1)


class BatchDeepRequest(BaseModel):
    voter_ids: list[str] = Field(default_factory=list)
    max_count: int = Field(default=50, ge=1, le=50)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_stale(last_updated: str | None) -> bool:
    ts = _parse_ts(last_updated)
    if not ts:
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return datetime.now(UTC) - ts > timedelta(days=STALE_DAYS)


def _full_name(voter: dict[str, Any]) -> str:
    return f"{voter.get('first_name') or ''} {voter.get('last_name') or ''}".strip() or "בוחר"


def _gotv(voter: dict[str, Any]) -> str:
    return str(voter.get("gotv_category") or "SWING").upper()


async def _groq_json(system: str, user: str, temperature: float = 0.45) -> dict[str, Any] | None:
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=55),
                json={
                    "model": "llama-3.3-70b-versatile",
                    "temperature": temperature,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
            ) as resp:
                if resp.status != 200:
                    logger.warning("Groq deep-intel HTTP %s", resp.status)
                    return None
                data = await resp.json()
                content = data["choices"][0]["message"]["content"]
                start = content.find("{")
                end = content.rfind("}") + 1
                if start < 0 or end <= start:
                    return None
                parsed = json.loads(content[start:end])
                return parsed if isinstance(parsed, dict) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Groq deep-intel failed: %s", exc)
        return None


def _fallback_intel(voter: dict[str, Any], *, low_osint: bool = True) -> dict[str, Any]:
    name = _full_name(voter)
    nb = voter.get("neighborhood") or "השכונה"
    gotv = _gotv(voter)
    first = voter.get("first_name") or name.split()[0]

    conf = 52 if low_osint else 68
    return {
        "social_presence": {
            "primary_platforms": [
                f"פייסבוק — קבוצת {nb}",
                "וואטסאפ — קבוצות שכונה/הורים (משוער)",
            ],
            "activity_level": "בינוני — מעט אותות OSINT ישירים במערכת",
            "posting_style": f"{first} כנראה יותר מגיב מאשר יוזם — אין מספיק פוסטים מאומתים",
            "typical_content": f"נושאי שכונה ב{nb}, שירותי עיר, יוקר מחיה",
            "tone": "זהיר, מעשי — לא מתלהם בלי עובדות",
            "best_time_to_engage": "ערב, 20:00-22:00",
        },
        "topic_stances": {
            "חינוך": {
                "stance": "חשוב מאוד",
                "support_level": 7,
                "pain_point": "כיתות צפופות ושירותי צהרון יקרים",
                "argument": "תוכנית כיתות חדשות + צהרונים מסובסדים",
            },
            "ביטחון": {
                "stance": "תומך בחיזוק ביטחון אישי",
                "support_level": 8 if gotv in ("SAFE", "LEANING") else 6,
                "pain_point": "תחושת ביטחון בערבים",
                "argument": "מצלמות + תאורה + סיורים",
            },
            "תחבורה": {
                "stance": "מתוסכל מפקקים",
                "support_level": 5,
                "pain_point": f"יציאה מ{nb} בבוקר",
                "argument": "רמזורים חכמים + נתיבי תחבורה ציבורית",
            },
            "דיור": {
                "stance": "מודאג ממחירי דיור",
                "support_level": 6,
                "pain_point": "יוקר דיור למשפחות צעירות",
                "argument": "הקלות בנייה + דיור בר-השגה",
            },
            "דת": {
                "stance": "מסורתי ללא כפייה",
                "support_level": 7,
                "argument": "שמירה על סטטוס קוו",
            },
            "כלכלה": {
                "stance": "מודאג מיוקר מחיה",
                "support_level": 5,
                "pain_point": "ארנונה + מחירים",
                "argument": "הקפאת ארנונה / הנחות למשפחות",
            },
            "קהילה": {
                "stance": "רוצה קהילה חזקה",
                "support_level": 7,
                "argument": "אירועי שכונה + מרכז קהילתי",
            },
            "איכות חיים": {
                "stance": "פארקים ותחזוקה",
                "support_level": 6,
                "pain_point": "תחזוקת רחובות וגינות",
                "argument": "שיפוץ פארקים ותאורה",
            },
        },
        "behavioral_patterns": {
            "engagement_type": "מגיב סלקטיבי — קורא הרבה, מגיב כשנוגע בו אישית",
            "decision_style": "מבוסס עובדות ומספרים — לא מתרשם מסיסמאות",
            "trust_builders": ["הוכחות מוחשיות", "המלצות מחברים בשכונה", "פגישה אישית"],
            "trust_breakers": ["הבטחות בומבסטיות", "האשמות", "פוליטיקה מלוכלכת"],
            "influence_triggers": ["ילדים וחינוך", "ארנונה ויוקר מחיה", "גאוות שכונה"],
        },
        "social_network": {
            "influencers": [f"שכנים פעילים ב{nb}", "דמויות קהילה מקומיות"],
            "influencees": ["משפחה קרובה", "2-4 שכנים בבניין"],
            "network_role": "צומת שקט — משפיע דרך שיחות אישיות",
            "estimated_reach": 6,
        },
        "communication_profile": {
            "best_tone": "ישיר, לא מתנשא, עם מספר אחד חזק. בלי סיסמאות",
            "best_channel": "וואטסאפ — הודעה אישית",
            "opening_strategy": f"לשאול שאלה על {nb}, לא לקבוע עובדה",
            "words_to_use": ["עובדות", "מספרים", "ילדים", "שכונה", "תוכנית", "קהילה"],
            "words_to_avoid": ["מהפכה", "מטורף", "הכי טוב בעולם", "אחי" if gotv == "SAFE" else "מהפכה"],
            "ideal_message_length": "4-6 משפטים. ממוקד. עם מספר אחד חזק",
        },
        "triggers": {
            "anger": "חוסר שקיפות, פגיעה בחינוך, הבטחות ריקות",
            "pride": f"הצלחת הילדים והתפתחות {nb}",
            "fear": "ירידה באיכות חינוך ובמצב הכלכלי",
            "hope": "שינוי אמיתי עם תוכנית מדידה — לא סיסמאות",
            "vote_driver": f"מי שיראה ל{first} תוכנית חינוך + מספרים ברורים ל{nb} — יקבל הקשבה אמיתית",
        },
        "intelligence_assessment": {
            "confidence_score": conf,
            "data_quality": "נמוך-בינוני — פרופיל דמוגרפי/GOTV קיים, OSINT ישיר דל",
            "intelligence_gaps": [
                "אין פוסטים מאומתים ברשתות במערכת",
                "עמדות פוליטיות ישירות לא מאומתות",
                "לא ידוע אם מכיר אישית את המועמד",
            ],
            "recommendation": f"פגישה קצרה / וואטסאפ אישי עם תוכנית חינוך ממוספרת ל{nb} — ואז לרענן מודיעין",
        },
    }


def _normalize_intel(raw: dict[str, Any], voter: dict[str, Any]) -> dict[str, Any]:
    """Merge LLM output with required structure; fill gaps from fallback."""
    base = _fallback_intel(voter, low_osint=False)
    src = raw.get("intel") if isinstance(raw.get("intel"), dict) else raw

    def merge_dict(default: dict[str, Any], overlay: Any) -> dict[str, Any]:
        if not isinstance(overlay, dict):
            return default
        out = dict(default)
        for k, v in overlay.items():
            if v is None or v == "":
                continue
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k] = {**out[k], **v}
            else:
                out[k] = v
        return out

    intel = {
        "social_presence": merge_dict(base["social_presence"], src.get("social_presence")),
        "topic_stances": merge_dict(base["topic_stances"], src.get("topic_stances")),
        "behavioral_patterns": merge_dict(base["behavioral_patterns"], src.get("behavioral_patterns")),
        "social_network": merge_dict(base["social_network"], src.get("social_network")),
        "communication_profile": merge_dict(base["communication_profile"], src.get("communication_profile")),
        "triggers": merge_dict(base["triggers"], src.get("triggers")),
        "intelligence_assessment": merge_dict(
            base["intelligence_assessment"], src.get("intelligence_assessment")
        ),
    }

    # Ensure list fields
    sp = intel["social_presence"]
    if not isinstance(sp.get("primary_platforms"), list) or not sp["primary_platforms"]:
        sp["primary_platforms"] = base["social_presence"]["primary_platforms"]

    for key in ("trust_builders", "trust_breakers", "influence_triggers"):
        bp = intel["behavioral_patterns"]
        if not isinstance(bp.get(key), list) or not bp[key]:
            bp[key] = base["behavioral_patterns"][key]

    sn = intel["social_network"]
    for key in ("influencers", "influencees"):
        if not isinstance(sn.get(key), list) or not sn[key]:
            sn[key] = base["social_network"][key]
    try:
        sn["estimated_reach"] = int(sn.get("estimated_reach") or base["social_network"]["estimated_reach"])
    except (TypeError, ValueError):
        sn["estimated_reach"] = base["social_network"]["estimated_reach"]

    cp = intel["communication_profile"]
    for key in ("words_to_use", "words_to_avoid"):
        if not isinstance(cp.get(key), list) or not cp[key]:
            cp[key] = base["communication_profile"][key]

    ia = intel["intelligence_assessment"]
    try:
        score = float(ia.get("confidence_score") or 0)
    except (TypeError, ValueError):
        score = 55
    ia["confidence_score"] = int(max(50, min(95, score)))
    if not isinstance(ia.get("intelligence_gaps"), list) or not ia["intelligence_gaps"]:
        ia["intelligence_gaps"] = base["intelligence_assessment"]["intelligence_gaps"]

    # Ensure 5+ topics
    if len(intel["topic_stances"]) < 5:
        intel["topic_stances"] = {**base["topic_stances"], **intel["topic_stances"]}

    return intel


def _response_payload(voter: dict[str, Any], intel: dict[str, Any], *, cached: bool = False) -> dict[str, Any]:
    assessment = intel.get("intelligence_assessment") or {}
    return {
        "voter_id": str(voter["id"]),
        "full_name": _full_name(voter),
        "neighborhood": voter.get("neighborhood") or "",
        "gotv_category": _gotv(voter),
        "intel": intel,
        "intelligence_score": float(assessment.get("confidence_score") or 0),
        "cached": cached,
    }


async def _build_deep_profile(voter: dict[str, Any]) -> dict[str, Any]:
    name = _full_name(voter)
    nb = voter.get("neighborhood") or "לא ידוע"
    gotv = _gotv(voter)
    psych = await db.get_psychological_profile(str(voter["id"]))
    sentiment = await db.list_sentiment_history(str(voter["id"]), limit=5)

    user_prompt = f"""בנה תיק מודיעין מלא לבוחר הבא.
שם: {name}
מזהה: {voter.get('id')}
שכונה: {nb}
עיר: {voter.get('city') or 'פתח תקווה'}
קטגוריית GOTV: {gotv}
ציון תמיכה: {voter.get('support_score')}
ערוץ מועדף: {voter.get('gotv_channel') or 'whatsapp'}
פרופיל פסיכולוגי קיים: {json.dumps(psych.get('profile_json') if psych else None, ensure_ascii=False)[:1800]}
היסטוריית סנטימנט אחרונה: {json.dumps(sentiment, ensure_ascii=False)[:800]}

החזר JSON בפורמט:
{{
  "social_presence": {{...}},
  "topic_stances": {{ "חינוך": {{"stance":"","support_level":7,"pain_point":"","argument":""}}, ... }},
  "behavioral_patterns": {{...}},
  "social_network": {{...}},
  "communication_profile": {{...}},
  "triggers": {{ "anger":"", "pride":"", "fear":"", "hope":"", "vote_driver":"" }},
  "intelligence_assessment": {{ "confidence_score": 70, "data_quality":"", "intelligence_gaps":[], "recommendation":"" }}
}}
"""
    llm = await _groq_json(SYSTEM_PROMPT, user_prompt)
    if llm:
        intel = _normalize_intel(llm, voter)
    else:
        intel = _fallback_intel(voter, low_osint=True)

    score = float((intel.get("intelligence_assessment") or {}).get("confidence_score") or 50)
    record_id = secrets.token_hex(8)
    await db.upsert_voter_intel_deep(
        {
            "id": record_id,
            "voter_id": str(voter["id"]),
            "social_presence": json.dumps(intel["social_presence"], ensure_ascii=False),
            "topic_stances": json.dumps(intel["topic_stances"], ensure_ascii=False),
            "behavioral_patterns": json.dumps(intel["behavioral_patterns"], ensure_ascii=False),
            "social_network": json.dumps(intel["social_network"], ensure_ascii=False),
            "communication_profile": json.dumps(intel["communication_profile"], ensure_ascii=False),
            "triggers": json.dumps(intel["triggers"], ensure_ascii=False),
            "intelligence_score": score,
            "last_updated": _now(),
            "osint_raw": json.dumps({"source": "groq" if llm else "fallback"}, ensure_ascii=False),
            "intel_json": json.dumps(intel, ensure_ascii=False),
        }
    )
    return _response_payload(voter, intel, cached=False)


def _row_to_payload(voter: dict[str, Any], row: dict[str, Any], *, cached: bool = True) -> dict[str, Any]:
    intel: dict[str, Any] | None = None
    raw = row.get("intel_json") or ""
    if raw:
        try:
            intel = json.loads(raw)
        except json.JSONDecodeError:
            intel = None
    if not intel:
        intel = {
            "social_presence": json.loads(row["social_presence"]) if row.get("social_presence") else {},
            "topic_stances": json.loads(row["topic_stances"]) if row.get("topic_stances") else {},
            "behavioral_patterns": json.loads(row["behavioral_patterns"]) if row.get("behavioral_patterns") else {},
            "social_network": json.loads(row["social_network"]) if row.get("social_network") else {},
            "communication_profile": json.loads(row["communication_profile"])
            if row.get("communication_profile")
            else {},
            "triggers": json.loads(row["triggers"]) if row.get("triggers") else {},
            "intelligence_assessment": {
                "confidence_score": row.get("intelligence_score") or 0,
                "data_quality": "מהמטמון",
                "intelligence_gaps": [],
                "recommendation": "",
            },
        }
    intel = _normalize_intel(intel, voter)
    payload = _response_payload(voter, intel, cached=cached)
    payload["last_updated"] = row.get("last_updated")
    return payload


async def _refresh_background(voter_id: str) -> None:
    try:
        voter = await db.get_voter(voter_id)
        if voter:
            await _build_deep_profile(voter)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Background deep refresh failed for %s: %s", voter_id, exc)


@router.post("/intel/voter/deep-profile")
async def create_deep_profile(body: DeepProfileRequest) -> dict[str, Any]:
    voter = await db.get_voter(body.voter_id)
    if not voter:
        raise HTTPException(status_code=404, detail="בוחר לא נמצא")
    return await _build_deep_profile(voter)


@router.post("/intel/voter/batch-deep")
async def batch_deep_profile(body: BatchDeepRequest) -> dict[str, Any]:
    ids = [str(x) for x in body.voter_ids if str(x).strip()][: body.max_count]
    if not ids:
        # Sample from DB
        voters, _ = await db.list_voters(limit=body.max_count, offset=0)
        ids = [str(v["id"]) for v in voters]

    sem = asyncio.Semaphore(10)
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    async def one(vid: str) -> None:
        async with sem:
            voter = await db.get_voter(vid)
            if not voter:
                errors.append({"voter_id": vid, "error": "לא נמצא"})
                return
            try:
                results.append(await _build_deep_profile(voter))
            except Exception as exc:  # noqa: BLE001
                errors.append({"voter_id": vid, "error": str(exc)})

    await asyncio.gather(*(one(vid) for vid in ids))
    return {
        "generated": len(results),
        "failed": len(errors),
        "profiles": results,
        "errors": errors,
    }


@router.get("/intel/voter/deep-profile/{voter_id}")
async def get_deep_profile(voter_id: str, background_tasks: BackgroundTasks) -> dict[str, Any]:
    voter = await db.get_voter(voter_id)
    if not voter:
        raise HTTPException(status_code=404, detail="בוחר לא נמצא")

    row = await db.get_voter_intel_deep(voter_id)
    if not row:
        return await _build_deep_profile(voter)

    payload = _row_to_payload(voter, row, cached=True)
    if _is_stale(row.get("last_updated")):
        background_tasks.add_task(_refresh_background, voter_id)
        payload["refresh_scheduled"] = True
    return payload


@router.get("/intel/voter/intel-summary")
async def intel_summary(
    neighborhood: str = Query(default="all"),
    gotv: str = Query(default="all"),
) -> dict[str, Any]:
    rows = await db.list_voter_intel_deep(limit=5000)
    voters_cache: dict[str, dict[str, Any] | None] = {}

    async def voter_of(vid: str) -> dict[str, Any] | None:
        if vid not in voters_cache:
            voters_cache[vid] = await db.get_voter(vid)
        return voters_cache[vid]

    analyzed: list[dict[str, Any]] = []
    concern_counts: dict[str, int] = {}
    trigger_counts: dict[str, int] = {}
    segments: dict[str, int] = {
        "חינוך-ממוקד": 0,
        "כלכלה-ממוקד": 0,
        "קהילה-ממוקד": 0,
        "ביטחון-ממוקד": 0,
    }
    scores: list[float] = []

    for row in rows:
        vid = str(row.get("voter_id") or "")
        voter = await voter_of(vid)
        if not voter:
            continue
        nb = voter.get("neighborhood") or ""
        g = _gotv(voter)
        if neighborhood != "all" and nb != neighborhood:
            continue
        if gotv != "all" and g != gotv.upper():
            continue

        try:
            stances = json.loads(row["topic_stances"]) if row.get("topic_stances") else {}
        except json.JSONDecodeError:
            stances = {}
        try:
            triggers = json.loads(row["triggers"]) if row.get("triggers") else {}
        except json.JSONDecodeError:
            triggers = {}

        score = float(row.get("intelligence_score") or 0)
        scores.append(score)
        analyzed.append({"voter_id": vid, "score": score})

        # Top concern = lowest support or first pain
        top_topic = "חינוך"
        lowest = 99
        for topic, data in stances.items():
            if not isinstance(data, dict):
                continue
            lvl = int(data.get("support_level") or 5)
            if data.get("pain_point") and lvl < lowest:
                lowest = lvl
                top_topic = topic
        concern_counts[top_topic] = concern_counts.get(top_topic, 0) + 1

        for key in ("anger", "pride", "hope", "vote_driver"):
            val = str(triggers.get(key) or "")
            for token in ("ילדים", "עובדות", "קהילה", "חינוך", "ארנונה", "ביטחון"):
                if token in val:
                    trigger_counts[token] = trigger_counts.get(token, 0) + 1

        if "חינוך" in top_topic:
            segments["חינוך-ממוקד"] += 1
        elif top_topic in ("כלכלה", "דיור"):
            segments["כלכלה-ממוקד"] += 1
        elif top_topic == "קהילה":
            segments["קהילה-ממוקד"] += 1
        elif top_topic == "ביטחון":
            segments["ביטחון-ממוקד"] += 1
        else:
            segments["חינוך-ממוקד"] += 1

    top_concerns = sorted(concern_counts.keys(), key=lambda k: concern_counts[k], reverse=True)[:3]
    top_triggers = sorted(trigger_counts.keys(), key=lambda k: trigger_counts[k], reverse=True)[:3]
    if not top_concerns:
        top_concerns = ["חינוך", "יוקר מחיה", "תחבורה"]
    if not top_triggers:
        top_triggers = ["ילדים", "עובדות", "קהילה"]

    avg_conf = round(sum(scores) / len(scores), 1) if scores else 0.0
    insight = (
        "בוחרי SWING רוצים מספרים + אנושיות. בלי סיסמאות — תראה תוכנית."
        if gotv.upper() == "SWING" or gotv == "all"
        else f"סגמנט {gotv}: התמקד בטריגרים המקומיים ובשפה ישירה."
    )

    return {
        "neighborhood": neighborhood,
        "gotv_filter": gotv,
        "total_analyzed": len(analyzed),
        "avg_confidence": avg_conf,
        "top_concerns": top_concerns,
        "top_triggers": top_triggers,
        "communication_insight": insight,
        "segment_breakdown": segments,
    }
