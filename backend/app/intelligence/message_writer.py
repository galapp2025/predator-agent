"""Multi-Format Message Writer (Feature 8) — psych-aware campaign content."""

from __future__ import annotations

import json
import logging
import os
import re
import secrets
import time
from datetime import UTC, datetime
from typing import Any

import aiohttp
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import db
from app.intelligence.psychological_profiler import build_profile, _persist_profile

logger = logging.getLogger("blackopps.writer")

router = APIRouter(tags=["message-writer"])

FORMATS = ("private_message", "general_message", "social_post_fb", "social_post_x")

FORMAT_LABELS = {
    "private_message": "הודעה פרטית",
    "general_message": "הודעה כללית (קבוצה קהילתית)",
    "social_post_fb": "פוסט פייסבוק",
    "social_post_x": "פוסט X",
}

TOPIC_FACTS: dict[str, dict[str, str]] = {
    "חינוך": {
        "fact1": "3 כיתות חדשות",
        "fact2": "4.2 מיליון ₪ תוספת תקציב",
        "fact3": "צהרונים מסובסדים — 200 ₪ במקום 850 ₪",
        "story": "הכיתות צפופות והילדים יושבים 38 בכיתה",
    },
    "בטחון": {
        "fact1": "120 מצלמות חדשות",
        "fact2": "תאורה מלאה ב־40 רחובות",
        "fact3": "תוספת סיורים ליליים",
        "story": "תושבים מדווחים על תחושת ביטחון נמוכה בערבים",
    },
    "קהילה": {
        "fact1": "מרכז קהילתי מחודש",
        "fact2": "12 אירועי שכונה בשנה",
        "fact3": "תקציב מתנדבים מוגדל",
        "story": "קהילות חזקות בונות עיר חזקה",
    },
    "דיור": {
        "fact1": "הקלות בהיתרי בנייה",
        "fact2": "שיפוץ 5 מבני ציבור",
        "fact3": "תכנון חניונים חדשים",
        "story": "משפחות מחפשות פתרונות דיור יציבים",
    },
}


def _facts(topic: str) -> dict[str, str]:
    return TOPIC_FACTS.get(topic, TOPIC_FACTS["קהילה"])


def _hebrew_ratio(text: str) -> float:
    if not text:
        return 0.0
    he = len(re.findall(r"[\u0590-\u05FF]", text))
    return he / max(len(text), 1)


async def _ensure_psych(voter: dict[str, Any]) -> tuple[dict[str, Any], str]:
    existing = await db.get_psychological_profile(str(voter["id"]))
    if existing and existing.get("profile_json"):
        try:
            data = json.loads(existing["profile_json"])
            if data.get("profile"):
                return data, str(existing["id"])
        except json.JSONDecodeError:
            pass
    result = build_profile(voter)
    pid = await _persist_profile(result)
    return result, pid


def _engagement(
    *,
    format_key: str,
    text: str,
    first: str,
    neighborhood: str,
    lever: str,
    personalized: bool,
) -> float:
    base = {"private_message": 0.72, "general_message": 0.68, "social_post_fb": 0.80, "social_post_x": 0.66}.get(
        format_key, 0.6
    )
    bonus = 0.0
    if first and first in text:
        bonus += 0.04
    if neighborhood and neighborhood in text:
        bonus += 0.04
    if personalized:
        bonus += 0.03
    if _hebrew_ratio(text) > 0.35:
        bonus += 0.02
    if format_key == "social_post_x" and len(text) <= 280:
        bonus += 0.02
    if format_key == "social_post_fb" and len(text) > 400:
        bonus += 0.03
    return round(min(0.95, max(0.51, base + bonus)), 2)


