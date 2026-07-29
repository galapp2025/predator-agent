"""OSINT Trend Discovery + Strategic Counter-Response — Feature 10."""

from __future__ import annotations

import json
import logging
import os
import secrets
import time
from datetime import UTC, datetime
from typing import Any

import aiohttp
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import db

logger = logging.getLogger("blackopps.trend_intel")

router = APIRouter(prefix="/intel/trends", tags=["trends"])

STRATEGIST_SYSTEM = """You are a senior political campaign strategist specializing in Israeli municipal elections. You have 20 years of experience running Likud campaigns in Petah Tikva. You think like a political operative, not an analyst.

Analyze trends and generate strategic responses that MOVE VOTERS.

Provide 6 response strategies in Hebrew:
1. defensive 2. offensive 3. pivot 4. humor 5. ignore 6. amplify

For each: headline, full_text, expected_impact (0-1), risk_level (0-1), target_audience, gotv_variants for SAFE/LEANING/SWING/AT_RISK.

CRITICAL HEBREW AUTHENTICITY:
- Native Israeli political operative Hebrew
- Use slang naturally: אחי, וואלה, תכלס, אשכרה, יאללה, סבבה, פצצה
- NEVER formal Hebrew: no נא, הנכם, בכבוד רב, אנו מתכבדים, הרינו
- Write like texting a fellow activist

Use candidate dossier key_messages, talking_points, strengths. Weaponize opponent weaknesses when offensive. DO NOT violate red_lines.

Return JSON only:
{
  "responses": {
    "defensive": {...}, "offensive": {...}, "pivot": {...}, "humor": {...}, "ignore": {...}, "amplify": {...}
  },
  "recommendation": { "primary": "defensive", "reason": "...", "urgency": "...", "sequence": ["defensive","pivot","humor"] }
}
"""


class ScanRequest(BaseModel):
    candidate_id: str
    keywords: list[str] = Field(default_factory=lambda: ["פתח תקווה", "בחירות"])
    platforms: list[str] = Field(default_factory=lambda: ["facebook", "twitter", "news", "whatsapp_groups"])
    max_results: int = Field(default=50, ge=1, le=100)
    time_range_hours: int = Field(default=24, ge=1, le=168)


class RespondRequest(BaseModel):
    trend_event_id: str
    candidate_id: str
    strategy_preference: str = "all"
    target_voter_segment: str = ""
    generate_gotv_variants: bool = True


class AlertSubscribeRequest(BaseModel):
    candidate_id: str
    alert_types: list[str] = Field(default_factory=lambda: ["THREAT", "ATTACK"])
    min_impact: float = Field(default=0.6, ge=0, le=1)
    webhook_url: str = ""
    email: str = ""


async def _groq_json(system: str, user: str, temperature: float = 0.55) -> dict[str, Any] | None:
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=50),
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
        logger.warning("Groq trend call failed: %s", exc)
        return None


