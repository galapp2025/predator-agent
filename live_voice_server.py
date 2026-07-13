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
from typing import Any, Dict, List, Optional

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
# Railway מספק PORT; מקומית ברירת מחדל 8766
PORT = int(os.getenv("PORT") or os.getenv("VOICE_PORT", "8766"))
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
CARTESIA_API_KEY = os.getenv("CARTESIA_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
VOICE_MALE = os.getenv("CARTESIA_VOICE_MALE", "ff857c8e-e7f9-4afd-af42-dce9f3c5ab02")
VOICE_FEMALE = os.getenv("CARTESIA_VOICE_FEMALE", "3e32f3c5-9ac0-4192-9994-87fdb277120f")
CARTESIA_VERSION = os.getenv("CARTESIA_VERSION", "2024-11-13")
# Cartesia free/starter limit = 2 concurrent — שומרים 1 לסשן קול
TTS_SEMAPHORE = asyncio.Semaphore(1)
TTS_MAX_RETRIES = int(os.getenv("CARTESIA_TTS_RETRIES", "3"))
# אחרי 402 — מדלגים על Cartesia לזמן מה (חוסך ~400ms לכל תור)
_cartesia_skip_until = 0.0
TTS_PROVIDER = (os.getenv("TTS_PROVIDER") or "local").strip().lower()  # local=<1s ; openai/cartesia=איכות
GROQ_VOICE_MODEL = os.getenv("GROQ_VOICE_MODEL", "llama-3.1-8b-instant")

# Deepgram — endpointing אגרסיבי לתגובה מהירה לסוף דיבור
DG_URL = (
    "wss://api.deepgram.com/v1/listen"
    "?model=nova-3&language=he&encoding=linear16&sample_rate=16000"
    "&channels=1&punctuate=false&interim_results=true"
    "&endpointing=100&utterance_end_ms=1000&vad_events=true&smart_format=false"
)

# אישור speechSynthesis הוסר — קול אחר = מרגיש רובוטי


def _clip_spoken_reply(text: str, max_words: int = 16) -> str:
    """מנקה תשובות מתסריט ושומר אורך טלפוני טבעי."""
    t = (text or "").strip()
    t = re.sub(r"\[.*?\]", "", t)
    t = re.sub(r"\(.*?\)", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"אני אגיד לך בדיוק[,.]?\s*", "", t)
    # הסר פתיחות תסריט חוזרות
    for _ in range(3):
        cleaned = re.sub(
            r"^(תקשיב[,.]?\s*|תשמע[,.]?\s*|העניין הוא פשוט[,.]?\s*|"
            r"אני אגיד לך בדיוק מה המצב[.!]?\s*|בוא נראה[,.]?\s*|"
            r"הנתונים מראים ש?—?\s*|אוקיי[,.]?\s*סבבה[,.]?\s*)",
            "",
            t,
            flags=re.IGNORECASE,
        ).strip()
        if cleaned == t:
            break
        t = cleaned
    parts = re.split(r"(?<=[.!?…])\s+", t)
    if len(parts) > 2:
        t = " ".join(parts[:2]).strip()
    words = t.split()
    if len(words) > max_words:
        t = " ".join(words[:max_words]).rstrip(",;") + "."
    return t or "אני כאן, תגיד."


def pcm16_to_wav(pcm: bytes, sample_rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def humanize_for_tts(text: str) -> str:
    """טקסט נקי ל-TTS — בלי SSML breaks שנשמעים סינתטיים."""
    t = (text or "").strip()
    t = re.sub(r"\[.*?\]", "", t)
    t = re.sub(r"\(.*?\)", "", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("—", ",").replace(" - ", ", ")
    t = re.sub(r"\s+", " ", t).strip()
    return t[:320]


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
        self._pending_utterance: Optional[str] = None
        self.ua = ""
        self._last_final_text: Optional[str] = None
        self._last_final_at = 0.0
        self._commit_lock = asyncio.Lock()
        self._last_speech_final_at = 0.0
        self._speaking_until = 0.0  # חוסם הד ממיקרופון בזמן שהסוכן מדבר
        self._partial_commit_task: Optional[asyncio.Task] = None
        self._last_stt_at = 0.0
        self._keepalive_task: Optional[asyncio.Task] = None
        self._stt_stall_restarts = 0

    async def send_json(self, payload: dict) -> None:
        if not self.ws.closed:
            await self.ws.send_json(payload)

    def _touch(self) -> None:
        self._last_activity = time.time()

    async def start_agent_session(self, voter: Optional[dict] = None) -> None:
        from src.enrichment.voter_context import VoterContextBuilder
        from src.llm.prompt_builder import PERSONA_AGENT_NAME

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
                gender=voter.get("gender") or "",
            )
        session = self.agent.create_session(self.session_id, voter_context=ctx, phone=phone)
        self._agent_ready = True
        self._touch()
        self._silence_task = None
        agent_name = PERSONA_AGENT_NAME.get(session.current_persona, "דוד")
        await self.send_json(
            {
                "type": "ready",
                "session_id": self.session_id,
                "agent_name": agent_name,
                "persona": session.current_persona,
                "voter_name": (ctx.first_name if ctx else "") or "",
                "voter_gender": (ctx.gender if ctx else "") or "",
            }
        )

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
                                if TTS_PROVIDER in {"local", "browser", "webkit"}:
                                    await self.send_json(
                                        {
                                            "type": "speak_local",
                                            "text": probe["reply"],
                                            "lang": "he-IL",
                                        }
                                    )
                                else:
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
                                await self.send_json(
                                    {
                                        "type": "speak_local",
                                        "text": probe["reply"],
                                        "lang": "he-IL",
                                    }
                                )
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
            if self._keepalive_task:
                self._keepalive_task.cancel()
            self._keepalive_task = asyncio.create_task(self._dg_keepalive())
            self._last_stt_at = time.time()
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

    async def _dg_keepalive(self) -> None:
        """שומר את חיבור Deepgram חי — מונע 'תקיעה' בלי finals."""
        try:
            while self._agent_ready and self.dg_ws and not self.dg_ws.closed:
                await asyncio.sleep(5.0)
                if self.dg_ws and not self.dg_ws.closed:
                    try:
                        await self.dg_ws.send_json({"type": "KeepAlive"})
                    except Exception:
                        break
        except asyncio.CancelledError:
            return

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
        finally:
            log.warning("[%s] Deepgram pump ended — will reconnect on next audio", self.session_id)
            self.dg_ws = None

    async def _on_dg_message(self, data: dict) -> None:
        if not isinstance(data, dict):
            return
        typ = data.get("type")
        if typ == "Error" or data.get("error"):
            msg = data.get("message") or data.get("description") or data.get("error") or str(data)
            log.error("[%s] Deepgram error: %s", self.session_id, msg)
            await self.send_json({"type": "error", "message": f"Deepgram: {msg}"})
            return

        if typ == "SpeechStarted":
            await self.send_json({"type": "barge_in"})
            self._speaking_until = 0.0  # מאפשר barge-in מיידי
            return

        if typ == "UtteranceEnd":
            if self._partial.strip():
                await self._commit_utterance(self._partial.strip(), source="utterance_end")
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

        speech_final = bool(data.get("speech_final"))
        is_final = bool(data.get("is_final") or speech_final)
        self._partial = text
        self._last_stt_at = time.time()
        self._touch()

        if is_final or speech_final:
            if self._partial_commit_task:
                self._partial_commit_task.cancel()
                self._partial_commit_task = None
            log.info("[%s] STT final: %s", self.session_id, text[:80])
            await self.send_json({"type": "transcript", "text": text, "is_final": True})
            await self._commit_utterance(text, source="final" if is_final else "speech_final")
            return

        # interim — מציגים + מתחייבים אחרי 380ms בלי עדכון (לייטנסי נמוך)
        await self.send_json({"type": "transcript", "text": text, "is_final": False})
        if self._partial_commit_task:
            self._partial_commit_task.cancel()

        async def _eager_commit(snapshot: str) -> None:
            try:
                await asyncio.sleep(0.25)
                if self._partial == snapshot and len(snapshot.split()) >= 2:
                    log.info("[%s] STT eager: %s", self.session_id, snapshot[:80])
                    await self.send_json({"type": "transcript", "text": snapshot, "is_final": True})
                    await self._commit_utterance(snapshot, source="eager")
            except asyncio.CancelledError:
                return

        self._partial_commit_task = asyncio.create_task(_eager_commit(text))

    async def _commit_utterance(self, text: str, *, source: str = "final") -> None:
        text = (text or "").strip()
        if not text or not self._agent_ready:
            return
        # בזמן דיבור הסוכן — מתעלמים מהד קצר בלבד
        if time.time() < self._speaking_until:
            words = text.split()
            if len(words) <= 2 and source in {"utterance_end", "eager"}:
                return
            if len(words) <= 1:
                return
        run_now = False
        async with self._commit_lock:
            now = time.time()
            last = getattr(self, "_last_final_text", None) or ""
            if last and (now - getattr(self, "_last_final_at", 0)) < 0.55:
                if text == last or (text.startswith(last) and len(text) - len(last) < 12):
                    if len(text) <= len(last) + 1:
                        return
            if len(text) < 2 or text in {"א", "אה", "ה", "מה", "מה מה", "ממ", "אוקיי"}:
                return
            self._last_final_text = text
            self._last_final_at = now
            self._partial = ""
            if self.busy:
                self._pending_utterance = text
                log.info("[%s] queued (%s): %s", self.session_id, source, text[:80])
                return
            run_now = True
        if run_now:
            log.info("[%s] commit (%s): %s", self.session_id, source, text[:80])
            await self._drain_pipeline(text)

    async def _drain_pipeline(self, text: str) -> None:
        self.busy = True
        try:
            await self._run_pipeline(text)
        finally:
            self.busy = False
            self._partial = ""
            self._touch()
            pending = getattr(self, "_pending_utterance", None)
            self._pending_utterance = None
            if pending and self._agent_ready:
                log.info("[%s] draining queued: %s", self.session_id, pending[:80])
                await self._drain_pipeline(pending)

    async def forward_audio(self, pcm: bytes) -> None:
        if not pcm:
            return
        self._touch()
        self._audio_bytes += len(pcm)
        self._audio_chunks += 1
        # אם יש אודיו אבל אין STT 8+ שניות — Deepgram תקוע, מחברים מחדש
        if (
            self._audio_chunks % 80 == 0
            and self._last_stt_at
            and (time.time() - self._last_stt_at) > 8.0
            and not self.busy
            and self._stt_stall_restarts < 4
        ):
            self._stt_stall_restarts += 1
            log.warning(
                "[%s] STT stall (%.0fs) — reconnect Deepgram #%d",
                self.session_id,
                time.time() - self._last_stt_at,
                self._stt_stall_restarts,
            )
            try:
                if self.dg_ws and not self.dg_ws.closed:
                    await self.dg_ws.close()
            except Exception:
                pass
            self.dg_ws = None
            await self.connect_deepgram()

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
        if not self.dg_ws or self.dg_ws.closed:
            if len(self._pcm_buf) < 80:
                self._pcm_buf.append(pcm)
            await self.connect_deepgram()
        if self.dg_ws and not self.dg_ws.closed:
            await self.dg_ws.send_bytes(pcm)
        else:
            if len(self._pcm_buf) < 80:
                self._pcm_buf.append(pcm)

    async def _run_pipeline(self, voter_text: str) -> None:
        t0 = time.time()
        await self.send_json({"type": "status", "stage": "predator"})
        turn = await self.agent.process_voter_turn(
            self.session_id,
            voter_text,
            compact_prompt=True,
            skip_slow_llm=True,
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

        reply = _clip_spoken_reply(reply, max_words=14)
        self.agent.add_assistant_response(self.session_id, reply)

        llm_ms = int((time.time() - t0) * 1000)
        await self.send_json(
            {
                "type": "pipeline",
                "stt": voter_text,
                "disc": turn.get("disc"),
                "state": turn.get("state"),
                "persona": turn.get("persona"),
                "llm": reply,
                "latency_ms": llm_ms,
            }
        )

        # נתיב <1s: דיבור מקומי בדפדפן (OpenAI TTS ~4s — לא עומד ביעד)
        if TTS_PROVIDER in {"local", "browser", "webkit"}:
            approx_sec = max(0.5, min(3.0, 0.28 * max(1, len(reply.split()))))
            self._speaking_until = time.time() + approx_sec
            total_ms = int((time.time() - t0) * 1000)
            await self.send_json(
                {
                    "type": "speak_local",
                    "text": reply,
                    "lang": "he-IL",
                    "latency_ms": total_ms,
                }
            )
            log.info("[%s] turn done in %dms (local-TTS) reply=%r", self.session_id, total_ms, reply[:60])
            await self.send_json({"type": "status", "stage": "idle"})
            return

        await self.send_json({"type": "status", "stage": "tts"})
        try:
            audio_b64, sr = await self._tts(reply, turn.get("tts_params") or {})
        except Exception as e:
            log.error("TTS failed: %s — speak_local fallback", e)
            await self.send_json({"type": "speak_local", "text": reply, "lang": "he-IL"})
            await self.send_json({"type": "status", "stage": "idle"})
            return
        approx_sec = max(0.6, min(3.5, 0.22 * max(1, len(reply.split()))))
        self._speaking_until = time.time() + approx_sec
        await self.send_json(
            {"type": "audio", "format": "wav", "sample_rate": sr, "data": audio_b64, "text": reply}
        )
        log.info(
            "[%s] turn done in %dms reply=%r",
            self.session_id,
            int((time.time() - t0) * 1000),
            reply[:60],
        )
        await self.send_json({"type": "status", "stage": "idle"})

    async def _llm_reply(self, system_prompt: str, user_text: str) -> str:
        from src.agent.predator import TURN_BUDGET_SEC
        from src.llm.fast_llm import FastLLM

        llm = FastLLM(
            temperature=0.85,
            max_tokens=36,
            top_p=0.9,
            groq_model=GROQ_VOICE_MODEL,
        )
        if llm.provider == "none":
            return "אני כאן, תגיד."
        history: List[Dict[str, str]] = []
        sess = self.agent.active_sessions.get(self.session_id)
        voter_name = ""
        voter_gender = ""
        agent_name = ""
        if sess:
            if sess.voter_context:
                voter_name = sess.voter_context.first_name or ""
                voter_gender = sess.voter_context.gender or ""
            from src.llm.prompt_builder import PERSONA_AGENT_NAME

            agent_name = PERSONA_AGENT_NAME.get(sess.current_persona, "")
            if sess.conversation_history:
                for h in sess.conversation_history[:-1][-4:]:
                    role = h.get("role")
                    content = (h.get("content") or "").strip()
                    if role in ("user", "assistant") and content:
                        history.append({"role": role, "content": content[:140]})
        if voter_gender == "female":
            g_hint = f"פנה ל-{voter_name or 'הבוחרת'} בנקבה (את/שלך)."
        elif voter_gender == "male":
            g_hint = f"פנה ל-{voter_name or 'הבוחר'} בזכר (אתה/שלך)."
        else:
            g_hint = f"השם: {voter_name or 'לא ידוע'}."
        tiny_system = (
            f"אתה {agent_name or 'נציג'} מהמטה בטלפון. עברית מדוברת. "
            f"{g_hint} משפט אחד, עד 12 מילים. בלי סיסמאות."
        )
        return await llm.reply(
            tiny_system,
            user_text,
            self.http,
            timeout_sec=min(3.5, float(TURN_BUDGET_SEC)),
            history=history,
        )

    async def _tts(self, text: str, tts_params: dict) -> tuple[str, int]:
        global _cartesia_skip_until
        spoken = humanize_for_tts(text)
        if not spoken:
            raise RuntimeError("empty TTS text")
        # local handled in pipeline; here only server providers
        prefer_openai = TTS_PROVIDER in {"openai", "oa"} or time.time() < _cartesia_skip_until
        if prefer_openai or TTS_PROVIDER == "local":
            if TTS_PROVIDER == "local":
                raise RuntimeError("local TTS path")
            return await self._tts_openai(spoken, tts_params)
        try:
            return await self._tts_cartesia(spoken, tts_params)
        except Exception as e:
            msg = str(e).lower()
            if any(x in msg for x in ("402", "insufficient credits", "credit", "401", "403")):
                _cartesia_skip_until = time.time() + 3600
                log.warning("Cartesia disabled 1h (%s) — OpenAI TTS", e)
                return await self._tts_openai(spoken, tts_params)
            raise

    async def _tts_openai(self, spoken: str, tts_params: dict) -> tuple[str, int]:
        if not OPENAI_API_KEY:
            raise RuntimeError("OpenAI TTS fallback: OPENAI_API_KEY missing")
        voice_id = tts_params.get("voice_id") or VOICE_MALE
        oa_voice = "nova" if voice_id == VOICE_FEMALE else "onyx"
        # tts-1 מהיר יותר מ-gpt-4o-mini-tts לשיחה חיה
        model = os.getenv("OPENAI_TTS_MODEL", "tts-1")
        sample_rate = 24000
        t0 = time.time()
        async with TTS_SEMAPHORE:
            async with self.http.post(
                "https://api.openai.com/v1/audio/speech",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "voice": oa_voice,
                    "input": spoken[:280],
                    "response_format": "wav",
                    "speed": float(max(0.97, min(1.05, float(tts_params.get("speed") or 1.0)))),
                },
                timeout=aiohttp.ClientTimeout(total=25),
            ) as resp:
                raw = await resp.read()
                if resp.status >= 400:
                    raise RuntimeError(f"OpenAI TTS {resp.status}: {raw[:160]!r}")
                if len(raw) < 100:
                    raise RuntimeError("OpenAI TTS empty audio")
                log.info(
                    "TTS ok provider=openai model=%s voice=%s bytes=%d ms=%d",
                    model,
                    oa_voice,
                    len(raw),
                    int((time.time() - t0) * 1000),
                )
                return base64.b64encode(raw).decode("ascii"), sample_rate

    async def _tts_cartesia(self, spoken: str, tts_params: dict) -> tuple[str, int]:
        voice_id = tts_params.get("voice_id") or VOICE_MALE
        # קצב שיחה טבעי — בלי קיצוניות
        speed = float(tts_params.get("speed") or 1.0)
        speed = max(0.95, min(1.03, speed))
        sample_rate = 24000
        volume = float(tts_params.get("volume") or 1.0)
        gen: Dict[str, Any] = {
            "speed": speed,
            "volume": max(0.85, min(1.15, volume)),
        }
        emotion = (tts_params.get("emotion") or "").strip().lower()
        if emotion and emotion not in {"confident", "content", "angry", "excited"}:
            gen["emotion"] = emotion
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
                        if resp.status == 402 or b"Insufficient credits" in raw:
                            raise RuntimeError("402: Insufficient Cartesia credits")
                        # אל תנסה sonic-3 אחרי שגיאת קרדיטים / 4xx קבועה
                        if resp.status >= 400 and model_id != "sonic-3" and attempt == 1 and resp.status != 402:
                            if resp.status in (404, 400) or b"model" in raw.lower():
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
                            "TTS ok provider=cartesia model=%s speed=%.2f bytes=%d",
                            model_id,
                            speed,
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
        if self._keepalive_task:
            self._keepalive_task.cancel()
            self._keepalive_task = None
        if self._partial_commit_task:
            self._partial_commit_task.cancel()
            self._partial_commit_task = None
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
        demo_url = f"{request.url.scheme}://{request.host}/"
        try:
            await ws.send_json(
                {
                    "type": "error",
                    "message": f"פתחו ב-Google Chrome בלבד (לא Cursor): {demo_url}",
                }
            )
        except Exception:
            pass
        await ws.close()
        return ws

    # כמה בודקים במקביל (צוות משקיעים) — לא בועטים סשנים פעילים
    sessions: Dict[str, VoiceSession] = request.app["sessions"]
    max_sessions = int(os.getenv("MAX_VOICE_SESSIONS", "12"))
    if len(sessions) >= max_sessions:
        try:
            await ws.send_json(
                {
                    "type": "error",
                    "message": "השרת עמוס — נסו שוב בעוד דקה (יותר מדי סשנים פעילים)",
                }
            )
        except Exception:
            pass
        await ws.close()
        return ws

    agent = request.app["agent"]
    http = request.app["http"]
    session = VoiceSession(ws, agent, http)
    session.ua = ua
    sessions[session.session_id] = session
    log.info("OPS session → %s ua=%s active=%d", session.session_id, ua[:60], len(sessions))

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
                    if not text:
                        continue
                    if session.busy:
                        session._pending_utterance = text
                        await session.send_json({"type": "status", "stage": "בתור…" })
                        continue
                    session._touch()
                    try:
                        await session._drain_pipeline(text)
                    except Exception as e:
                        log.exception("pipeline failed")
                        await session.send_json({"type": "error", "message": str(e)})
                elif typ == "playback_done":
                    session._speaking_until = 0.0
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
        sessions.pop(session.session_id, None)
        await session.close()
        log.info("OPS session closed → %s active=%d", session.session_id, len(sessions))
    return ws


async def index_handler(_: web.Request) -> web.FileResponse:
    return web.FileResponse(ROOT / "ops_console.html")


async def health_handler(request: web.Request) -> web.Response:
    sessions = request.app.get("sessions") or {}
    return web.json_response(
        {
            "ok": True,
            "service": "predator-ops",
            "tts": TTS_PROVIDER,
            "sessions": len(sessions),
        }
    )


async def on_startup(app: web.Application) -> None:
    from src.agent.predator import PredatorAgent

    connector = aiohttp.TCPConnector(ssl=SSL_CTX)
    app["agent"] = PredatorAgent()
    app["http"] = aiohttp.ClientSession(connector=connector)
    app["sessions"] = {}
    missing = [k for k, v in {
        "DEEPGRAM_API_KEY": DEEPGRAM_API_KEY,
        "OPENAI_API_KEY": OPENAI_API_KEY,
        "GROQ_API_KEY": os.getenv("GROQ_API_KEY", ""),
    }.items() if not v]
    if missing:
        log.warning("Missing keys: %s", ", ".join(missing))
    log.info("PREDATOR OPS LIVE http://%s:%s tts=%s", HOST, PORT, TTS_PROVIDER)


async def on_cleanup(app: web.Application) -> None:
    await app["http"].close()


def main() -> None:
    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/test_voice.html", index_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/ws", ws_handler)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    web.run_app(app, host=HOST, port=PORT, print=lambda *a, **k: None)


if __name__ == "__main__":
    main()