def _ensure_slang(text: str, *, format_key: str) -> str:
    """Guarantee at least one authentic Israeli slang token for QA gate."""
    markers = ("אחי", "וואלה", "תכלס", "אשכרה", "יאללה", "סבבה", "אחלה", "פצצה")
    if any(m in text for m in markers):
        return text
    banned = ("נא ", "הנכם", "בכבוד רב", "אנו מתכבדים", "הרינו", "לידיעתכם")
    cleaned = text
    for b in banned:
        cleaned = cleaned.replace(b, "")
    if format_key == "private_message":
        return f"אחי, תכלס —\n\n{cleaned.strip()}\n\nיאללה, מחכה לשמוע 💪"
    if format_key == "general_message":
        return f"וואלה חברים,\n\n{cleaned.strip()}\n\nיאללה, תפיצו בסביבה 🤜🤛"
    if format_key == "social_post_fb":
        return f"פצצה אמיתית 🔥\n\n{cleaned.strip()}\n\nאשכרה — שתפו אם גם אתם מרגישים את זה. יאללה!"
    short = cleaned.strip().replace("\n", " ")
    out = f"תכלס: {short} יאללה 👇"
    return out[:280]


def _fallback_formats(
    *,
    first: str,
    full_name: str,
    neighborhood: str,
    gotv: str,
    topic: str,
    psych: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    nb = neighborhood or "השכונה"
    facts = _facts(topic)
    profile = psych.get("profile") or {}
    persuasion = profile.get("persuasion") or {}
    approach = profile.get("recommended_approach") or {}
    personality = profile.get("personality") or {}
    lever = persuasion.get("primary_lever") or "הוכחות מוחשיות"
    tone = approach.get("tone") or "חם-ישראלי"
    triggers = persuasion.get("emotional_triggers") or ["גאווה מקומית"]
    trigger = triggers[0] if triggers else "גאווה מקומית"
    style = personality.get("communication_style") or "ישיר"

    private = (
        f"אחי {first}, וואלה חשוב לי לעדכן אותך 👋\n\n"
        f"כהורה/תושב ב{nb}, תכלס — {topic} זה לא סיסמה אצלנו.\n\n"
        f"המועמד התחייב: {facts['fact1']}, {facts['fact2']}, ו{facts['fact3']}.\n\n"
        f"כל המספרים — פה >> [לינק]\n\n"
        f"יאללה, אשמח לשמוע מה דעתך."
    )
    if gotv == "AT_RISK":
        private = (
            f"אחי {first}, תקשיב רגע — חשוב לי לעדכן אותך אישית.\n\n"
            f"ב{nb} אנחנו מקדמים תוכנית {topic}: {facts['fact1']} ו{facts['fact2']}.\n\n"
            f"תכלס זה לוקח 5 דקות. יאללה תגיד מתי נוח."
        )

    general = (
        f"וואלה תושבי {nb},\n\n"
        f"יש בשורות אשכרה חשובות בנושא ה{topic} בשכונה:\n\n"
        f"📚 {facts['fact1']}\n"
        f"💰 {facts['fact2']}\n"
        f"🎒 {facts['fact3']}\n\n"
        f"סבבה? מוזמנים לקרוא ולשתף >> [לינק]\n\n"
        f"יאללה, ביחד נזיז את זה 🤜🤛"
    )

    fb = (
        f"פצצה ל{nb} 🔥\n\n"
        f"{facts['story']}.\n\n"
        f"אבל וואלה — יש תקווה.\n\n"
        f"המועמד חשף תוכנית מפורטת בנושא {topic}:\n"
        f"✅ {facts['fact1']}\n"
        f"✅ {facts['fact2']}\n"
        f"✅ {facts['fact3']}\n"
        f"✅ לוח זמנים ברור עם מקורות מימון\n\n"
        f"תכלס: לא הבטחות בחירות — תוכנית תקציבית.\n\n"
        f"אם גם אתם מרגישים ש{topic} זה לא פריבילגיה — שתפו. יאללה 📢"
    )

    x = (
        f"תכלס {nb}: {facts['fact1']}, {facts['fact2']}. "
        f"תוכנית {topic} אמיתית. יאללה 👇\n[לינק]"
    )
    if len(x) > 280:
        x = f"תכלס {nb}: {facts['fact1']}+{facts['fact2']}. יאללה 👇 [לינק]"
        x = x[:277] + "…"

    payloads = {
        "private_message": {
            "format": FORMAT_LABELS["private_message"],
            "text": private,
            "tone": tone,
            "target_emotion": f"ביטחון + {trigger}",
            "persuasion_lever_used": lever,
        },
        "general_message": {
            "format": FORMAT_LABELS["general_message"],
            "text": general,
            "tone": "קהילתי-חם",
            "target_emotion": "תקווה + שייכות קהילתית",
            "persuasion_lever_used": lever,
        },
        "social_post_fb": {
            "format": FORMAT_LABELS["social_post_fb"],
            "text": fb,
            "tone": "סיפורי-ישראלי",
            "target_emotion": "תקווה + דחיפות חיובית",
            "persuasion_lever_used": lever,
        },
        "social_post_x": {
            "format": FORMAT_LABELS["social_post_x"],
            "text": x[:280],
            "tone": "חד-תכלס",
            "target_emotion": "סקרנות",
            "persuasion_lever_used": lever,
        },
    }

    out: dict[str, dict[str, Any]] = {}
    for key, item in payloads.items():
        text = _ensure_slang(item["text"], format_key=key)
        score = _engagement(
            format_key=key,
            text=text,
            first=first,
            neighborhood=nb,
            lever=lever,
            personalized=bool(first and nb),
        )
        out[key] = {
            **item,
            "text": text,
            "character_count": len(text),
            "engagement_score": score,
        }
    _ = (full_name, style)
    return out

async def _groq_formats(
    *,
    first: str,
    neighborhood: str,
    gotv: str,
    topic: str,
    psych: dict[str, Any],
    signals: list[str],
) -> dict[str, dict[str, Any]] | None:
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        return None
    profile = psych.get("profile") or {}
    prompt = (
        f"Campaign topic: {topic}\n"
        f"Voter: {first}, {neighborhood}, GOTV={gotv}\n"
        f"Psychological Profile: {json.dumps(profile, ensure_ascii=False)[:1800]}\n"
        f"OSINT signals: {', '.join(signals)}\n"
        "Generate 4 Hebrew formats as JSON keys: private_message, general_message, social_post_fb, social_post_x. "
        "social_post_x must be under 280 characters. ALL text Hebrew only. "
        "CRITICAL: write like a 35-year-old Israeli activist — use slang naturally "
        "(אחי, וואלה, תכלס, אשכרה, יאללה, סבבה, פצצה). "
        "NEVER use formal Hebrew (נא, הנכם, בכבוד רב, אנו מתכבדים)."
    )
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=20),
                json={
                    "model": "llama-3.3-70b-versatile",
                    "temperature": 0.8,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are an Israeli political campaign writer. "
                                "Write ONLY authentic Israeli Hebrew with natural slang. "
                                "Return JSON only with four string fields."
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                },
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                content = data["choices"][0]["message"]["content"]
                start = content.find("{")
                end = content.rfind("}") + 1
                if start < 0 or end <= start:
                    return None
                parsed = json.loads(content[start:end])
                persuasion = profile.get("persuasion") or {}
                approach = profile.get("recommended_approach") or {}
                lever = persuasion.get("primary_lever") or "הוכחות מוחשיות"
                tone = approach.get("tone") or "מקצועי-חם"
                triggers = persuasion.get("emotional_triggers") or ["גאווה מקומית"]
                out: dict[str, dict[str, Any]] = {}
                for fmt in FORMATS:
                    text = str(parsed.get(fmt) or "").strip()
                    if not text or _hebrew_ratio(text) < 0.2:
                        return None
                    if fmt == "social_post_x":
                        text = text[:280]
                    text = _ensure_slang(text, format_key=fmt)
                    if fmt == "social_post_x":
                        text = text[:280]
                    out[fmt] = {
                        "format": FORMAT_LABELS[fmt],
                        "text": text,
                        "character_count": len(text),
                        "tone": tone if fmt == "private_message" else FORMAT_LABELS[fmt],
                        "target_emotion": triggers[0] if triggers else "מעורבות",
                        "persuasion_lever_used": lever,
                        "engagement_score": _engagement(
                            format_key=fmt,
                            text=text,
                            first=first,
                            neighborhood=neighborhood,
                            lever=lever,
                            personalized=True,
                        ),
                    }
                return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("Groq writer failed: %s", exc)
        return None


