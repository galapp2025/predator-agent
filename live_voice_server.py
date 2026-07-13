#!/usr/bin/env python3
"""
Live Voice Server — WebSocket
מיקרופון → Deepgram STT (he) → Predator Pipeline → OpenAI → Cartesia Sonic-3 TTS → רמקול
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
import ssl
import struct
import time
import uuid
import wave
from pathlib import Path
from typing import Any, Dict, Optional

import aiohttp
from aiohttp import web
from dotenv import load_dotenv

try:
    import certifi

    SSL_CTX: Any = ssl.create_default_context(cafile=certifi.where())
except Exception:
    SSL_CTX = False  # macOS Python ללא CA bundle

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("live-voice")

HOST = os.getenv("VOICE_HOST", "0.0.0.0")
PORT = int(os.getenv("VOICE_PORT", "8766"))
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
CARTESIA_API_KEY = os.getenv("CARTESIA_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
VOICE_MALE = os.getenv("CARTESIA_VOICE_MALE", "ff857c8e-e7f9-4afd-af42-dce9f3c5ab02")
VOICE_FEMALE = os.getenv("CARTESIA_VOICE_FEMALE", "3e32f3c5-9ac0-4192-9994-87fdb277120f")
CARTESIA_VERSION = os.getenv("CARTESIA_VERSION", "2024-11-13")
# Cartesia free/starter limit = 2 concurrent — שומרים 1 לסשן קול
TTS_SEMAPHORE = asyncio.Semaphore(1)
TTS_MAX_RETRIES = int(os.getenv("CARTESIA_TTS_RETRIES", "6"))

# Deepgram listen (PCM s16le @ 16kHz from browser)
DG_URL = (
    "wss://api.deepgram.com/v1/listen"
    "?model=nova-3&language=he&encoding=linear16&sample_rate=16000"
    "&channels=1&punctuate=true&interim_results=true"
    "&endpointing=300&utterance_end_ms=1000&vad_events=true&smart_format=true"
)


def pcm16_to_wav(pcm: bytes, sample_rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def humanize_for_tts(text: str) -> str:
    """הפוך טקסט לדיבור טבעי יותר ל-Cartesia (הפסקות, בלי רובוטיקה)."""
    t = (text or "").strip()
    t = re.sub(r"\[.*?\]", "", t)
    t = re.sub(r"\(.*?\)", "", t)  # מחשבות/הערות במה
    t = t.replace("...", ",").replace("…", ",")
    t = t.replace(" — ", ", ").replace(" - ", ", ")
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"([.!?])\s+", r'\1 <break time="220ms"/> ', t)
    t = re.sub(r",\s+", ', <break time="90ms"/> ', t)
    return t[:500]


class VoiceSession:
    def __init__(self, ws: web.WebSocketResponse, agent, http: aiohttp.ClientSession):
        self.ws = ws
        self.agent = agent
        self.http = http
        self.session_id = f"voice-{uuid.uuid4().hex[:10]}"
        self.busy = False
        self.dg_ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._dg_task: Optional[asyncio.Task] = None
        self._silence_task: Optional[asyncio.Task] = None
        self._partial = ""
        self._last_activity = time.time()
        self._started_mono = time.time()
        self._agent_ready = False
        self._audio_bytes = 0
        self._audio_chunks = 0
        self._dg_lock = asyncio.Lock()
        self._pcm_buf: list[bytes] = []

    async def send_json(self, payload: dict) -> None:
        if not self.ws.closed:
            await self.ws.send_json(payload)

    def _touch(self) -> None:
        self._last_activity = time.time()

    async def start_agent_session(self, voter: Optional[dict] = None) -> None:
        from src.enrichment.voter_context import VoterContextBuilder

        ctx = None
        phone = ""
        if voter:
            phone = str(voter.get("phone") or "")
            ctx = VoterContextBuilder().build(
                first_name=voter.get("first_name", "בוחר"),
                last_name=voter.get("last_name", ""),
                city=voter.get("city", "פתח תקווה"),
                street=voter.get("street", ""),
                house_number=voter.get("house_number", ""),
                support_score=float(voter.get("support_score") or 0.55),
                campaign_type=voter.get("campaign_type", "primaries"),
            )
        self.agent.create_session(self.session_id, voter_context=ctx, phone=phone)
        self._agent_ready = True
        self._touch()
        # Silence probe כבוי ב-voice UI — גרם לשיחות/TTS אקראיים ולולאות
        self._silence_task = None
        await self.send_json({"type": "ready", "session_id": self.session_id})

    async def _silence_watchdog(self) -> None:
        from src.agent.predator import SILENCE_TIMEOUT_SEC

        try:
            while self._agent_ready and not self.ws.closed:
                await asyncio.sleep(0.5)
                if self.busy:
                    self._touch()
                    continue
                gap = time.time() - self._last_activity
                if gap >= SILENCE_TIMEOUT_SEC:
                    # פעם אחת בלבד לסשן — לא לולאה אינסופית
                    if getattr(self, "_silence_fired", False):
                        self._touch()
                        continue
                    probe = self.agent.handle_silence(self.session_id, gap)
                    if probe and probe.get("reply"):
                        self._silence_fired = True
                        self.busy = True
                        try:
                            await self.send_json({"type": "status", "stage": "silence"})
                            await self.send_json(
                                {
                                    "type": "pipeline",
                                    "stt": "(silence)",
                                    "llm": probe["reply"],
                                    "battle": bool(probe.get("battle")),
                                    "state": probe.get("state"),
                                    "persona": probe.get("persona"),
                                }
                            )
                            try:
                                audio_b64, sr = await self._tts(
                                    probe["reply"], probe.get("tts_params") or {}
                                )
                                await self.send_json(
                                    {
                                        "type": "audio",
                                        "format": "wav",
                                        "sample_rate": sr,
                                        "data": audio_b64,
                                        "text": probe["reply"],
                                    }
                                )
                            except Exception as e:
                                log.warning("silence TTS skipped: %s", e)
                        finally:
                            self.busy = False
                            self._touch()
        except asyncio.CancelledError:
            return

    async def connect_deepgram(self) -> bool:
        async with self._dg_lock:
            if self.dg_ws and not self.dg_ws.closed:
                return True
            if not DEEPGRAM_API_KEY:
                await self.send_json({"type": "error", "message": "DEEPGRAM_API_KEY missing — השתמש בשליחת טקסט"})
                return False
            try:
                self.dg_ws = await self.http.ws_connect(
                    DG_URL,
                    headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"},
                    heartbeat=20,
                    ssl=SSL_CTX,
                )
            except Exception as first_err:
                log.warning("[%s] Deepgram SSL failed (%s) — retry insecure", self.session_id, first_err)
                try:
                    self.dg_ws = await self.http.ws_connect(
                        DG_URL,
                        headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"},
                        heartbeat=20,
                        ssl=False,
                    )
                except Exception as e:
                    log.error("[%s] Deepgram connect failed: %s", self.session_id, e)
                    await self.send_json(
                        {
                            "type": "error",
                            "message": f"Deepgram לא התחבר ({e}). כפתור טקסט עדיין עובד.",
                        }
                    )
                    return False
            self._dg_task = asyncio.create_task(self._pump_deepgram())
            log.info("[%s] Deepgram connected", self.session_id)
            if self._pcm_buf:
                flushed = 0
                for chunk in self._pcm_buf:
                    await self.dg_ws.send_bytes(chunk)
                    flushed += len(chunk)
                self._pcm_buf.clear()
                log.info("[%s] flushed %d buffered audio bytes", self.session_id, flushed)
            await self.send_json({"type": "stt_ready"})
            return True

    async def _pump_deepgram(self) -> None:
        assert self.dg_ws is not None
        try:
            async for msg in self.dg_ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        await self._on_dg_message(data)
                    except Exception as e:
                        log.exception("[%s] Deepgram message parse: %s", self.session_id, e)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
        except Exception as e:
            log.error("[%s] Deepgram pump: %s", self.session_id, e)
            await self.send_json({"type": "error", "message": f"deepgram: {e}"})

    async def _on_dg_message(self, data: dict) -> None:
        if not isinstance(data, dict):
            return
        if data.get("type") == "Error" or data.get("error"):
            msg = data.get("message") or data.get("description") or data.get("error") or str(data)
            log.error("[%s] Deepgram error: %s", self.session_id, msg)
            await self.send_json({"type": "error", "message": f"Deepgram: {msg}"})
            return

        channel = data.get("channel")
        if isinstance(channel, list):
            channel = channel[0] if channel else {}
        if not isinstance(channel, dict):
            channel = {}

        alts = channel.get("alternatives") or []
        if isinstance(alts, dict):
            alts = [alts]
        if not isinstance(alts, list) or not alts:
            return
        first = alts[0] if isinstance(alts[0], dict) else {}
        text = (first.get("transcript") or "").strip()
        if not text:
            return

        is_final = bool(data.get("is_final") or data.get("speech_final"))
        self._partial = text
        self._touch()
        log.info("[%s] STT%s: %s", self.session_id, " final" if is_final else "", text[:80])
        await self.send_json({"type": "transcript", "text": text, "is_final": is_final})
        if not is_final or self.busy or not self._agent_ready:
            return
        # דיבאונס — מונע "שלום" כפול כל שנייה
        now = time.time()
        if text == getattr(self, "_last_final_text", None) and (now - getattr(self, "_last_final_at", 0)) < 2.5:
            return
        self._last_final_text = text
        self._last_final_at = now
        self.busy = True
        try:
            await self._run_pipeline(text)
        finally:
            self.busy = False
            self._partial = ""
            self._touch()

    async def forward_audio(self, pcm: bytes) -> None:
        if not pcm:
            return
        self._touch()
        self._audio_bytes += len(pcm)
        self._audio_chunks += 1
        if self._audio_chunks == 1 or self._audio_chunks % 50 == 0:
            log.info(
                "[%s] audio in: chunks=%d bytes=%d dg=%s",
                self.session_id,
                self._audio_chunks,
                self._audio_bytes,
                "up" if self.dg_ws and not self.dg_ws.closed else "down",
            )
            await self.send_json(
                {
                    "type": "mic_stats",
                    "chunks": self._audio_chunks,
                    "bytes": self._audio_bytes,
                }
            )
        if self.dg_ws and not self.dg_ws.closed:
            await self.dg_ws.send_bytes(pcm)
        else:
            if len(self._pcm_buf) < 80:  # ~ few seconds
                self._pcm_buf.append(pcm)

    async def _run_pipeline(self, voter_text: str) -> None:
        await self.send_json({"type": "status", "stage": "predator"})
        turn = await self.agent.process_voter_turn(
            self.session_id,
            voter_text,
            compact_prompt=True,
            skip_slow_llm=True,  # קול חי — בלי המתנה ל-Claude
        )
        if turn.get("error"):
            await self.send_json({"type": "error", "message": turn["error"]})
            return

        if turn.get("forced_reply"):
            reply = turn["forced_reply"]
            await self.send_json({"type": "status", "stage": "battle"})
        else:
            await self.send_json({"type": "status", "stage": "llm"})
            reply = await self._llm_reply(turn["system_prompt"], voter_text)

        self.agent.add_assistant_response(self.session_id, reply)

        pipeline = {
            "type": "pipeline",
            "stt": voter_text,
            "disc": turn.get("disc"),
            "state": turn.get("state"),
            "tactic": turn.get("tactic"),
            "persona": turn.get("persona"),
            "resistance": turn.get("resistance"),
            "battle": bool(turn.get("battle")),
            "whisper": bool(turn.get("whisper")),
            "forced": bool(turn.get("forced_reply")),
            "llm": reply,
            "tts_params": turn.get("tts_params") or {},
        }
        await self.send_json(pipeline)

        await self.send_json({"type": "status", "stage": "tts"})
        try:
            audio_b64, sr = await self._tts(reply, turn.get("tts_params") or {})
        except Exception as e:
            log.error("TTS failed: %s", e)
            await self.send_json(
                {
                    "type": "error",
                    "message": f"TTS נכשל ({e}). סגור טאבים כפולים של localhost:8765 ונסה שוב.",
                }
            )
            await self.send_json({"type": "status", "stage": "idle"})
            return
        await self.send_json(
            {
                "type": "audio",
                "format": "wav",
                "sample_rate": sr,
                "data": audio_b64,
                "text": reply,
            }
        )
        await self.send_json({"type": "status", "stage": "idle"})

    async def _llm_reply(self, system_prompt: str, user_text: str) -> str:
        from src.agent.predator import LLM_HEBREW_PARAMS, TURN_BUDGET_SEC
        from src.llm.fast_llm import FastLLM

        llm = FastLLM(
            temperature=float(LLM_HEBREW_PARAMS.get("temperature", 0.9)),
            max_tokens=int(LLM_HEBREW_PARAMS.get("max_tokens", 90)),
            top_p=float(LLM_HEBREW_PARAMS.get("top_p", 0.92)),
        )
        if llm.provider == "none":
            return "סבבה, אני שומע אותך. תמשיך."
        return await llm.reply(
            system_prompt,
            user_text,
            self.http,
            timeout_sec=TURN_BUDGET_SEC,
        )

    async def _tts(self, text: str, tts_params: dict) -> tuple[str, int]:
        voice_id = tts_params.get("voice_id") or VOICE_MALE
        # קצב שיחה טבעי — לא מהיר מדי (נשמע רובוטי)
        speed = float(tts_params.get("speed") or 1.0)
        speed = max(0.88, min(1.06, speed))
        sample_rate = 24000
        emotion = tts_params.get("emotion") or "calm"
        volume = float(tts_params.get("volume") or 1.0)
        gen: Dict[str, Any] = {
            "speed": speed,
            "volume": max(0.8, min(1.3, volume)),
            "emotion": emotion,
        }
        spoken = humanize_for_tts(text)
        model_id = os.getenv("CARTESIA_TTS_MODEL", "sonic-3.5")
        req = {
            "model_id": model_id,
            "transcript": spoken,
            "voice": {"mode": "id", "id": voice_id},
            "language": "he",
            "output_format": {
                "container": "wav",
                "encoding": "pcm_s16le",
                "sample_rate": sample_rate,
            },
            "generation_config": gen,
        }
        last_err = "unknown"
        async with TTS_SEMAPHORE:
            for attempt in range(1, TTS_MAX_RETRIES + 1):
                try:
                    async with self.http.post(
                        "https://api.cartesia.ai/tts/bytes",
                        headers={
                            "X-API-Key": CARTESIA_API_KEY,
                            "Cartesia-Version": CARTESIA_VERSION,
                            "Content-Type": "application/json",
                        },
                        json=req,
                        timeout=aiohttp.ClientTimeout(total=45),
                    ) as resp:
                        raw = await resp.read()
                        # sonic-3.5 לא זמין? נפול ל-sonic-3
                        if resp.status >= 400 and model_id != "sonic-3" and attempt == 1:
                            log.warning("Cartesia %s failed (%s) — fallback sonic-3", model_id, resp.status)
                            req["model_id"] = "sonic-3"
                            model_id = "sonic-3"
                            continue
                        if resp.status == 429:
                            last_err = f"429 concurrency (attempt {attempt})"
                            wait = min(8.0, 0.8 * attempt)
                            log.warning("Cartesia 429 — retry in %.1fs", wait)
                            await self.send_json(
                                {
                                    "type": "status",
                                    "stage": "tts",
                                    "detail": f"ממתין ל-TTS… ({attempt}/{TTS_MAX_RETRIES})",
                                }
                            )
                            await asyncio.sleep(wait)
                            continue
                        if resp.status >= 400:
                            last_err = f"{resp.status}: {raw[:200]!r}"
                            log.error("Cartesia %s", last_err)
                            raise RuntimeError(last_err)
                        if len(raw) < 100:
                            last_err = "empty audio"
                            raise RuntimeError(last_err)
                        log.info(
                            "TTS ok model=%s speed=%.2f emotion=%s bytes=%d",
                            model_id,
                            speed,
                            emotion,
                            len(raw),
                        )
                        return base64.b64encode(raw).decode("ascii"), sample_rate
                except asyncio.CancelledError:
                    raise
                except RuntimeError:
                    raise
                except Exception as e:
                    last_err = str(e)
                    log.warning("Cartesia request error: %s", e)
                    await asyncio.sleep(min(4.0, 0.5 * attempt))
        raise RuntimeError(f"Cartesia exhausted retries: {last_err}")

    async def end_and_report(self) -> None:
        if not self._agent_ready:
            return
        duration = time.time() - self._started_mono
        try:
            result = await self.agent.end_session(
                self.session_id,
                outcome="answered",
                duration_seconds=duration,
                send_whatsapp=True,
            )
            await self.send_json({"type": "session_ended", "result": {
                "final_state": result.get("final_state"),
                "whatsapp": (result.get("whatsapp") or {}).get("status"),
                "report_voter": (result.get("report") or {}).get("voter"),
            }})
        except Exception as e:
            log.error("end_session failed: %s", e)

    async def close(self) -> None:
        self._agent_ready = False
        self.busy = True  # חוסם תורות/TTS נוספים
        if self._silence_task:
            self._silence_task.cancel()
            self._silence_task = None
        # לא מריצים end_session/TTS אחרי ניתוק — מונע רעש ברקע
        if self.dg_ws and not self.dg_ws.closed:
            try:
                await self.dg_ws.send_json({"type": "CloseStream"})
            except Exception:
                pass
            try:
                await self.dg_ws.close()
            except Exception:
                pass
        if self._dg_task:
            self._dg_task.cancel()
            self._dg_task = None


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(max_msg_size=4 * 1024 * 1024, heartbeat=30)
    await ws.prepare(request)

    ua = request.headers.get("User-Agent", "")
    # Cursor Simple Browser הורג סשנים + אין מיקרופון אמיתי
    if "Cursor/" in ua:
        log.warning("reject Cursor browser UA — mic will not work")
        try:
            await ws.send_json(
                {
                    "type": "error",
                    "message": "אסור לפתוח מתוך Cursor. סגור את החלונית ופתח רק Google Chrome: http://localhost:8766/",
                }
            )
        except Exception:
            pass
        await ws.close()
        return ws

    # סשן מבצעי יחיד — מעיף חיבור Chrome ישן בלבד
    prev: Optional[VoiceSession] = request.app.get("active_session")
    if prev is not None:
        try:
            await prev.send_json(
                {
                    "type": "kicked",
                    "message": "סשן חדש תפס את הקו — סגור טאבים כפולים ב-Chrome",
                }
            )
        except Exception:
            pass
        try:
            await prev.close()
        except Exception:
            pass
        try:
            if not prev.ws.closed:
                await prev.ws.close()
        except Exception:
            pass
        request.app["active_session"] = None

    agent = request.app["agent"]
    http = request.app["http"]
    session = VoiceSession(ws, agent, http)
    request.app["active_session"] = session
    log.info("OPS session → %s ua=%s", session.session_id, ua[:60])

    try:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                typ = data.get("type")
                if typ == "start":
                    await session.start_agent_session(data.get("voter"))
                elif typ == "start_stt":
                    ok = await session.connect_deepgram()
                    await session.send_json({"type": "stt_status", "ok": ok})
                elif typ == "ping":
                    await session.send_json({"type": "pong", "t": time.time()})
                elif typ == "text":
                    text = (data.get("text") or "").strip()
                    if not session._agent_ready:
                        await session.send_json({"type": "error", "message": "session not ready"})
                        continue
                    if text and not session.busy:
                        session._touch()
                        session.busy = True
                        try:
                            await session._run_pipeline(text)
                        except Exception as e:
                            log.exception("pipeline failed")
                            await session.send_json({"type": "error", "message": str(e)})
                        finally:
                            session.busy = False
                            session._touch()
                elif typ == "stop":
                    break
            elif msg.type == aiohttp.WSMsgType.BINARY:
                if not session.dg_ws or session.dg_ws.closed:
                    await session.connect_deepgram()
                await session.forward_audio(msg.data)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                break
    finally:
        if request.app.get("active_session") is session:
            request.app["active_session"] = None
        await session.close()
        log.info("OPS session closed → %s", session.session_id)
    return ws


async def index_handler(_: web.Request) -> web.FileResponse:
    return web.FileResponse(ROOT / "ops_console.html")


async def on_startup(app: web.Application) -> None:
    from src.agent.predator import PredatorAgent

    connector = aiohttp.TCPConnector(ssl=SSL_CTX)
    app["agent"] = PredatorAgent()
    app["http"] = aiohttp.ClientSession(connector=connector)
    app["active_session"] = None
    missing = [k for k, v in {
        "DEEPGRAM_API_KEY": DEEPGRAM_API_KEY,
        "CARTESIA_API_KEY": CARTESIA_API_KEY,
        "OPENAI_API_KEY": OPENAI_API_KEY,
        "GROQ_API_KEY": os.getenv("GROQ_API_KEY", ""),
    }.items() if not v]
    if missing:
        log.warning("Missing keys: %s", ", ".join(missing))
    log.info("PREDATOR OPS LIVE http://%s:%s", HOST, PORT)


async def on_cleanup(app: web.Application) -> None:
    await app["http"].close()


def main() -> None:
    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/test_voice.html", index_handler)
    app.router.add_get("/ws", ws_handler)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    web.run_app(app, host=HOST, port=PORT, print=lambda *a, **k: None)


if __name__ == "__main__":
    main()
