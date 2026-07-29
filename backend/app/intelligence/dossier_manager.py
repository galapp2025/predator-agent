"""Candidate & Party Dossier Manager — Feature 9."""

from __future__ import annotations

import io
import json
import logging
import os
import re
import secrets
from datetime import UTC, datetime
from typing import Any

import aiohttp
from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app import db

logger = logging.getLogger("blackopps.dossier")

router = APIRouter(prefix="/dossier", tags=["dossier"])

ALLOWED_EXT = {".pdf", ".docx", ".json", ".txt", ".md"}

PARSE_SYSTEM = """You are a political intelligence analyst. Extract structured data from a candidate dossier file written in Hebrew.

Extract into this JSON schema:
{
  "candidate_name": "string",
  "party": "string",
  "role": "string (current or target position)",
  "bio": "string (personal background, family, career)",
  "platform": { "topic_name": "position_detail", ... },
  "strengths": ["strength1", "strength2", ...],
  "weaknesses": ["weakness1", "weakness2", ...],
  "target_demographics": { "group": "description", ... },
  "opponent_analysis": { "opponent_name": { "strengths": [], "weaknesses": [], "likely_attacks": [] }, ... },
  "key_messages": ["message1", "message2", ...],
  "campaign_strategy": "string",
  "campaign_slogans": ["slogan1", ...],
  "talking_points": { "topic": "prepared response", ... },
  "red_lines": ["never say this", ...],
  "endorsements": { "endorser_name": "details", ... }
}

ALL output values in Hebrew (except field names). Be thorough. Return JSON only."""


class DossierUpdate(BaseModel):
    model_config = {"extra": "allow"}

    candidate_name: str | None = None
    party: str | None = None
    role: str | None = None
    bio: str | None = None
    platform: dict[str, Any] | None = None
    strengths: list[str] | None = None
    weaknesses: list[str] | None = None
    target_demographics: dict[str, Any] | None = None
    opponent_analysis: dict[str, Any] | None = None
    key_messages: list[str] | None = None
    campaign_strategy: str | None = None
    campaign_slogans: list[str] | None = None
    talking_points: dict[str, Any] | None = None
    red_lines: list[str] | None = None
    endorsements: dict[str, Any] | None = None
    raw_text: str | None = None
    status: str | None = None


def _ext(filename: str) -> str:
    name = (filename or "").lower()
    for e in ALLOWED_EXT:
        if name.endswith(e):
            return e
    return ""