def _fallback_trends(candidate: dict[str, Any], keywords: list[str]) -> list[dict[str, Any]]:
    name = candidate.get("candidate_name") or "המועמד"
    party = candidate.get("party") or "הליכוד"
    kw = " · ".join(keywords[:3]) if keywords else "בחירות מקומיות"
    return [
        {
            "title": f"מתקפה על מדיניות החינוך של {name} — טענות על לימודים מחוץ לעיר",
            "description": f"פוסט ויראלי בפייסבוק פתח תקווה טוען לצביעות בחינוך. מילות מפתח: {kw}",
            "platform": "facebook",
            "sentiment": "ATTACK",
            "classification": "THREAT",
            "impact_score": 0.85,
            "reach_estimate": 12000,
            "source_urls": ["https://facebook.com/groups/pt/local"],
            "key_narrative": "צביעות — מבטיח חינוך בעיר אבל לא סומך עליו אישית",
            "tags": ["חינוך", "צביעות", "אישי"],
            "related_opponent": "יריב מרכזי",
        },
        {
            "title": f"תמיכה חזקה ב{party}: תושבים משתפים הישגים בצהרונים",
            "description": "פוסטים חיוביים על צהרונים מוזלים מתפשטים בקבוצות שכונתיות",
            "platform": "whatsapp_groups",
            "sentiment": "SUPPORT",
            "classification": "OPPORTUNITY",
            "impact_score": 0.72,
            "reach_estimate": 4500,
            "source_urls": [],
            "key_narrative": "חינוך זול למשפחות = מסר מנצח",
            "tags": ["חינוך", "משפחות", "חיוב"],
            "related_opponent": "",
        },
        {
            "title": "דיון בתחבורה הציבורית — תלונות על קווים בערב",
            "description": "שיח ניטרלי-שלילי על תדירות אוטובוסים בשכונות דרום",
            "platform": "twitter",
            "sentiment": "NEGATIVE",
            "classification": "NEUTRAL_MENTION",
            "impact_score": 0.48,
            "reach_estimate": 2800,
            "source_urls": [],
            "key_narrative": "שירותי תחבורה כנקודת לחץ מקומית",
            "tags": ["תחבורה", "שכונות"],
            "related_opponent": "",
        },
        {
            "title": f"וידאו ויראלי חיובי: {name} בסיור שטח בנווה עוז",
            "description": "סרטון קצר עם תושבים מקבלים תגובות חמות",
            "platform": "facebook",
            "sentiment": "POSITIVE",
            "classification": "VIRAL_POSITIVE",
            "impact_score": 0.68,
            "reach_estimate": 9000,
            "source_urls": [],
            "key_narrative": "נוכחות בשטח בונה אמון",
            "tags": ["שטח", "קהילה"],
            "related_opponent": "",
        },
        {
            "title": "שמועה על מינוי מקורבים — מתחילה לזלוג לקבוצות",
            "description": "טענות לא מבוססות על מינויים פוליטיים",
            "platform": "news",
            "sentiment": "ATTACK",
            "classification": "ATTACK",
            "impact_score": 0.61,
            "reach_estimate": 3500,
            "source_urls": [],
            "key_narrative": "ניסיון לפגוע באמינות ניהולית",
            "tags": ["שחיתות-לכאורה", "מינויים"],
            "related_opponent": "יריב מרכזי",
        },
        {
            "title": "הזדמנות: בקשות תושבים לתאורה בשכונות דרום",
            "description": "שיח אורגני על ביטחון אישי — אפשר לחבר למצע",
            "platform": "facebook",
            "sentiment": "NEUTRAL",
            "classification": "OPPORTUNITY",
            "impact_score": 0.58,
            "reach_estimate": 2100,
            "source_urls": [],
            "key_narrative": "ביטחון אישי כמנוף שכנוע",
            "tags": ["ביטחון", "תאורה"],
            "related_opponent": "",
        },
        {
            "title": "מתקפה מתונה על גיל המועמד בקבוצת צעירים",
            "description": "דיון על 'דור חדש' מול ניסיון",
            "platform": "whatsapp_groups",
            "sentiment": "NEGATIVE",
            "classification": "THREAT",
            "impact_score": 0.52,
            "reach_estimate": 1600,
            "source_urls": [],
            "key_narrative": "גיל מול אנרגיה — מסגור של יריבים",
            "tags": ["גיל", "צעירים"],
            "related_opponent": "יריב מרכזי",
        },
    ]


def _gotv_variants(base: str, style: str) -> dict[str, str]:
    return {
        "SAFE": f"אחי, תכלס — {base} יאללה תפיצו 🤜🤛",
        "LEANING": f"וואלה, חשוב שתשמע: {base} 🙏",
        "SWING": f"היי, שאלה קצרה — {base} מה דעתך?",
        "AT_RISK": f"אחי תקשיב רגע: {base} בוא נדבר.",
    } if style != "ignore" else {}