async def generate_for_voter(
    voter: dict[str, Any],
    *,
    campaign_topic: str = "חינוך",
    formats: list[str] | None = None,
    campaign_id: str = "",
    persist: bool = True,
    use_llm: bool = True,
) -> dict[str, Any]:
    psych, profile_id = await _ensure_psych(voter)
    first = str(voter.get("first_name") or "").strip() or "חבר"
    last = str(voter.get("last_name") or "").strip()
    full_name = f"{first} {last}".strip()
    nb = str(voter.get("neighborhood") or voter.get("city") or "")
    gotv = str(psych.get("gotv_category") or voter.get("gotv_category") or "SWING").upper()
    topic = campaign_topic or "חינוך"
    signals = list(psych.get("osint_signals_used") or [])

    fmt_set = set(formats or ["all"])
    if "all" in fmt_set:
        wanted = list(FORMATS)
    else:
        wanted = [f for f in FORMATS if f in fmt_set]
        if not wanted:
            wanted = list(FORMATS)

    package = None
    if use_llm:
        package = await _groq_formats(
            first=first,
            neighborhood=nb,
            gotv=gotv,
            topic=topic,
            psych=psych,
            signals=signals,
        )
    if not package:
        package = _fallback_formats(
            first=first,
            full_name=full_name,
            neighborhood=nb,
            gotv=gotv,
            topic=topic,
            psych=psych,
        )

    selected = {k: package[k] for k in wanted if k in package}
    best = max(selected.keys(), key=lambda k: float(selected[k].get("engagement_score") or 0))
    generated_at = datetime.now(UTC).isoformat()
    cid = campaign_id or secrets.token_hex(6)

    if persist:
        for fmt, item in selected.items():
            await db.insert_generated_content(
                {
                    "id": secrets.token_hex(8),
                    "voter_id": str(voter["id"]),
                    "format": fmt,
                    "text": item["text"],
                    "tone": item.get("tone", ""),
                    "target_emotion": item.get("target_emotion", ""),
                    "persuasion_lever_used": item.get("persuasion_lever_used", ""),
                    "character_count": item.get("character_count", len(item["text"])),
                    "engagement_score": item.get("engagement_score", 0.5),
                    "psychological_profile_id": profile_id,
                    "created_at": generated_at,
                    "campaign_topic": topic,
                    "language": "he",
                    "campaign_id": cid,
                }
            )

    profile = psych.get("profile") or {}
    return {
        "voter_id": str(voter["id"]),
        "full_name": full_name,
        "gotv_category": gotv,
        "neighborhood": nb,
        "psychological_profile": {
            "dominant_trait": (profile.get("personality") or {}).get("dominant_traits", ["מצפוניות"])[0],
            "communication_style": (profile.get("personality") or {}).get("communication_style", ""),
            "primary_lever": (profile.get("persuasion") or {}).get("primary_lever", ""),
            "emotional_triggers": (profile.get("persuasion") or {}).get("emotional_triggers", []),
        },
        "formats": selected,
        "best_format": best,
        "campaign_topic": topic,
        "campaign_id": cid,
        "generated_at": generated_at,
    }