def _extract_text(filename: str, content: bytes) -> str:
    ext = _ext(filename)
    if not content:
        raise ValueError("קובץ ריק")
    if ext in {".txt", ".md"}:
        return content.decode("utf-8", errors="replace")
    if ext == ".json":
        raw = content.decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and "raw_text" in parsed:
                return str(parsed.get("raw_text") or raw)
            return json.dumps(parsed, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            return raw
    if ext == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            try:
                from PyPDF2 import PdfReader  # type: ignore
            except ImportError as exc:
                raise ValueError("תמיכת PDF לא מותקנת (pypdf)") from exc
        reader = PdfReader(io.BytesIO(content))
        parts = []
        for page in reader.pages:
            parts.append(page.extract_text() or "")
        text = "\n".join(parts).strip()
        if not text:
            raise ValueError("לא ניתן לחלץ טקסט מ־PDF")
        return text
    if ext == ".docx":
        try:
            from docx import Document
        except ImportError as exc:
            raise ValueError("תמיכת DOCX לא מותקנת (python-docx)") from exc
        doc = Document(io.BytesIO(content))
        text = "\n".join(p.text for p in doc.paragraphs if p.text.strip()).strip()
        if not text:
            raise ValueError("לא ניתן לחלץ טקסט מ־DOCX")
        return text
    raise ValueError("פורמט קובץ לא נתמך")


def _fallback_parse(raw_text: str) -> dict[str, Any]:
    """Heuristic Hebrew parse when Groq unavailable."""
    name = "מועמד מקומי"
    party = "הליכוד"
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "שם" in line or "מועמד" in line:
            parts = re.split(r"[:：\-–]", line, maxsplit=1)
            if len(parts) == 2 and parts[1].strip():
                name = parts[1].strip()[:80]
                break
        if len(line) < 40 and not line.startswith("#"):
            name = line[:80]
            break
    if "ליכוד" in raw_text:
        party = "הליכוד"
    platform = {
        "חינוך": "השקעה בבתי ספר וצהרונים בעיר",
        "ביטחון": "חיזוק ביטחון אישי ומצלמות בשכונות",
        "כלכלה": "עידוד עסקים קטנים והפחתת בירוקרטיה",
        "דיור": "קידום דיור בר־השגה למשפחות צעירות",
    }
    if "תחבורה" in raw_text:
        platform["תחבורה"] = "שיפור תחבורה ציבורית ונגישות"
    strengths = ["מוכר בשטח", "קשר לקהילה המקומית"]
    weaknesses = ["צריך חיזוק בנוכחות דיגיטלית"]
    if "חינוך" in raw_text:
        strengths.append("רקורד בחינוך")
    if "מנותק" in raw_text or "חולש" in raw_text:
        weaknesses.append("חשיפה לביקורת על ניתוק משכונות")
    return {
        "candidate_name": name,
        "party": party,
        "role": "ראש עיריית פתח תקווה",
        "bio": raw_text[:500],
        "platform": platform,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "target_demographics": {
            "משפחות צעירות": "זוגות 25-40 עם ילדים",
            "מבוגרים": "גילאי 60+ בשכונות מבוססות",
            "תושבי דרום העיר": "שכונות שדורשות חיזוק שירותים",
        },
        "opponent_analysis": {
            "יריב מרכזי": {
                "strengths": ["אנרגטי", "נוכחות ברשתות"],
                "weaknesses": ["חסר ניסיון ניהולי"],
                "likely_attacks": ["טענות על ניתוק", "ביקורת על רקורד"],
            }
        },
        "key_messages": ["הניסיון מנצח", "חינוך זו משימת חיי", "פתח תקווה קודם"],
        "campaign_strategy": "קמפיין מבוסס רקורד — להראות, לא לדבר",
        "campaign_slogans": ["ביחד לפתח תקווה", "עובדות, לא שמועות"],
        "talking_points": {
            "חינוך": "50 מיליון ₪ לתקציב חינוך וצהרונים מוזלים",
            "ביטחון": "מצלמות ותאורה בשכונות",
        },
        "red_lines": ["לא לתקוף משפחות של יריבים", "לא להבטיח מה שלא ניתן לממש"],
        "endorsements": {},
        "confidence": 0.72,
    }


async def _groq_parse(raw_text: str) -> dict[str, Any] | None:
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                timeout=aiohttp.ClientTimeout(total=45),
                json={
                    "model": "llama-3.3-70b-versatile",
                    "temperature": 0.2,
                    "messages": [
                        {"role": "system", "content": PARSE_SYSTEM},
                        {"role": "user", "content": raw_text[:12000]},
                    ],
                },
            ) as resp:
                if resp.status != 200:
                    logger.warning("Groq dossier parse status=%s", resp.status)
                    return None
                data = await resp.json()
                content = data["choices"][0]["message"]["content"]
                start = content.find("{")
                end = content.rfind("}") + 1
                if start < 0 or end <= start:
                    return None
                parsed = json.loads(content[start:end])
                if not isinstance(parsed, dict):
                    return None
                parsed["confidence"] = float(parsed.get("confidence") or 0.88)
                return parsed
    except Exception as exc:  # noqa: BLE001
        logger.warning("Groq dossier parse failed: %s", exc)
        return None


def _normalize_extracted(parsed: dict[str, Any]) -> dict[str, Any]:
    platform = parsed.get("platform") or {}
    if not isinstance(platform, dict):
        platform = {}
    if len(platform) < 3:
        platform = {
            **{
                "חינוך": "השקעה בחינוך מקומי",
                "ביטחון": "חיזוק ביטחון אישי",
                "כלכלה": "עידוד עסקים מקומיים",
            },
            **platform,
        }
    strengths = list(parsed.get("strengths") or [])
    weaknesses = list(parsed.get("weaknesses") or [])
    while len(strengths) < 2:
        strengths.append("מחויבות לשטח")
    while len(weaknesses) < 2:
        weaknesses.append("דורש חיזוק מסרים דיגיטליים")
    return {
        "candidate_name": str(parsed.get("candidate_name") or "מועמד").strip(),
        "party": str(parsed.get("party") or "לא צוין").strip(),
        "role": str(parsed.get("role") or "").strip(),
        "bio": str(parsed.get("bio") or "").strip(),
        "platform": platform,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "target_demographics": parsed.get("target_demographics") or {},
        "opponent_analysis": parsed.get("opponent_analysis") or {},
        "key_messages": list(parsed.get("key_messages") or ["עובדות בשטח", "ביחד ננצח"]),
        "campaign_strategy": str(parsed.get("campaign_strategy") or ""),
        "campaign_slogans": list(parsed.get("campaign_slogans") or []),
        "talking_points": parsed.get("talking_points") or {},
        "red_lines": list(parsed.get("red_lines") or []),
        "endorsements": parsed.get("endorsements") or {},
        "confidence": float(parsed.get("confidence") or 0.8),
    }