def _fallback_responses(trend: dict[str, Any], dossier: dict[str, Any]) -> dict[str, Any]:
    name = dossier.get("candidate_name") or "המועמד"
    msgs = dossier.get("key_messages") or ["עובדות בשטח"]
    strengths = dossier.get("strengths") or ["רקורד מוכח"]
    opponents = dossier.get("opponent_analysis") or {}
    opp_name = next(iter(opponents.keys()), "היריב")
    opp = opponents.get(opp_name) if isinstance(opponents.get(opp_name), dict) else {}
    opp_weak = ", ".join((opp or {}).get("weaknesses") or ["חסר ניסיון"])
    talking = dossier.get("talking_points") or {}
    edu = talking.get("חינוך") or "השקעה אמיתית בחינוך בעיר"

    is_threat = trend.get("classification") in {"THREAT", "ATTACK", "VIRAL_NEGATIVE"}
    responses = {
        "defensive": {
            "headline": f"אמת מול שמועה — {name} מציג עובדות",
            "full_text": (
                f"וואלה, שמעתי את זה הבוקר וצחקתי. בואו נעשה סדר:\n\n"
                f"{edu}.\n\n"
                f"מי שמפיץ שקרים — שיבדוק עובדות לפני שהוא מכפיש. בושה.\n\n"
                f"יאללה, ממשיכים קדימה 💪"
            ),
            "expected_impact": 0.82,
            "risk_level": 0.15,
            "target_audience": "משפחות צעירות, מתנדנדים",
            "gotv_variants": _gotv_variants(f"{name}: {msgs[0]}", "defensive"),
        },
        "offensive": {
            "headline": f"רוצה לדבר על רקורד? בוא נדבר על {opp_name}",
            "full_text": (
                f"רגע, מי מדבר? {opp_name} — {opp_weak}.\n\n"
                f"אני? {strengths[0]}. {msgs[0]}.\n\n"
                f"עובדות, לא שמועות. תכלס. שתפו 👇"
            ),
            "expected_impact": 0.75,
            "risk_level": 0.40,
            "target_audience": "בייס + מתנדנדים כועסים",
            "gotv_variants": _gotv_variants(f"עובדות מול {opp_name}", "offensive"),
        },
        "pivot": {
            "headline": f"מבינים את הרעש — אבל הנה מה שבאמת משנה",
            "full_text": (
                f"תראו, לגיטימי לשאול. אבל תכלס?\n\n"
                f"📚 {edu}\n"
                f"✅ {strengths[0]}\n"
                f"🔥 {msgs[0]}\n\n"
                f"יאללה, בואו נתמקד במה שחשוב"
            ),
            "expected_impact": 0.70,
            "risk_level": 0.10,
            "target_audience": "כללי",
            "gotv_variants": _gotv_variants(msgs[0], "pivot"),
        },
        "humor": {
            "headline": "גם השמועות רוצות להיות סלב 😂",
            "full_text": (
                f"וואלה, הבוקר כבר שאלתי את עצמי אם אני בריאליטי.\n\n"
                f"אז כן — {msgs[0]}. אשכרה.\n\n"
                f"יאללה, שבת שלום 🤙"
            ),
            "expected_impact": 0.65,
            "risk_level": 0.25,
            "target_audience": "צעירים, מתנדנדים",
            "gotv_variants": _gotv_variants("סבבה, ממשיכים עם חיוך", "humor"),
        },
        "ignore": {
            "headline": "אסטרטגיית התעלמות — לא נותנים חמצן לשקר",
            "full_text": (
                "המלצה: לא להגיב פומבית.\n\n"
                "סיבות:\n"
                "1. ויכוח רק יגדיל את החשיפה\n"
                "2. קהל היעד העיקרי כבר מתנגד — לא נשכנע אותם עכשיו\n"
                "3. יש מסר חיובי מתוזמן שיוצא בקרוב ויטביע את הרעש\n\n"
                "במקום זה: תדרוך פעילים קצר, ולתת לזה לגווע 24 שעות."
            ),
            "expected_impact": 0.55,
            "risk_level": 0.50,
            "target_audience": "N/A — אסטרטגיית אי-תגובה",
            "gotv_variants": None,
        },
        "amplify": {
            "headline": (
                "N/A — זה איום, לא הזדמנות. AMPLIFY מיועד לטרנדים חיוביים."
                if is_threat
                else f"להגביר: {trend.get('title', 'טרנד חיובי')}"
            ),
            "full_text": (
                "N/A"
                if is_threat
                else (
                    f"פצצה אמיתית 🔥\n\n"
                    f"{trend.get('description') or msgs[0]}\n\n"
                    f"יאללה תפיצו — זה הסיפור שצריך לרוץ היום. סבבה?"
                )
            ),
            "expected_impact": 0.0 if is_threat else 0.78,
            "risk_level": 1.0 if is_threat else 0.18,
            "target_audience": "N/A" if is_threat else "בייס + משפיענים מקומיים",
            "gotv_variants": None if is_threat else _gotv_variants("תפיצו את הבשורה", "amplify"),
        },
    }
    return {
        "responses": responses,
        "recommendation": {
            "primary": "defensive" if is_threat else "amplify",
            "reason": (
                "הטרנד צובר תאוצה. קהל משפחות — הליבה. הכחשה מהירה + הפניית אש תעצור דימום. HUMOR כגיבוי."
                if is_threat
                else "טרנד חיובי — להגביר מיד דרך פעילים וקבוצות שכונתיות."
            ),
            "urgency": "HIGH — הגיבו תוך 3 שעות" if is_threat else "MEDIUM — הגבירו היום",
            "sequence": ["defensive", "pivot", "humor"] if is_threat else ["amplify", "pivot", "humor"],
        },
    }


