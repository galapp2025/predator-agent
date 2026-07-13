#!/usr/bin/env python3
"""
🎙 PREDATOR AGENT — RAILWAY SERVER
═══════════════════════════════════════════════════════════════
שרת HTTP + WebSocket משולב עבור Railway:
  /           → test_voice.html (דפדפן)
  /ws         → WebSocket (צינור קולי)
  /health     → בדיקת מצב

LLM: Groq (llama-3.3-70b) > OpenAI (gpt-4.1-mini) > fallback
"""

import asyncio
import base64
import json
import logging
import os
import random
import sys
import time
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import websockets
from websockets import Response, Headers
from websockets.asyncio.server import serve
from dotenv import load_dotenv
load_dotenv()

from src.agent.predator import PredatorAgent
from src.enrichment.voter_context import VoterContextBuilder
from src.personas.persona_base import get_persona

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("voice-server")

# ── Configuration ───────────────────────────────────────
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
CARTESIA_API_KEY = os.getenv("CARTESIA_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

CARTESIA_VOICE_MALE = os.getenv("CARTESIA_VOICE_MALE", "ff857c8e-e7f9-4afd-af42-dce9f3c5ab02")
CARTESIA_VOICE_FEMALE = os.getenv("CARTESIA_VOICE_FEMALE", "3e32f3c5-9ac0-4192-9994-87fdb277120f")

DEEPGRAM_WS_URL = "wss://api.deepgram.com/v1/listen"
CARTESIA_TTS_URL = "https://api.cartesia.ai/tts/bytes"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

SAMPLE_RATE = 16000
PORT = int(os.getenv("PORT", "8765"))


def _is_real_key(key: str) -> bool:
    if not key or len(key) < 15:
        return False
    if "xxx" in key.lower():
        return False
    return True


# ── Test voter context ──────────────────────────────────
TEST_VOTER = {
    "first_name": "אורי", "last_name": "כהן", "city": "תל אביב",
    "street": "אבן גבירול", "house_number": "45",
    "registered_branch": "תל אביב", "support_score": 0.55,
    "campaign_type": "primaries",
}


# ═══════════════════════════════════════════════════════════
# RICH FALLBACK RESPONSES
# ═══════════════════════════════════════════════════════════
FALLBACK_RESPONSES = {
    "greeting": [
        "שלום, כאן [שם] מהקמפיין של [מועמד]. מדבר אורי?",
        "היי, טוב לשמוע אותך. זה [שם] מצוות השטח.",
        "אהלן, מה שלומך? שמח שהצלחתי לתפוס אותך.",
    ],
    "exploration": [
        "תגיד, מה הכי חשוב לך בבחירות האלה?",
        "מה מעצבן אותך בשכונה? דבר איתי ישר.",
        "אם היית יכול לשנות דבר אחד בעיר — מה זה היה?",
        "איך נראית השכונה שלך בבוקר? אני שואל ברצינות.",
    ],
    "engagement": [
        "אני שומע אותך. תראה, [מועמד] בדיוק על זה מדבר.",
        "נכון. ובדיוק בגלל זה אנחנו פה. רוצה לשמוע את התוכנית?",
        "מסכים איתך לגמרי. בוא נדבר פתרונות.",
    ],
    "closing": [
        "אז נדבר שוב ביום שלישי?",
        "שולח לך עכשיו פרטים לווצאפ. תסתכל ותחזור אליי.",
        "תודה על השיחה, היה כיף. יאללה, בהצלחה.",
    ],
}


# ═══════════════════════════════════════════════════════════
# Voice Agent Session (per connection)
# ═══════════════════════════════════════════════════════════

class VoiceAgentSession:
    def __init__(self, agent, builder):
        self.agent = agent
        self.builder = builder
        self.session_id = None
        self.deepgram_ws = None
        self.pending_response = False
        self._last_response = None
        self._last_groq_time = 0
        self._last_bot_turn = 0
        self._silence_start = time.time()

    async def start(self):
        ctx = self.builder.build(**TEST_VOTER)
        session_id_str = f"ws-{id(self)}"
        self.agent.create_session(session_id_str, voter_context=ctx)
        self.session_id = session_id_str
        print(f"\n📋 Session: {self.session_id[:12]}... — {ctx.first_name} {ctx.last_name}")

    async def feed_audio(self, raw_audio: bytes):
        if not self.deepgram_ws or not self.deepgram_ws.open:
            return
        try:
            await self.deepgram_ws.send(raw_audio)
        except Exception:
            pass

    async def _process_voter_turn(self, voter_text: str):
        self.pending_response = True
        self._silence_start = time.time()
        print(f"\n🎤 בוחר: {voter_text[:80]}")

        try:
            result = await self.agent.process_voter_turn(self.session_id, voter_text)
        except Exception as e:
            logger.error(f"Pipeline error: {e}")
            self.pending_response = False
            return

        state = result.get("state", "exploration")
        resistance = result.get("resistance", "low")
        disc = result.get("disc", "I")
        tactic = result.get("tactic", "reciprocity")
        persona_key = result.get("persona", "daniel")
        persona_obj = get_persona(persona_key)
        system_prompt = result.get("system_prompt", "")
        tts_speed = result.get("tts_params", {}).get("speed", 1.0)

        # ── Generate response ──
        t0 = time.time()
        agent_text = await self._generate_llm_response(system_prompt, voter_text)

        if not agent_text:
            pool = FALLBACK_RESPONSES.get(state, FALLBACK_RESPONSES["exploration"])
            agent_text = random.choice(pool)
            agent_text = agent_text.replace("[שם]", persona_obj.name).replace("[מועמד]", os.getenv("CANDIDATE_NAME", "המועמד"))

        prompt_len = len(system_prompt)

        # ── TTS ──
        voice_id = persona_obj.voice_id
        tts_start = time.time()
        audio_data = await self._synthesize_speech(agent_text, voice_id, tts_speed)
        tts_time = (time.time() - tts_start) * 1000

        total_time = (time.time() - t0) * 1000
        print(f"   🤖 ({total_time:.0f}ms): {agent_text[:80]}")
        if audio_data:
            print(f"   🔊 TTS: {len(audio_data)} bytes ({tts_time:.0f}ms)")

        self._last_response = {
            "type": "agent_response",
            "text": agent_text,
            "state": state,
            "resistance": resistance,
            "persona": persona_key,
            "persona_name": persona_obj.name,
            "tactic": tactic,
            "tts_speed": tts_speed,
            "audio": base64.b64encode(audio_data).decode("utf-8") if audio_data else None,
            "prompt_chars": prompt_len,
        }
        self.pending_response = False

    async def _generate_llm_response(self, system_prompt: str, voter_text: str) -> Optional[str]:
        now = time.time()
        groq_cooldown = 30 if not getattr(self, '_last_groq_time', 0) else \
            (30 - (now - self._last_groq_time)) if (now - self._last_groq_time) < 30 else 0

        trimmed_prompt = system_prompt
        if len(system_prompt) > 10000:
            keep_first = int(10000 * 0.6)
            keep_last = 10000 - keep_first
            trimmed_prompt = system_prompt[:keep_first] + "\n\n[...]\n\n" + system_prompt[-keep_last:]

        if _is_real_key(GROQ_API_KEY) and groq_cooldown <= 0:
            self._last_groq_time = now
            result = await self._call_llm(
                GROQ_API_URL, GROQ_API_KEY, "llama-3.3-70b-versatile",
                trimmed_prompt, voter_text
            )
            if result:
                return result

        if _is_real_key(OPENAI_API_KEY):
            return await self._call_llm(
                OPENAI_API_URL, OPENAI_API_KEY, "gpt-4.1-mini",
                system_prompt, voter_text
            )

        return None

    async def _call_llm(self, url: str, api_key: str, model: str,
                        system_prompt: str, voter_text: str) -> Optional[str]:
        try:
            import aiohttp
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            body = {
                "model": model,
                "temperature": 0.82,
                "max_tokens": 150,
                "top_p": 0.92,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": voter_text},
                ],
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, headers=headers, json=body,
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data["choices"][0]["message"]["content"].strip()
                    else:
                        text_err = await resp.text()
                        logger.error(f"LLM error {resp.status}: {text_err[:200]}")
        except Exception as e:
            logger.error(f"LLM error ({model}): {e}")
        return None

    async def _synthesize_speech(self, text: str, voice_id: str, speed: float = 1.0) -> Optional[bytes]:
        if not _is_real_key(CARTESIA_API_KEY):
            return None
        try:
            import aiohttp
            headers = {
                "X-API-Key": CARTESIA_API_KEY,
                "Cartesia-Version": "2024-06-30",
                "Content-Type": "application/json",
            }
            body = {
                "model_id": "sonic-3",
                "transcript": text,
                "voice": {"mode": "id", "id": voice_id},
                "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": 24000},
                "language": "he",
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    CARTESIA_TTS_URL, headers=headers, json=body,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        return await resp.read()
                    else:
                        text_err = await resp.text()
                        logger.error(f"Cartesia error {resp.status}: {text_err[:200]}")
        except Exception as e:
            logger.error(f"TTS error: {e}")
        return None

    @property
    def last_response(self):
        return getattr(self, "_last_response", None)

    async def close(self):
        if self.deepgram_ws and self.deepgram_ws.open:
            await self.deepgram_ws.close()
        if self.session_id:
            self.agent.end_session(self.session_id)
            print(f"\n📴 Session ended: {self.session_id[:12]}...")


# ═══════════════════════════════════════════════════════════
# HTML page (inline — Railway serves directly)
# ═══════════════════════════════════════════════════════════

def get_html() -> str:
    """Read test_voice.html with dynamic WS URL."""
    html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_voice.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    # WS_URL auto-detected in test_voice.html — no injection needed
    return html


# ═══════════════════════════════════════════════════════════
# Combined HTTP + WebSocket Handler
# ═══════════════════════════════════════════════════════════

class RailwayServer:
    def __init__(self):
        self.agent = PredatorAgent(
            anthropic_api_key=ANTHROPIC_API_KEY if _is_real_key(ANTHROPIC_API_KEY) else None,
            openai_api_key=OPENAI_API_KEY if _is_real_key(OPENAI_API_KEY) else None,
        )
        self.builder = VoterContextBuilder()
        self.sessions: dict = {}
        self._html_cache = get_html()

    async def handler(self, connection, request):
        """HTTP + WebSocket handler for websockets 14+."""
        path = request.path

        # Health check
        if path == "/health":
            dg_ok = _is_real_key(DEEPGRAM_API_KEY)
            cart_ok = _is_real_key(CARTESIA_API_KEY)
            groq_ok = _is_real_key(GROQ_API_KEY)
            openai_ok = _is_real_key(OPENAI_API_KEY)
            return Response(
                200, "OK",
                Headers({"Content-Type": "application/json"}),
                json.dumps({
                    "deepgram": dg_ok,
                    "cartesia": cart_ok,
                    "groq": groq_ok,
                    "openai": openai_ok,
                    "llm_ready": groq_ok or openai_ok,
                    "demo_ready": dg_ok and cart_ok and (groq_ok or openai_ok),
                }).encode()
            )

        # Serve HTML for root
        if path == "/" or path == "/index.html":
            return Response(
                200, "OK",
                Headers({"Content-Type": "text/html; charset=utf-8"}),
                self._html_cache.encode("utf-8")
            )

        # Everything else → WebSocket upgrade
        return None  # let websockets handle upgrade

    async def ws_handler(self, ws):
        """WebSocket connection handler."""
        client_addr = f"{ws.remote_address[0]}:{ws.remote_address[1]}"
        print(f"\n🔌 Connected: {client_addr}")

        voice = VoiceAgentSession(self.agent, self.builder)
        self.sessions[ws] = voice

        try:
            await voice.start()

            session_info = self.agent.get_session(voice.session_id)
            if session_info:
                persona = get_persona(session_info.current_persona)
                await ws.send(json.dumps({
                    "type": "session_started",
                    "session_id": voice.session_id,
                    "persona": session_info.current_persona,
                    "persona_name": persona.name,
                    "support_score": session_info.support_score,
                }, ensure_ascii=False))

            async for message in ws:
                if isinstance(message, bytes):
                    await voice.feed_audio(message)
                elif isinstance(message, str):
                    try:
                        data = json.loads(message)
                    except json.JSONDecodeError:
                        continue
                    msg_type = data.get("type", "")

                    if msg_type == "audio":
                        audio_bytes = base64.b64decode(data["data"])
                        await voice.feed_audio(audio_bytes)
                    elif msg_type == "text":
                        text = data.get("content", "")
                        if text:
                            await voice._process_voter_turn(text)
                    elif msg_type == "ping":
                        await ws.send(json.dumps({"type": "pong"}))
                    elif msg_type == "end_call":
                        print(f"\n📴 Call ended by client")
                        break

                if voice.last_response and voice.pending_response is False:
                    await ws.send(json.dumps(voice.last_response, ensure_ascii=False))
                    voice._last_response = None

        except websockets.exceptions.ConnectionClosed:
            print(f"\n🔌 Disconnected: {client_addr}")
        except Exception as e:
            logger.error(f"Session error: {e}")
        finally:
            await voice.close()
            self.sessions.pop(ws, None)

    async def start(self):
        dg_ok = _is_real_key(DEEPGRAM_API_KEY)
        cart_ok = _is_real_key(CARTESIA_API_KEY)
        groq_ok = _is_real_key(GROQ_API_KEY)
        openai_ok = _is_real_key(OPENAI_API_KEY)
        claude_ok = _is_real_key(ANTHROPIC_API_KEY)

        print()
        print("=" * 60)
        print("   🎙 PREDATOR AGENT — RAILWAY SERVER")
        print("=" * 60)
        print(f"   🌐 HTTP + WS: 0.0.0.0:{PORT}")
        print(f"   📋 Deepgram:  {'✅' if dg_ok else '⚠️'}")
        print(f"   🗣  Cartesia:  {'✅' if cart_ok else '⚠️'}")
        print(f"   🧠 Groq:      {'✅' if groq_ok else '❌'}")
        print(f"   🧠 OpenAI:    {'✅' if openai_ok else '❌'}")
        print(f"   🔍 Claude:    {'✅' if claude_ok else '⚠️'}")
        print()
        print(f"   דפדפן: https://your-app.railway.app")
        print("=" * 60)
        print()

        async with serve(
            self.ws_handler,
            host="0.0.0.0",
            port=PORT,
            process_request=self.handler,
        ):
            print(f"🟢 Server ready on port {PORT}\n")
            await asyncio.Future()


def main():
    server = RailwayServer()
    asyncio.run(server.start())


if __name__ == "__main__":
    main()