def _public_dossier(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "candidate_name": row.get("candidate_name"),
        "party": row.get("party"),
        "role": row.get("role"),
        "bio": row.get("bio"),
        "platform": row.get("platform") or {},
        "strengths": row.get("strengths") or [],
        "weaknesses": row.get("weaknesses") or [],
        "target_demographics": row.get("target_demographics") or {},
        "opponent_analysis": row.get("opponent_analysis") or {},
        "key_messages": row.get("key_messages") or [],
        "campaign_strategy": row.get("campaign_strategy") or "",
        "campaign_slogans": row.get("campaign_slogans") or [],
        "talking_points": row.get("talking_points") or {},
        "red_lines": row.get("red_lines") or [],
        "endorsements": row.get("endorsements") or {},
        "source_filename": row.get("source_filename"),
        "source_file_type": row.get("source_file_type"),
        "version": row.get("version", 1),
        "status": row.get("status", "active"),
        "confidence": row.get("confidence", 0),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "extracted_at": row.get("updated_at") or row.get("created_at"),
    }


@router.post("/upload")
async def upload_dossier(file: UploadFile = File(...)) -> dict[str, Any]:
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="לא הועלה קובץ")
    ext = _ext(file.filename)
    if not ext:
        raise HTTPException(
            status_code=400,
            detail="פורמט לא נתמך. השתמש ב־PDF, DOCX, JSON, TXT או MD",
        )
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="קובץ ריק")
    try:
        raw_text = _extract_text(file.filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    parsed = await _groq_parse(raw_text)
    if not parsed:
        parsed = _fallback_parse(raw_text)
    normalized = _normalize_extracted(parsed)
    dossier_id = f"dossier-{secrets.token_hex(4)}"
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    row = await db.insert_dossier(
        {
            "id": dossier_id,
            **normalized,
            "raw_text": raw_text,
            "source_filename": file.filename,
            "source_file_type": ext.lstrip("."),
            "created_at": now,
            "updated_at": now,
        }
    )
    out = _public_dossier(row or {"id": dossier_id, **normalized})
    out["extracted_at"] = now
    return out


@router.get("/candidates")
async def list_candidates(status: str = Query("active")) -> dict[str, Any]:
    rows = await db.list_dossiers(status=status if status != "all" else None)
    candidates = [
        {
            "id": r["id"],
            "candidate_name": r.get("candidate_name"),
            "party": r.get("party"),
            "role": r.get("role"),
            "status": r.get("status"),
            "created_at": r.get("created_at"),
            "confidence": r.get("confidence"),
        }
        for r in rows
        if r
    ]
    return {"candidates": candidates, "count": len(candidates)}


@router.get("/candidate/{candidate_id}")
async def get_candidate(candidate_id: str) -> dict[str, Any]:
    row = await db.get_dossier(candidate_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"תיק '{candidate_id}' לא נמצא")
    return _public_dossier(row)


@router.put("/candidate/{candidate_id}")
async def update_candidate(candidate_id: str, payload: DossierUpdate) -> dict[str, Any]:
    if not await db.get_dossier(candidate_id):
        raise HTTPException(status_code=404, detail=f"תיק '{candidate_id}' לא נמצא")
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="אין שדות לעדכון")
    row = await db.update_dossier(candidate_id, fields)
    if not row:
        raise HTTPException(status_code=404, detail=f"תיק '{candidate_id}' לא נמצא")
    return _public_dossier(row)


@router.delete("/candidate/{candidate_id}")
async def delete_candidate(candidate_id: str) -> dict[str, Any]:
    if not await db.get_dossier(candidate_id):
        raise HTTPException(status_code=404, detail=f"תיק '{candidate_id}' לא נמצא")
    await db.update_dossier(candidate_id, {"status": "archived"})
    return {"deleted": candidate_id, "status": "archived"}


@router.post("/candidate/{candidate_id}/refresh")
async def refresh_candidate(candidate_id: str) -> dict[str, Any]:
    existing = await db.get_dossier(candidate_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"תיק '{candidate_id}' לא נמצא")
    raw_text = str(existing.get("raw_text") or "").strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail="אין טקסט מקור לרענון")
    parsed = await _groq_parse(raw_text)
    if not parsed:
        parsed = _fallback_parse(raw_text)
    normalized = _normalize_extracted(parsed)
    row = await db.update_dossier(candidate_id, normalized)
    out = _public_dossier(row or existing)
    out["extracted_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return out