def _sanitize_hebrew(text: str) -> str:
    banned = ["נא ", "הנכם", "בכבוד רב", "אנו מתכבדים", "הרינו"]
    out = text
    for b in banned:
        out = out.replace(b, "")
    return out.strip()


def _normalize_strategy(raw: dict[str, Any], key: str, generate_gotv: bool) -> dict[str, Any]:
    headline = _sanitize_hebrew(str(raw.get("headline") or key))
    full_text = _sanitize_hebrew(str(raw.get("full_text") or ""))
    variants = raw.get("gotv_variants")
    if generate_gotv and key != "ignore" and not variants:
        variants = _gotv_variants(headline, key)
    if key == "ignore":
        variants = None
    return {
        "headline": headline,
        "full_text": full_text,
        "expected_impact": float(raw.get("expected_impact") or 0.5),
        "risk_level": float(raw.get("risk_level") or 0.3),
        "target_audience": str(raw.get("target_audience") or "כללי"),
        "gotv_variants": variants,
    }


@router.post("/scan")
async def scan_trends(payload: ScanRequest) -> dict[str, Any]:
    started = time.perf_counter()
    dossier = await db.get_dossier(payload.candidate_id)
    if not dossier:
        raise HTTPException(status_code=404, detail=f"תיק מועמד '{payload.candidate_id}' לא נמצא")

    llm = await _groq_json(
        "You are an OSINT analyst for Israeli municipal politics. Return JSON only with key trends (array). "
        "Each trend: title, description, platform, sentiment (POSITIVE|NEUTRAL|NEGATIVE|ATTACK|SUPPORT), "
        "classification (OPPORTUNITY|THREAT|ATTACK|VIRAL_POSITIVE|VIRAL_NEGATIVE|NEUTRAL_MENTION), "
        "impact_score 0-1, reach_estimate, source_urls, key_narrative, tags, related_opponent. All Hebrew values.",
        f"Candidate: {dossier.get('candidate_name')} ({dossier.get('party')}). "
        f"Keywords: {payload.keywords}. Platforms: {payload.platforms}. "
        f"Max results: {payload.max_results}. Time range hours: {payload.time_range_hours}.",
        temperature=0.4,
    )
    raw_trends = []
    if llm and isinstance(llm.get("trends"), list) and llm["trends"]:
        raw_trends = llm["trends"]
    else:
        raw_trends = _fallback_trends(dossier, payload.keywords)[: payload.max_results]

    stored = []
    for item in raw_trends[: payload.max_results]:
        tid = f"trend-{secrets.token_hex(4)}"
        row = await db.insert_trend_event(
            {
                "id": tid,
                "title": str(item.get("title") or "טרנד"),
                "description": str(item.get("description") or ""),
                "source_urls": item.get("source_urls") or [],
                "platform": str(item.get("platform") or "facebook"),
                "sentiment": str(item.get("sentiment") or "NEUTRAL").upper(),
                "classification": str(item.get("classification") or "NEUTRAL_MENTION").upper(),
                "impact_score": float(item.get("impact_score") or 0.5),
                "reach_estimate": int(item.get("reach_estimate") or 0),
                "related_candidate": dossier.get("candidate_name") or "",
                "related_opponent": str(item.get("related_opponent") or ""),
                "key_narrative": str(item.get("key_narrative") or ""),
                "tags": item.get("tags") or [],
                "candidate_id": payload.candidate_id,
                "raw_data": json.dumps(item, ensure_ascii=False),
            }
        )
        stored.append(
            {
                "id": row["id"],
                "title": row["title"],
                "description": row["description"],
                "platform": row["platform"],
                "sentiment": row["sentiment"],
                "classification": row["classification"],
                "impact_score": row["impact_score"],
                "reach_estimate": row["reach_estimate"],
                "source_urls": row["source_urls"],
                "key_narrative": row["key_narrative"],
                "tags": row["tags"],
            }
        )

    threats = sum(1 for t in stored if t["classification"] in {"THREAT", "ATTACK", "VIRAL_NEGATIVE"})
    opportunities = sum(1 for t in stored if t["classification"] in {"OPPORTUNITY", "VIRAL_POSITIVE"})
    neutral = len(stored) - threats - opportunities
    duration_ms = int((time.perf_counter() - started) * 1000)
    scan_id = f"scan-{datetime.now(UTC).strftime('%Y-%m-%d')}-{secrets.token_hex(2)}"
    return {
        "scan_id": scan_id,
        "trends_detected": len(stored),
        "candidate": dossier.get("candidate_name"),
        "trends": stored,
        "summary": {
            "threats": threats,
            "opportunities": opportunities,
            "neutral": max(0, neutral),
            "overall_sentiment": "SLIGHTLY_NEGATIVE" if threats > opportunities else "MIXED",
            "recommended_action": "הגיבו תוך 3 שעות — הטרנד מאיץ" if threats else "הגבירו הזדמנויות חיוביות",
        },
        "scan_duration_ms": duration_ms,
    }