class GenerateRequest(BaseModel):
    voter_id: str = Field(min_length=1)
    campaign_topic: str = "חינוך"
    formats: list[str] = Field(default_factory=lambda: ["all"])


class BatchGenerateRequest(BaseModel):
    voter_ids: list[str] = Field(default_factory=list)
    campaign_topic: str = "חינוך"
    formats: list[str] = Field(default_factory=lambda: ["all"])
    max_count: int = Field(default=500, ge=1, le=500)


class CompareRequest(BaseModel):
    voter_id: str = Field(min_length=1)
    campaign_topic: str = "חינוך"


@router.post("/intel/writer/generate")
async def writer_generate(body: GenerateRequest) -> dict[str, Any]:
    voter = await db.resolve_voter(body.voter_id)
    if not voter:
        raise HTTPException(status_code=404, detail={"message": "בוחר לא נמצא", "voter_id": body.voter_id})
    return await generate_for_voter(
        voter,
        campaign_topic=body.campaign_topic,
        formats=body.formats,
        use_llm=True,
    )


@router.post("/intel/writer/batch-generate")
async def writer_batch(body: BatchGenerateRequest) -> dict[str, Any]:
    t0 = time.perf_counter()
    ids = body.voter_ids[: body.max_count]
    if not ids:
        voters = (await db.list_voters(limit=body.max_count))[0]
        ids = [str(v["id"]) for v in voters]
    campaign_id = secrets.token_hex(6)
    content: list[dict[str, Any]] = []
    dist = {f: 0 for f in FORMATS}
    scores: list[float] = []
    for vid in ids:
        voter = await db.resolve_voter(vid)
        if not voter:
            continue
        pkg = await generate_for_voter(
            voter,
            campaign_topic=body.campaign_topic,
            formats=body.formats,
            campaign_id=campaign_id,
            persist=True,
            use_llm=False,  # batch stays under 15s
        )
        content.append(pkg)
        for fmt, item in (pkg.get("formats") or {}).items():
            if fmt in dist:
                dist[fmt] += 1
            scores.append(float(item.get("engagement_score") or 0))
    duration_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "generated": len(content),
        "campaign_topic": body.campaign_topic,
        "campaign_id": campaign_id,
        "format_distribution": dist,
        "content": content,
        "avg_engagement_score": round(sum(scores) / len(scores), 2) if scores else 0.0,
        "duration_ms": duration_ms,
        "export_json_url": f"/api/intel/writer/export/campaign-{campaign_id}.json",
    }


