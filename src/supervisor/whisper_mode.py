"""Whisper Mode — מפקח מזריק הוראות לסוכן בלי שהבוחר שומע (:9001/whisper)"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Deque, Dict, List, Optional

logger = logging.getLogger("whisper-mode")

WHISPER_HOST = os.getenv("WHISPER_HOST", "0.0.0.0")
WHISPER_PORT = int(os.getenv("WHISPER_PORT", "9001"))


@dataclass
class WhisperMessage:
    session_id: str
    text: str
    author: str = "supervisor"
    priority: int = 1  # 1=normal, 2=high, 3=critical
    kind: str = "coach"  # coach | tactic | persona | abort | note
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    consumed: bool = False
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = f"w-{int(time.time() * 1000)}"


@dataclass
class SupervisorNote:
    session_id: str
    note: str
    author: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


class WhisperBus:
    """תור לחשים לכל session — Predator שולף לפני בניית פרומפט."""

    def __init__(self, max_queue: int = 20) -> None:
        self.max_queue = max_queue
        self._queues: Dict[str, Deque[WhisperMessage]] = defaultdict(deque)
        self._history: Dict[str, List[WhisperMessage]] = defaultdict(list)
        self._notes: Dict[str, List[SupervisorNote]] = defaultdict(list)
        self._locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.stats = {"pushed": 0, "consumed": 0, "dropped": 0}

    @property
    def enabled(self) -> bool:
        return os.getenv("WHISPER_ENABLED", "true").lower() in ("1", "true", "yes")

    def push(
        self,
        session_id: str,
        text: str,
        *,
        author: str = "supervisor",
        priority: int = 1,
        kind: str = "coach",
    ) -> WhisperMessage:
        msg = WhisperMessage(
            session_id=session_id,
            text=text.strip(),
            author=author,
            priority=max(1, min(3, int(priority))),
            kind=kind,
        )
        q = self._queues[session_id]
        if len(q) >= self.max_queue:
            q.popleft()
            self.stats["dropped"] += 1
        # עדיפות גבוהה קודם — נשמור ממוין
        q.append(msg)
        items = sorted(q, key=lambda m: (-m.priority, m.created_at))
        self._queues[session_id] = deque(items, maxlen=self.max_queue)
        self._history[session_id].append(msg)
        self.stats["pushed"] += 1
        logger.info("[whisper] push session=%s kind=%s prio=%s: %s", session_id, kind, priority, text[:80])
        return msg

    def consume(self, session_id: str, limit: int = 3) -> List[WhisperMessage]:
        if not self.enabled:
            return []
        q = self._queues.get(session_id)
        if not q:
            return []
        out: List[WhisperMessage] = []
        for _ in range(min(limit, len(q))):
            msg = q.popleft()
            msg.consumed = True
            out.append(msg)
            self.stats["consumed"] += 1
        return out

    def peek(self, session_id: str) -> List[dict]:
        return [asdict(m) for m in self._queues.get(session_id, [])]

    def history(self, session_id: str) -> List[dict]:
        return [asdict(m) for m in self._history.get(session_id, [])[-50:]]

    def add_note(self, session_id: str, note: str, author: str = "supervisor") -> SupervisorNote:
        n = SupervisorNote(session_id=session_id, note=note, author=author)
        self._notes[session_id].append(n)
        return n

    def prompt_overlay(self, session_id: str) -> str:
        """מחזיר בלוק להזרקה ל-system prompt — הבוחר לא שומע את זה."""
        msgs = self.consume(session_id)
        if not msgs:
            return ""
        lines = ["[WHISPER — הוראות מפקח, אל תזכיר לבוחר]"]
        for m in msgs:
            prefix = {
                "coach": "אימון",
                "tactic": "טקטיקה",
                "persona": "פרסונה",
                "abort": "עצור/סיים",
                "note": "הערה",
            }.get(m.kind, "הוראה")
            lines.append(f"- ({prefix}, p{m.priority}) {m.text}")
        lines.append("יישם בעדינות בתור הבא. אל תגיד 'המפקח אמר'.")
        return "\n".join(lines)

    def apply_to_turn(self, session_id: str, turn_payload: dict) -> dict:
        """מעדכן payload של תור לפי לחשים (persona/tactic/abort)."""
        overlay = self.prompt_overlay(session_id)
        if overlay:
            turn_payload = dict(turn_payload)
            existing = turn_payload.get("system_prompt") or ""
            turn_payload["system_prompt"] = existing + "\n\n" + overlay if existing else overlay
            turn_payload["whisper"] = True
        # non-consuming peek already consumed in prompt_overlay; check history for control kinds
        return turn_payload

    def summary(self) -> dict:
        return {
            "enabled": self.enabled,
            "active_sessions": len([k for k, v in self._queues.items() if v]),
            "stats": dict(self.stats),
        }


BUS = WhisperBus()


WHISPER_UI = """<!doctype html>
<html lang="he" dir="rtl">
<head>
  <meta charset="utf-8"/>
  <title>Whisper Mode</title>
  <style>
    body { font-family: Arial, sans-serif; background:#101820; color:#eef3f8; margin:0; padding:24px; }
    .card { background:#1b2838; border-radius:12px; padding:16px; max-width:720px; margin:0 auto; border:1px solid #2c3f55; }
    input, textarea, select, button { width:100%; margin:8px 0; padding:10px; border-radius:8px; border:1px solid #345; background:#0f1720; color:#fff; box-sizing:border-box; }
    button { background:#2bbbad; border:none; font-weight:700; cursor:pointer; }
    h1 { margin-top:0; }
    .ok { color:#2bbbad; }
  </style>
</head>
<body>
  <div class="card">
    <h1>Whisper Mode</h1>
    <p>הזרקת הוראה לסוכן — הבוחר לא שומע. פורט 9001</p>
    <label>session_id</label>
    <input id="sid" placeholder="out-050..."/>
    <label>סוג</label>
    <select id="kind">
      <option value="coach">coach</option>
      <option value="tactic">tactic</option>
      <option value="persona">persona</option>
      <option value="abort">abort</option>
      <option value="note">note</option>
    </select>
    <label>עדיפות</label>
    <select id="prio"><option>1</option><option>2</option><option selected>3</option></select>
    <label>הודעה</label>
    <textarea id="text" rows="4" placeholder="תעבור לטקטיקת limited_choice עכשיו"></textarea>
    <button onclick="send()">שלח Whisper</button>
    <pre id="out" class="ok"></pre>
  </div>
  <script>
    async function send() {
      const body = {
        session_id: document.getElementById('sid').value,
        text: document.getElementById('text').value,
        kind: document.getElementById('kind').value,
        priority: Number(document.getElementById('prio').value),
        author: 'supervisor-ui',
      };
      const r = await fetch('/whisper', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body) });
      document.getElementById('out').textContent = JSON.stringify(await r.json(), null, 2);
    }
  </script>
</body>
</html>
"""



# פריסטים מוכנים למפקח
WHISPER_PRESETS = {
    "slow_down": WhisperMessage(session_id="", text="האט. תן לו לדבר. משפט אחד קצר.", kind="coach", priority=2),
    "limited_choice": WhisperMessage(session_id="", text="עבור עכשיו לבחירה מוגבלת: בוקר או ערב?", kind="tactic", priority=3),
    "deescalate": WhisperMessage(session_id="", text="התנגדות גבוהה — עבור ל-deescalation. אין לחץ.", kind="coach", priority=3),
    "close_now": WhisperMessage(session_id="", text="סגור בעדינות. תודה + קלפי. בלי למכור עוד.", kind="abort", priority=2),
    "switch_persona_S": WhisperMessage(session_id="", text="עבור לטון דוד (S): איטי, חם, בלי לחץ.", kind="persona", priority=2),
    "switch_persona_D": WhisperMessage(session_id="", text="עבור לטון אלון (D): קצר, חד, לעניין.", kind="persona", priority=2),
}


def apply_preset(bus: WhisperBus, session_id: str, preset: str, author: str = "supervisor") -> WhisperMessage:
    base = WHISPER_PRESETS.get(preset)
    if not base:
        raise KeyError(f"unknown preset: {preset}")
    return bus.push(session_id, base.text, author=author, priority=base.priority, kind=base.kind)


def list_presets() -> dict:
    return {k: {"text": v.text, "kind": v.kind, "priority": v.priority} for k, v in WHISPER_PRESETS.items()}


def create_whisper_app(bus: WhisperBus = BUS):
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import HTMLResponse, JSONResponse

    app = FastAPI(title="Predator Whisper Mode", version="1.0.0")

    @app.get("/")
    async def ui():
        return HTMLResponse(WHISPER_UI)

    @app.get("/whisper")
    async def whisper_ui():
        """UI ב־/whisper — הדפדפן שולח GET; שליחה נשארת POST /whisper."""
        return HTMLResponse(WHISPER_UI)

    @app.get("/health")
    async def health():
        return bus.summary()

    @app.post("/whisper")
    async def whisper(payload: dict):
        if not bus.enabled:
            raise HTTPException(503, "WHISPER_ENABLED=false")
        session_id = (payload.get("session_id") or "").strip()
        text = (payload.get("text") or "").strip()
        if not session_id or not text:
            raise HTTPException(400, "session_id and text required")
        msg = bus.push(
            session_id,
            text,
            author=str(payload.get("author") or "supervisor"),
            priority=int(payload.get("priority") or 1),
            kind=str(payload.get("kind") or "coach"),
        )
        return JSONResponse({"ok": True, "message": asdict(msg)})

    @app.get("/whisper/{session_id}")
    async def peek(session_id: str):
        return {
            "pending": bus.peek(session_id),
            "history": bus.history(session_id),
        }

    @app.post("/whisper/{session_id}/note")
    async def note(session_id: str, payload: dict):
        n = bus.add_note(session_id, str(payload.get("note") or ""), str(payload.get("author") or "supervisor"))
        return asdict(n)

    @app.delete("/whisper/{session_id}")
    async def clear(session_id: str):
        bus._queues[session_id].clear()
        return {"ok": True, "cleared": session_id}

    @app.get("/whisper/presets/list")
    async def presets():
        return list_presets()

    @app.post("/whisper/{session_id}/preset/{name}")
    async def preset(session_id: str, name: str, payload: dict | None = None):
        payload = payload or {}
        try:
            msg = apply_preset(bus, session_id, name, author=str(payload.get("author") or "supervisor"))
        except KeyError as e:
            raise HTTPException(404, str(e))
        return asdict(msg)

    return app


class WhisperMode:
    """שרת מפקח + API לסוכן."""

    def __init__(self, host: str = WHISPER_HOST, port: int = WHISPER_PORT, bus: WhisperBus = BUS):
        self.host = host
        self.port = port
        self.bus = bus

    @property
    def enabled(self) -> bool:
        return self.bus.enabled

    def inject(self, session_id: str, text: str, **kwargs) -> WhisperMessage:
        return self.bus.push(session_id, text, **kwargs)

    def overlay_for(self, session_id: str) -> str:
        return self.bus.prompt_overlay(session_id)

    async def start(self) -> None:
        if not self.enabled:
            logger.info("Whisper disabled (WHISPER_ENABLED=false)")
            return
        import uvicorn

        app = create_whisper_app(self.bus)
        config = uvicorn.Config(app, host=self.host, port=self.port, log_level="info")
        server = uvicorn.Server(config)
        logger.info("Whisper Mode on http://%s:%s/whisper", self.host, self.port)
        await server.serve()


def run_whisper() -> None:
    asyncio.run(WhisperMode().start())


if __name__ == "__main__":
    run_whisper()