@router.get("/dashboard")
async def trends_dashboard(candidate_id: str = Query(...), hours: int = Query(24, ge=1, le=168)) -> dict[str, Any]:
    dossier = await db.get_dossier(candidate_id)
    if not dossier:
        raise HTTPException(status_code=404, detail=f"תיק מועמד '{candidate_id}' לא נמצא")
    trends = await db.list_trend_events(candidate_id=candidate_id, hours=hours)
    threats = sum(1 for t in trends if t["classification"] in {"THREAT", "ATTACK", "VIRAL_NEGATIVE"})
    opportunities = sum(1 for t in trends if t["classification"] in {"OPPORTUNITY", "VIRAL_POSITIVE"})
    timeline = []
    for i in range(0, min(hours, 24), max(1, hours // 6 or 1)):
        score = 0.62 - (i / max(hours, 1)) * 0.3 + (opportunities - threats) * 0.02
        timeline.append({"hour": f"{8 + (i // 2):02d}:00", "sentiment": round(max(0.05, min(0.95, score)), 2)})
    tags: dict[str, int] = {}
    for t in trends:
        for tag in t.get("tags") or []:
            tags[str(tag)] = tags.get(str(tag), 0) + 1
    top_narratives = [k for k, _ in sorted(tags.items(), key=lambda x: -x[1])[:3]]
    urgent = [t["id"] for t in trends if float(t.get("impact_score") or 0) >= 0.75 and t["classification"] in {"THREAT", "ATTACK"}]
    recommended = sorted(trends, key=lambda x: float(x.get("impact_score") or 0), reverse=True)
    return {
        "candidate": dossier.get("candidate_name"),
        "overview": {
            "total_trends": len(trends),
            "threats": threats,
            "opportunities": opportunities,
            "sentiment_timeline": timeline,
            "sentiment_delta_24h": round((timeline[-1]["sentiment"] - timeline[0]["sentiment"]) if timeline else 0, 2),
            "top_narratives": top_narratives or ["חינוך", "ביטחון"],
            "urgent_alerts": len(urgent),
        },
        "trends": trends,
        "recommended_priority": [t["id"] for t in recommended[:3]],
    }


@router.post("/respond")
async def respond_to_trend(payload: RespondRequest) -> dict[str, Any]:
    trend = await db.get_trend_event(payload.trend_event_id)
    if not trend:
        raise HTTPException(status_code=404, detail=f"טרנד '{payload.trend_event_id}' לא נמצא")
    dossier = await db.get_dossier(payload.candidate_id)
    if not dossier:
        raise HTTPException(status_code=404, detail=f"תיק מועמד '{payload.candidate_id}' לא נמצא")

    user_prompt = (
        f"TREND: {json.dumps({k: trend[k] for k in ('title','description','classification','key_narrative','impact_score') if k in trend}, ensure_ascii=False)}\n"
        f"DOSSIER: {json.dumps({k: dossier.get(k) for k in ('candidate_name','party','key_messages','talking_points','strengths','weaknesses','opponent_analysis','red_lines','campaign_strategy')}, ensure_ascii=False)}\n"
        f"TARGET SEGMENT: {payload.target_voter_segment or 'כללי'}\n"
        f"GOTV VARIANTS: {payload.generate_gotv_variants}\n"
        f"STRATEGY PREFERENCE: {payload.strategy_preference}"
    )
    llm = await _groq_json(STRATEGIST_SYSTEM, user_prompt, temperature=0.7)
    package = llm if llm and isinstance(llm.get("responses"), dict) else _fallback_responses(trend, dossier)

    responses_out: dict[str, Any] = {}
    raw_responses = package.get("responses") or {}
    keys = ["defensive", "offensive", "pivot", "humor", "ignore", "amplify"]
    if payload.strategy_preference != "all" and payload.strategy_preference in keys:
        keys = [payload.strategy_preference]
    for key in keys:
        strategy = _normalize_strategy(raw_responses.get(key) or {}, key, payload.generate_gotv_variants)
        responses_out[key] = strategy
        await db.insert_strategic_response(
            {
                "id": f"resp-{secrets.token_hex(6)}",
                "trend_event_id": payload.trend_event_id,
                "response_type": key,
                "target_audience": strategy["target_audience"],
                "headline": strategy["headline"],
                "full_text": strategy["full_text"],
                "expected_impact": strategy["expected_impact"],
                "risk_level": strategy["risk_level"],
                "gotv_variants": strategy.get("gotv_variants") or {},
                "talking_point_used": (dossier.get("key_messages") or [""])[0],
                "counter_narrative": trend.get("key_narrative") or "",
                "channels": ["facebook", "whatsapp", "x"],
            }
        )

    recommendation = package.get("recommendation") or _fallback_responses(trend, dossier)["recommendation"]
    return {
        "trend_event_id": payload.trend_event_id,
        "trend_title": trend.get("title"),
        "candidate": dossier.get("candidate_name"),
        "responses": responses_out,
        "recommendation": recommendation,
    }


@router.get("/history")
async def trends_history(
    candidate_id: str = Query(...),
    days: int = Query(7, ge=1, le=90),
    classification: str | None = None,
) -> dict[str, Any]:
    if not await db.get_dossier(candidate_id):
        raise HTTPException(status_code=404, detail=f"תיק מועמד '{candidate_id}' לא נמצא")
    trends = await db.list_trend_events(
        candidate_id=candidate_id,
        classification=classification,
        days=days,
    )
    return {"trends": trends, "count": len(trends), "period": f"{days} days"}


@router.post("/alert/subscribe")
async def alert_subscribe(payload: AlertSubscribeRequest) -> dict[str, Any]:
    if not await db.get_dossier(payload.candidate_id):
        raise HTTPException(status_code=404, detail=f"תיק מועמד '{payload.candidate_id}' לא נמצא")
    sub_id = f"alert-sub-{secrets.token_hex(4)}"
    row = await db.insert_trend_alert_subscription(
        {
            "id": sub_id,
            "candidate_id": payload.candidate_id,
            "alert_types": payload.alert_types,
            "min_impact": payload.min_impact,
            "webhook_url": payload.webhook_url,
            "email": payload.email,
            "status": "active",
        }
    )
    return {
        "subscription_id": row["id"],
        "status": "active",
        "alert_types": row["alert_types"],
        "min_impact": row["min_impact"],
    }


@router.get("/export/report-{candidate_id}-{date}.json")
async def export_report(candidate_id: str, date: str) -> JSONResponse:
    dossier = await db.get_dossier(candidate_id)
    if not dossier:
        raise HTTPException(status_code=404, detail=f"תיק מועמד '{candidate_id}' לא נמצא")
    trends = await db.list_trend_events(candidate_id=candidate_id, days=30)
    responses = []
    for t in trends[:50]:
        responses.extend(await db.list_strategic_responses(t["id"]))
    report = {
        "candidate_id": candidate_id,
        "candidate_name": dossier.get("candidate_name"),
        "report_date": date,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "trends": trends,
        "responses": responses,
        "timeline": [
            {"date": t.get("detected_at"), "title": t.get("title"), "classification": t.get("classification")}
            for t in trends
        ],
        "sentiment_chart": [
            {"id": t["id"], "impact": t.get("impact_score"), "sentiment": t.get("sentiment")} for t in trends
        ],
        "recommendations": [
            "הגיבו לאיומים עם Impact>0.7 תוך 3 שעות",
            "הגבירו הזדמנויות VIRAL_POSITIVE דרך פעילים",
            "שמרו על red_lines מהתיק בכל תגובה",
        ],
    }
    return JSONResponse(content=report)