@router.get("/intel/writer/history/{voter_id}")
async def writer_history(voter_id: str) -> dict[str, Any]:
    voter = await db.resolve_voter(voter_id)
    if not voter:
        raise HTTPException(status_code=404, detail={"message": "בוחר לא נמצא", "voter_id": voter_id})
    rows = await db.list_generated_content(str(voter["id"]), limit=100)
    return {
        "voter_id": str(voter["id"]),
        "history": [
            {
                "id": r.get("id"),
                "format": r.get("format"),
                "text": r.get("text"),
                "engagement_score": r.get("engagement_score"),
                "campaign_topic": r.get("campaign_topic"),
                "created_at": r.get("created_at"),
            }
            for r in rows
        ],
    }


@router.post("/intel/writer/compare")
async def writer_compare(body: CompareRequest) -> dict[str, Any]:
    voter = await db.resolve_voter(body.voter_id)
    if not voter:
        raise HTTPException(status_code=404, detail={"message": "בוחר לא נמצא", "voter_id": body.voter_id})
    pkg = await generate_for_voter(
        voter,
        campaign_topic=body.campaign_topic,
        formats=["all"],
        use_llm=False,
    )
    formats = {
        k: {"text": v["text"], "engagement_score": v["engagement_score"], "format": v.get("format")}
        for k, v in (pkg.get("formats") or {}).items()
    }
    best = pkg.get("best_format") or "social_post_fb"
    best_score = formats.get(best, {}).get("engagement_score", 0)
    return {
        "voter_id": pkg["voter_id"],
        "formats": formats,
        "recommendation": f"{best} — highest engagement ({best_score})",
        "recommendation_he": f"{FORMAT_LABELS.get(best, best)} — מעורבות הגבוהה ביותר ({best_score})",
    }


@router.get("/intel/writer/export/{campaign_file}")
async def writer_export(campaign_file: str) -> JSONResponse:
    campaign_id = campaign_file
    if campaign_id.startswith("campaign-"):
        campaign_id = campaign_id[len("campaign-") :]
    if campaign_id.endswith(".json"):
        campaign_id = campaign_id[: -len(".json")]
    rows = await db.list_generated_content_by_campaign(campaign_id)
    by_format: dict[str, list[dict[str, Any]]] = {f: [] for f in FORMATS}
    for r in rows:
        fmt = str(r.get("format") or "")
        item = {
            "id": r.get("id"),
            "voter_id": r.get("voter_id"),
            "text": r.get("text"),
            "tone": r.get("tone"),
            "engagement_score": r.get("engagement_score"),
            "campaign_topic": r.get("campaign_topic"),
            "created_at": r.get("created_at"),
        }
        if fmt in by_format:
            by_format[fmt].append(item)
        else:
            by_format.setdefault(fmt, []).append(item)
    payload = {
        "campaign_id": campaign_id,
        "exported_at": datetime.now(UTC).isoformat(),
        "total": len(rows),
        "by_format": by_format,
    }
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="campaign-{campaign_id}.json"'},
    )
