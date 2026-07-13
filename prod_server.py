#!/usr/bin/env python3
"""
🎙 PREDATOR AGENT — PRODUCTION SERVER v2 (TWILIO READY)
═══════════════════════════════════════════════════════════════════════════
צינור מבצעי מלא: שיחת טלפון ← Twilio ← Deepgram STT ← Predator Pipeline
← LLM (Groq/OpenAI) ← Cartesia TTS ← חזרה למתקשר

Endpoints:
  GET  /                 → test_voice.html (דפדפן)
  GET  /health           → בדיקת מצב כל השירותים
  POST /twilio/voice     → Twilio inbound webhook → TwiML
  POST /twilio/status    → Twilio call status callback
  WS   /twilio/media     → Twilio Media Streams (דו-כיווני)
  WS   /ws               → WebSocket לדפדפן (טסטים)

הרצה: cd /home/user/predator-agent && python3 prod_server.py
"""

import asyncio
import base64
import json
import logging
import os
import random
import sys
import time
from typing import Optional

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from src.agent.predator import PredatorAgent
from src.personas.persona_base import get_persona

# ═══════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("predator-prod")

# ═══════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
CARTESIA_API_KEY = os.getenv("CARTESIA_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

CARTESIA_VOICE_MALE = os.getenv("CARTESIA_VOICE_MALE", "ff857c8e-e7f9-4afd-af42-dce9f3c5ab02")
CARTESIA_VOICE_FEMALE = os.getenv("CARTESIA_VOICE_FEMALE", "3e32f3c5-9ac0-4192-9994-87fdb277120f")

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")

CANDIDATE_NAME = os.getenv("CANDIDATE_NAME", "המועמד")
AGENT_MODE = os.getenv("AGENT_MODE", "campaign")
PUBLIC_URL = os.getenv("PUBLIC_URL", "")

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8765"))

DEEPGRAM_WS_URL = "wss://api.deepgram.com/v1/listen"
CARTESIA_TTS_URL = "https://api.cartesia.ai/tts/bytes"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

# ═══════════════════════════════════════════════════════════
# μ-LAW CODEC (G.711) — Pre-computed LUTs for speed
# ═══════════════════════════════════════════════════════════

_MULAW_DECODE_INT16 = np.zeros(256, dtype=np.int16)
for _i in range(256):
    _ulaw = _i
    _ulaw = ~_ulaw
    _sign = -1 if (_ulaw & 0x80) else 1
    _exponent = (_ulaw >> 4) & 0x07
    _mantissa = _ulaw & 0x0F
    _sample = _mantissa << 3
    _sample += 0x84
    _sample <<= _exponent
    _sample -= 0x84
    _sample *= _sign
    _sample = max(-32768, min(32767, _sample))
    _MULAW_DECODE_INT16[_i] = _sample

_MULAW_ENCODE_TABLE = np.zeros(65536, dtype=np.uint8)
_ULAW_SEG_THRESHOLDS = [0x100, 0x200, 0x400, 0x800, 0x1000, 0x2000, 0x4000]
for _i in range(65536):
    _sample = _i - 32768
    _mask = 0x80 if _sample < 0 else 0
    if _mask:
        _mag = -_sample
    else:
        _mag = _sample
    _mag = min(_mag, 32635) + 0x84
    _exp = 0
    for _t in reversed(_ULAW_SEG_THRESHOLDS):
        if _mag >= _t:
            _exp = _ULAW_SEG_THRESHOLDS.index(_t) + 1
            break
    _mantissa = (_mag >> (_exp + 3)) & 0x0F
    _ulaw = ~(_mask | (_exp << 4) | _mantissa)
    _MULAW_ENCODE_TABLE[_i] = _ulaw & 0xFF


def mulaw_decode(data: bytes) -> np.ndarray:
    """Decode μ-law bytes → linear PCM float32 [-1.0, 1.0]."""
    arr = np.frombuffer(data, dtype=np.uint8)
    int16 = _MULAW_DECODE_INT16[arr]
    return int16.astype(np.float32) / 32768.0


def mulaw_encode(pcm: np.ndarray) -> bytes:
    """Encode linear PCM float32 [-1.0, 1.0] → μ-law bytes."""
    pcm = np.clip(pcm, -1.0, 1.0)
    int16 = (pcm * 32767.0).astype(np.int32)
    idx = np.clip(int16 + 32768, 0, 65535)
    return _MULAW_ENCODE_TABLE[idx].tobytes()


def resample_audio(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Simple linear-interpolation resampling (numpy)."""
    if src_rate == dst_rate:
        return audio
    duration = len(audio) / src_rate
    new_len = int(duration * dst_rate)
    src_positions = np.linspace(0, len(audio) - 1, new_len)
    idx_lo = np.floor(src_positions).astype(int)
    idx_hi = np.clip(idx_lo + 1, 0, len(audio) - 1)
    frac = src_positions - idx_lo
    return audio[idx_lo] * (1 - frac) + audio[idx_hi] * frac


def pcm_to_bytes(pcm: np.ndarray, sample_width: int = 2) -> bytes:
    """Convert float32 PCM [-1,1] → int16/32-bit bytes."""
    if sample_width == 2:
        int16 = np.clip(pcm * 32767, -32768, 32767).astype(np.int16)
        return int16.tobytes()
    elif sample_width == 4:
        int32 = np.clip(pcm * 2147483647, -2147483648, 2147483647).astype(np.int32)
        return int32.tobytes()
    return pcm.tobytes()


def bytes_to_pcm(data: bytes, sample_width: int = 2) -> np.ndarray:
    """Convert int16/32-bit bytes → float32 PCM [-1,1]."""
    if sample_width == 2:
        int16 = np.frombuffer(data, dtype=np.int16)
        return int16.astype(np.float32) / 32768.0
    elif sample_width == 4:
        int32 = np.frombuffer(data, dtype=np.int32)
        return int32.astype(np.float32) / 2147483648.0
    raise ValueError(f"Unsupported sample width: {sample_width}")


# ═══════════════════════════════════════════════════════════
# UTILITY
# ═══════════════════════════════════════════════════════════

def _is_real_key(key: str) -> bool:
    if not key or len(key) < 15:
        return False
    if "xxx" in key.lower() or "placeholder" in key.lower():
        return False
    return True


def _get_public_host(request) -> str:
    """Resolve public host for TwiML WebSocket URL."""
    host = os.getenv("PUBLIC_URL", "") or os.getenv("RAILWAY_PUBLIC_DOMAIN", "")
    if not host:
        host = request.headers.get("host", f"localhost:{PORT}")
    if host.startswith("https://"):
        host = host[8:]
    elif host.startswith("http://"):
        host = host[7:]
    return host


# ═══════════════════════════════════════════════════════════
# TEST VOTER
# ═══════════════════════════════════════════════════════════
TEST_VOTER = {
    "first_name": "אורי",
    "last_name": "כהן",
    "city": "תל אביב",
    "street": "אבן גבירול",
    "house_number": "45",
    "registered_branch": "תל אביב",
    "support_score": 0.55,
    "campaign_type": "primaries",
}


# ═══════════════════════════════════════════════════════════
# FALLBACK RESPONSES — Hebrew, per state
# ═══════════════════════════════════════════════════════════
FALLBACKS = {
    "opening": [
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
    "profiling": [
        "מעניין מה שאתה אומר. תן לי לשאול אותך משהו.",
        "אני מתחיל להבין. ומה עם...?",
    ],
    "engagement": [
        "אני שומע אותך. תראה, [מועמד] בדיוק על זה מדבר.",
        "נכון. ובדיוק בגלל זה אנחנו פה. רוצה לשמוע את התוכנית?",
        "מסכים איתך לגמרי. בוא נדבר פתרונות.",
    ],
    "persuasion": [
        "תקשיב, בוא נדבר תכלס. [מועמד] עשה X, Y, Z.",
        "אני אגיד לך משהו — ואני אומר את זה בתור מישהו שבאמת מאמין.",
    ],
    "closing": [
        "אז נדבר שוב ביום שלישי?",
        "שולח לך עכשיו פרטים לווצאפ. תסתכל ותחזור אליי.",
        "תודה על השיחה, היה כיף. יאללה, בהצלחה.",
    ],
}


def _get_fallback(state: str, persona_key: str = "daniel") -> str:
    pool = FALLBACKS.get(state, FALLBACKS["exploration"])
    text = random.choice(pool)
    p = get_persona(persona_key)
    text = text.replace("[שם]", p.name).replace("[מועמד]", CANDIDATE_NAME)
    return text


# ═══════════════════════════════════════════════════════════
# PREDATOR ENGINE (shared logic for Twilio + Browser)
# ═══════════════════════════════════════════════════════════

class PredatorEngine:
    """Core engine — manages agent sessions and LLM/TTS calls."""

    def __init__(self):
        self.agent = PredatorAgent(
            anthropic_api_key=ANTHROPIC_API_KEY if _is_real_key(ANTHROPIC_API_KEY) else None,
            openai_api_key=OPENAI_API_KEY if _is_real_key(OPENAI_API_KEY) else None,
        )
        from src.enrichment.voter_context import VoterContextBuilder
        self.builder = VoterContextBuilder()
        self._last_groq_time = 0

    def create_session(self, voter_data: dict = None) -> str:
        vd = voter_data or TEST_VOTER
        ctx = self.builder.build(**vd)
        session_id = f"call-{int(time.time() * 1000)}-{random.randint(1000, 9999)}"
        self.agent.create_session(session_id, voter_context=ctx)
        return session_id

    def end_session(self, session_id: str):
        self.agent.end_session(session_id)

    async def process_text(self, session_id: str, voter_text: str) -> dict:
        result = await self.agent.process_voter_turn(session_id, voter_text)
        state = result.get("state", "exploration")
        resistance = result.get("resistance", "low")
        persona_key = result.get("persona", "daniel")
        tactic = result.get("tactic", "reciprocity")
        system_prompt = result.get("system_prompt", "")
        tts_speed = result.get("tts_params", {}).get("speed", 1.0)
        persona_obj = get_persona(persona_key)

        agent_text = await self._call_llm_chain(system_prompt, voter_text)
        if not agent_text:
            agent_text = _get_fallback(state, persona_key)

        voice_id = persona_obj.voice_id
        audio_data = await self._synthesize_tts(agent_text, voice_id, tts_speed)

        return {
            "text": agent_text,
            "audio": audio_data,
            "state": state,
            "resistance": resistance,
            "persona": persona_key,
            "persona_name": persona_obj.name,
            "tactic": tactic,
            "tts_speed": tts_speed,
            "prompt_chars": len(system_prompt),
        }

    async def _call_llm_chain(self, system_prompt: str, voter_text: str) -> Optional[str]:
        now = time.time()
        groq_cooldown = (
            30
            if not self._last_groq_time
            else max(0, 30 - (now - self._last_groq_time))
        )

        trimmed = system_prompt
        if len(system_prompt) > 10000:
            keep_first = int(10000 * 0.6)
            keep_last = 10000 - keep_first
            trimmed = system_prompt[:keep_first] + "\n\n[...]\n\n" + system_prompt[-keep_last:]

        if _is_real_key(GROQ_API_KEY) and groq_cooldown <= 0:
            self._last_groq_time = now
            result = await self._call_llm(GROQ_API_URL, GROQ_API_KEY, "llama-3.3-70b-versatile", trimmed, voter_text)
            if result:
                return result

        if _is_real_key(OPENAI_API_KEY):
            return await self._call_llm(OPENAI_API_URL, OPENAI_API_KEY, "gpt-4.1-mini", system_prompt, voter_text)

        return None

    async def _call_llm(self, url: str, api_key: str, model: str, system_prompt: str, voter_text: str) -> Optional[str]:
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
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.post(url, headers=headers, json=body, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data["choices"][0]["message"]["content"].strip()
                    else:
                        err = await resp.text()
                        logger.warning(f"LLM {model} {resp.status}: {err[:150]}")
        except Exception as e:
            logger.warning(f"LLM {model} error: {e}")
        return None

    async def _synthesize_tts(self, text: str, voice_id: str, speed: float = 1.0) -> Optional[bytes]:
        if not _is_real_key(CARTESIA_API_KEY):
            return None
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
        if speed != 1.0:
            body["speed"] = speed
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.post(CARTESIA_TTS_URL, headers=headers, json=body, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        return await resp.read()
                    else:
                        err = await resp.text()
                        logger.warning(f"TTS {resp.status}: {err[:150]}")
        except Exception as e:
            logger.warning(f"TTS error: {e}")
        return None


# ═══════════════════════════════════════════════════════════
# HTML — TEST VOICE PAGE
# ═══════════════════════════════════════════════════════════

def get_html() -> str:
    return """<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Predator Agent — Voice Test</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#0a0a0a;color:#f0f0f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:700px;margin:20px auto;padding:0 16px}
h1{text-align:center;margin:12px 0;font-size:1.6em;color:#4af}
.panel{background:#1a1a1a;border-radius:10px;padding:14px;margin:10px 0}
.status{display:inline-block;margin:4px 12px 4px 0;font-size:0.95em}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;margin-left:4px}
.dot.ok{background:#4f4}
.dot.off{background:#f44}
.dot.wait{background:#fa4}
.btn{background:#4af;color:#000;border:none;padding:10px 20px;border-radius:8px;font-size:1em;cursor:pointer;margin:4px 4px 4px 0;font-weight:bold}
.btn:disabled{opacity:0.4;cursor:default}
.btn.end{background:#f44}
.btn.ping{background:#555;color:#fff}
textarea{width:100%;background:#222;color:#fff;border:1px solid #444;border-radius:8px;padding:10px;font-size:1em;resize:vertical;direction:rtl}
.transcript{background:#111;border:1px solid #333;border-radius:8px;padding:12px;max-height:300px;overflow-y:auto;margin:10px 0;font-size:0.9em;direction:rtl}
.transcript .agent{color:#4af;margin:4px 0}
.transcript .voter{color:#fa4;margin:4px 0}
.transcript .system{color:#888;font-size:0.8em}
.ws-url{font-size:0.75em;color:#666;word-break:break-all}
</style>
</head>
<body>
<h1>🎙 Predator Agent — Voice Test</h1>
<div class="panel">
<div class="status"><span class="dot wait" id="ws-dot"></span><span id="ws-status">מתחבר...</span></div>
<div class="status">🧠 LLM: <span id="llm-status">—</span></div>
<div class="status">🗣 TTS: <span id="tts-status">—</span></div>
<div class="ws-url" id="ws-url-display"></div>
</div>
<button class="btn start" id="btn-start" onclick="startCall()" disabled>▶ התחל שיחה</button>
<button class="btn end" id="btn-end" onclick="endCall()" disabled>⏹ סיים שיחה</button>
<div class="panel">
<textarea id="text-input" placeholder="הקלד הודעה בעברית..."></textarea>
<button class="btn ping" onclick="sendText()">📤 שלח</button>
</div>
<div class="panel">
<h3>📜 תמליל:</h3>
<div class="transcript" id="transcript"></div>
</div>
<script>
const WS_URL=(()=>{const p=location.protocol==='https:'?'wss:':'ws:';const h=location.host;return p+'//'+h+'/ws'})();
let ws=null,sessionId=null,audioCtx=null;
document.getElementById('ws-url-display').textContent=WS_URL;
function setStatus(el,cls,text){document.getElementById(el+'-dot').className='dot '+cls;document.getElementById(el+'-status').textContent=text;}
async function connect(){ws=new WebSocket(WS_URL);ws.binaryType='arraybuffer';ws.onopen=()=>{setStatus('ws','ok','מחובר');document.getElementById('btn-start').disabled=false};ws.onclose=()=>{setStatus('ws','off','מנותק');document.getElementById('btn-start').disabled=true;document.getElementById('btn-end').disabled=true};ws.onerror=()=>setStatus('ws','off','שגיאה');ws.onmessage=(e)=>{try{const d=JSON.parse(e.data);if(d.type==='session_started'){sessionId=d.session_id;addTranscript('system','שיחה '+d.persona_name+' ('+d.persona+') התחילה');setStatus('llm','ok','מוכן');}if(d.type==='agent_response'){addTranscript('agent',d.text+' ['+d.state+' r:'+d.resistance+']');if(d.audio)playAudio(d.audio);setStatus('tts','ok','TTS '+(d.audio?d.audio.length/1000+'KB':'fallback'));}}}catch{}};}
function startCall(){if(ws&&ws.readyState===1){ws.send(JSON.stringify({type:'start'}));document.getElementById('btn-start').disabled=true;document.getElementById('btn-end').disabled=false;}}
function endCall(){if(ws){ws.send(JSON.stringify({type:'end_call'}));document.getElementById('btn-start').disabled=true;document.getElementById('btn-end').disabled=true;addTranscript('system','שיחה הסתיימה');}}
function sendText(){const inp=document.getElementById('text-input');const txt=inp.value.trim();if(txt&&ws&&ws.readyState===1){addTranscript('voter',txt);ws.send(JSON.stringify({type:'text',content:txt}));inp.value='';}}
function addTranscript(role,text){const d=document.getElementById('transcript');d.innerHTML+='<div class="'+role+'">'+text+'</div>';d.scrollTop=d.scrollHeight;}
function playAudio(b64){try{const bin=atob(b64);const bytes=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)bytes[i]=bin.charCodeAt(i);if(!audioCtx)audioCtx=new(window.AudioContext||window.webkitAudioContext)({sampleRate:24000});const buf=audioCtx.createBuffer(1,bytes.length/2,24000);const ch=buf.getChannelData(0);const view=new DataView(bytes.buffer);for(let i=0;i<bytes.length/2;i++)ch[i]=view.getInt16(i*2,true)/32768;const src=audioCtx.createBufferSource();src.buffer=buf;src.connect(audioCtx.destination);src.start();}catch(e){console.error('audio:',e);}}
connect();
</script>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════
# TWIML — Twilio response XML
# ═══════════════════════════════════════════════════════════

def _get_twiml(ws_url: str) -> str:
    """Generate TwiML that connects the call to our Media Streams WebSocket."""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say voice="Polly.Mizuki" language="he-IL">שלום, כאן המערכת. אנא המתן.</Say>
    <Connect>
        <Stream url="{ws_url}">
            <Parameter name="mode" value="campaign"/>
        </Stream>
    </Connect>
</Response>"""


# ═══════════════════════════════════════════════════════════
# TWILIO MEDIA STREAM HANDLER (aiohttp WebSocket)
# ═══════════════════════════════════════════════════════════

class TwilioMediaHandler:
    """Handles a single Twilio Media Streams connection (aiohttp WS)."""

    def __init__(self, ws, engine: PredatorEngine, call_sid: str):
        self.ws = ws          # aiohttp.web.WebSocketResponse
        self.engine = engine
        self.call_sid = call_sid
        self.stream_sid = None
        self.session_id = None
        self.deepgram_ws = None
        self._dg_task = None
        self._pending_response = False
        self._silence_frames = 0
        self._last_transcript = ""
        self._speaking = False
        self._alive = True
        self._send_queue = asyncio.Queue()

    async def start(self):
        self.session_id = self.engine.create_session()
        logger.info(f"[{self.call_sid[:8]}] Session: {self.session_id}")
        asyncio.create_task(self._audio_sender())

    async def handle_message(self, data: dict):
        event = data.get("event", "")

        if event == "connected":
            logger.info(f"[{self.call_sid[:8]}] Twilio stream connected")

        elif event == "start":
            self.stream_sid = data.get("streamSid", "")
            logger.info(f"[{self.call_sid[:8]}] Stream started: {self.stream_sid[:12]}...")
            await self._connect_deepgram()

        elif event == "media":
            payload_b64 = data.get("media", {}).get("payload", "")
            if not payload_b64:
                return
            try:
                mulaw_bytes = base64.b64decode(payload_b64)
            except Exception:
                return

            pcm_8k = mulaw_decode(mulaw_bytes)
            pcm_16k = resample_audio(pcm_8k, 8000, 16000)
            pcm_bytes = pcm_to_bytes(pcm_16k, 2)

            if self.deepgram_ws and not self.deepgram_ws.closed:
                try:
                    await self.deepgram_ws.send_bytes(pcm_bytes)
                except Exception:
                    pass

            energy = np.mean(np.abs(pcm_8k))
            if energy > 0.005:
                self._speaking = True
                self._silence_frames = 0
            elif self._speaking:
                self._silence_frames += 1

            if self._speaking and self._silence_frames > 60 and not self._pending_response:
                self._speaking = False
                self._finalize_turn()

        elif event == "stop":
            logger.info(f"[{self.call_sid[:8]}] Stream stopped")
            await self.cleanup()

    async def _connect_deepgram(self):
        if not _is_real_key(DEEPGRAM_API_KEY):
            logger.warning("Deepgram API key missing")
            return
        try:
            import websockets
            url = f"{DEEPGRAM_WS_URL}?encoding=linear16&sample_rate=16000&language=he&interim_results=false&smart_format=true&vad_events=true&endpointing=300"
            self.deepgram_ws = await websockets.connect(
                url,
                additional_headers={"Authorization": f"Token {DEEPGRAM_API_KEY}"},
                ping_interval=5,
            )
            self._dg_task = asyncio.create_task(self._deepgram_listener())
        except Exception as e:
            logger.error(f"Deepgram connect error: {e}")

    async def _deepgram_listener(self):
        try:
            async for msg in self.deepgram_ws:
                if isinstance(msg, str):
                    try:
                        data = json.loads(msg)
                    except json.JSONDecodeError:
                        continue
                    if data.get("type") == "Results":
                        channel = data.get("channel", {})
                        alternatives = channel.get("alternatives", [])
                        if alternatives and alternatives[0].get("transcript", "").strip():
                            transcript = alternatives[0]["transcript"].strip()
                            is_final = data.get("is_final", False)
                            if is_final and transcript != self._last_transcript:
                                self._last_transcript = transcript
                                logger.info(f"[{self.call_sid[:8]}] 🎤: {transcript[:80]}")
                                await self._process_transcript(transcript)
        except Exception as e:
            logger.warning(f"Deepgram listener error: {e}")

    def _finalize_turn(self):
        if not self._last_transcript:
            return
        transcript = self._last_transcript
        self._last_transcript = ""
        if transcript.strip():
            asyncio.create_task(self._process_transcript(transcript))

    async def _process_transcript(self, transcript: str):
        if self._pending_response:
            return
        self._pending_response = True
        t0 = time.time()

        try:
            result = await self.engine.process_text(self.session_id, transcript)
        except Exception as e:
            logger.error(f"Pipeline error: {e}")
            self._pending_response = False
            return

        elapsed = (time.time() - t0) * 1000
        agent_text = result["text"]
        audio_data = result["audio"]
        logger.info(f"[{self.call_sid[:8]}] 🤖 ({elapsed:.0f}ms): {agent_text[:60]}")

        if audio_data:
            await self._send_audio(audio_data)
        self._pending_response = False

    async def _send_audio(self, pcm_16bit_24khz: bytes):
        """Convert 24kHz int16 PCM → μ-law and queue for sending via Twilio."""
        # Convert to float32
        pcm_24k = bytes_to_pcm(pcm_16bit_24khz, 2)
        # Downsample 24kHz → 8kHz
        pcm_8k = resample_audio(pcm_24k, 24000, 8000)
        # Encode to μ-law
        mulaw = mulaw_encode(pcm_8k)
        # Base64 encode
        payload = base64.b64encode(mulaw).decode()
        # Queue for sending
        await self._send_queue.put(payload)

    async def _audio_sender(self):
        """Send queued audio frames back to Twilio."""
        while self._alive:
            try:
                payload = await asyncio.wait_for(self._send_queue.get(), timeout=0.5)
                if self.stream_sid and not self.ws.closed:
                    msg = json.dumps({
                        "event": "media",
                        "streamSid": self.stream_sid,
                        "media": {"payload": payload},
                    })
                    await self.ws.send_str(msg)
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                if self._alive:
                    logger.warning(f"Audio send error: {e}")
                break

    async def cleanup(self):
        self._alive = False
        if self._dg_task and not self._dg_task.done():
            self._dg_task.cancel()
        if self.deepgram_ws and not self.deepgram_ws.closed:
            try:
                await self.deepgram_ws.close()
            except Exception:
                pass
        if self.session_id:
            self.engine.end_session(self.session_id)


# ═══════════════════════════════════════════════════════════
# BROWSER WEBSOCKET SESSION (aiohttp WS)
# ═══════════════════════════════════════════════════════════

class BrowserSession:
    """Handles a browser WebSocket connection for testing (aiohttp WS)."""

    def __init__(self, ws, engine: PredatorEngine):
        self.ws = ws          # aiohttp.web.WebSocketResponse
        self.engine = engine
        self.session_id = None
        self._pending_response = False
        self._last_response = None

    async def start(self):
        self.session_id = self.engine.create_session()

        session_info = self.engine.agent.get_session(self.session_id) if hasattr(self.engine.agent, 'get_session') else None
        persona_key = "daniel"
        persona_name = "דניאל"
        support = 0.55
        if session_info:
            persona_key = session_info.current_persona
            p = get_persona(persona_key)
            persona_name = p.name
            support = session_info.support_score

        await self.ws.send_str(json.dumps({
            "type": "session_started",
            "session_id": self.session_id,
            "persona": persona_key,
            "persona_name": persona_name,
            "support_score": support,
        }, ensure_ascii=False))

    async def handle_message(self, data: dict):
        msg_type = data.get("type", "")

        if msg_type == "text":
            text = data.get("content", "").strip()
            if text and not self._pending_response:
                await self._process_text(text)
        elif msg_type == "start":
            pass
        elif msg_type == "end_call":
            logger.info("[Browser] Call ended by client")
            raise ConnectionError("call ended")
        elif msg_type == "ping":
            await self.ws.send_str(json.dumps({"type": "pong"}))

    async def _process_text(self, text: str):
        self._pending_response = True
        t0 = time.time()

        try:
            result = await self.engine.process_text(self.session_id, text)
        except Exception as e:
            logger.error(f"Pipeline error: {e}")
            self._pending_response = False
            return

        elapsed = (time.time() - t0) * 1000
        logger.info(f"[Browser] 🤖 ({elapsed:.0f}ms): {result['text'][:60]}")

        self._last_response = {
            "type": "agent_response",
            "text": result["text"],
            "state": result["state"],
            "resistance": result["resistance"],
            "persona": result["persona"],
            "persona_name": result["persona_name"],
            "tactic": result["tactic"],
            "tts_speed": result["tts_speed"],
            "audio": base64.b64encode(result["audio"]).decode() if result["audio"] else None,
            "prompt_chars": result["prompt_chars"],
        }
        self._pending_response = False

    async def send_response(self):
        if self._last_response and not self.ws.closed:
            await self.ws.send_str(json.dumps(self._last_response, ensure_ascii=False))
            self._last_response = None

    async def cleanup(self):
        if self.session_id:
            self.engine.end_session(self.session_id)

    @property
    def pending_response(self):
        return self._pending_response


# ═══════════════════════════════════════════════════════════
# AIOHTTP SERVER — HTTP + WebSocket (One port, production)
# ═══════════════════════════════════════════════════════════

from aiohttp import web

# Cache
_html_content = get_html().encode("utf-8")

dg_ok = _is_real_key(DEEPGRAM_API_KEY)
cart_ok = _is_real_key(CARTESIA_API_KEY)
groq_ok = _is_real_key(GROQ_API_KEY)
openai_ok = _is_real_key(OPENAI_API_KEY)
twilio_ok = _is_real_key(TWILIO_ACCOUNT_SID) and _is_real_key(TWILIO_AUTH_TOKEN)

HEALTH_JSON = json.dumps({
    "status": "ok",
    "deepgram": dg_ok,
    "cartesia": cart_ok,
    "groq": groq_ok,
    "openai": openai_ok,
    "twilio": twilio_ok,
    "llm_ready": groq_ok or openai_ok,
    "voice_ready": dg_ok and cart_ok,
    "production_ready": dg_ok and cart_ok and (groq_ok or openai_ok),
    "mode": AGENT_MODE,
    "uptime": time.time(),
}).encode()

# Global engine instance
engine = PredatorEngine()


# ── HTTP Handlers ──

async def handle_index(request):
    return web.Response(body=_html_content, content_type="text/html", charset="utf-8")


async def handle_health(request):
    return web.Response(body=HEALTH_JSON, content_type="application/json",
                        headers={"Access-Control-Allow-Origin": "*"})


async def handle_twilio_voice(request):
    host = _get_public_host(request)
    proto = "wss"
    ws_url = f"{proto}://{host}/twilio/media"
    twiml = _get_twiml(ws_url)
    logger.info(f"📞 Twilio webhook → {ws_url}")
    return web.Response(text=twiml, content_type="application/xml", charset="utf-8")


async def handle_twilio_status(request):
    return web.Response(text="OK")


# ── WebSocket Handlers ──

async def handle_twilio_media_ws(request):
    """Twilio Media Streams WebSocket."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    client = f"{request.remote}"
    call_sid = f"twilio-{client}"
    logger.info(f"📞 Twilio call connected: {client}")

    handler = TwilioMediaHandler(ws, engine, call_sid)
    try:
        await handler.start()
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    await handler.handle_message(data)
                except json.JSONDecodeError:
                    pass
            elif msg.type == web.WSMsgType.ERROR:
                logger.error(f"Twilio WS error: {ws.exception()}")
                break
            elif msg.type == web.WSMsgType.CLOSE:
                break
    except ConnectionError:
        pass
    except Exception as e:
        logger.error(f"Twilio stream error: {e}")
    finally:
        await handler.cleanup()
        logger.info(f"📞 Twilio call ended: {client}")

    return ws


async def handle_browser_ws(request):
    """Browser test WebSocket."""
    ws = web.WebSocketResponse()
    await ws.prepare(request)

    client = f"{request.remote}"
    logger.info(f"💻 Browser connected: {client}")

    session = BrowserSession(ws, engine)
    try:
        await session.start()
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    await session.handle_message(data)
                except json.JSONDecodeError:
                    pass
                await session.send_response()
            elif msg.type == web.WSMsgType.ERROR:
                logger.error(f"Browser WS error: {ws.exception()}")
                break
            elif msg.type == web.WSMsgType.CLOSE:
                break
    except ConnectionError:
        pass
    except Exception as e:
        logger.error(f"Browser session error: {e}")
    finally:
        await session.cleanup()
        logger.info(f"💻 Browser disconnected: {client}")

    return ws


# ── Build app ──

def create_app():
    app = web.Application()

    # HTTP routes
    app.router.add_get("/", handle_index)
    app.router.add_get("/index.html", handle_index)
    app.router.add_get("/test_voice.html", handle_index)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/api/health", handle_health)
    app.router.add_post("/twilio/voice", handle_twilio_voice)
    app.router.add_post("/twilio/status", handle_twilio_status)

    # WebSocket routes
    app.router.add_get("/twilio/media", handle_twilio_media_ws)
    app.router.add_get("/ws", handle_browser_ws)

    return app


# ── Main ──

def main():
    print()
    print("=" * 64)
    print("   🎙  PREDATOR AGENT — PRODUCTION SERVER v2")
    print("=" * 64)
    print(f"   🌐  HTTP + WS:  {HOST}:{PORT}")
    print(f"   📋  Deepgram:   {'✅' if dg_ok else '❌'}")
    print(f"   🗣   Cartesia:   {'✅' if cart_ok else '❌'}")
    print(f"   🧠  Groq:       {'✅' if groq_ok else '❌'}")
    print(f"   🧠  OpenAI:     {'✅' if openai_ok else '❌'}")
    print(f"   📞  Twilio:     {'✅' if twilio_ok else '⚠️  (config only)'}")
    print(f"   🎯  Mode:       {AGENT_MODE}")
    print()
    print(f"   🏠  Local:      http://localhost:{PORT}")
    if PUBLIC_URL:
        print(f"   🌍  Public:     {PUBLIC_URL}")
    print()
    print("   Endpoints:")
    print("     GET  /              → test_voice.html")
    print("     GET  /health        → status JSON")
    print("     POST /twilio/voice  → Twilio webhook (TwiML)")
    print("     POST /twilio/status → Twilio status callback")
    print("     WS   /twilio/media  → Twilio Media Streams")
    print("     WS   /ws            → browser client")
    print("=" * 64)
    print()

    if not dg_ok:
        print("❌ DEEPGRAM_API_KEY missing — STT will not work!")
    if not cart_ok:
        print("❌ CARTESIA_API_KEY missing — TTS will not work!")
    if not (groq_ok or openai_ok):
        print("⚠️  No LLM keys — using Hebrew fallback responses only")

    app = create_app()
    print("🟢 LIVE — accepting connections\n")
    web.run_app(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
