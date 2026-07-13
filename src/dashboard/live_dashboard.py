"""Live Dashboard — מצב שיחות בזמן אמת על :8080"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("live-dashboard")

DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))


@dataclass
class LiveCallSnapshot:
    session_id: str
    voter: str = ""
    phone: str = ""
    persona: str = "S"
    state: str = "opening"
    resistance: str = "medium"
    tactic: str = ""
    disc: str = ""
    persuadability: float = 0.0
    battle: bool = False
    exchange: int = 0
    last_voter_text: str = ""
    last_agent_text: str = ""
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    status: str = "active"  # active | ended

    def touch(self) -> None:
        self.updated_at = datetime.now().isoformat()


class CallRegistry:
    """רישום שיחות חיות — מקור האמת לדשבורד."""

    def __init__(self) -> None:
        self.calls: Dict[str, LiveCallSnapshot] = {}
        self.events: List[dict] = []
        self._subscribers: Set[asyncio.Queue] = set()
        self.stats = {
            "started": 0,
            "ended": 0,
            "commitments": 0,
            "battles": 0,
        }

    def upsert(self, snap: LiveCallSnapshot) -> None:
        is_new = snap.session_id not in self.calls
        snap.touch()
        self.calls[snap.session_id] = snap
        if is_new:
            self.stats["started"] += 1
        self._emit({"type": "call_update", "call": asdict(snap)})

    def end(self, session_id: str, final_state: str = "") -> None:
        snap = self.calls.get(session_id)
        if not snap:
            return
        snap.status = "ended"
        if final_state:
            snap.state = final_state
        snap.touch()
        self.stats["ended"] += 1
        if final_state in ("closing", "commitment", "gotv"):
            self.stats["commitments"] += 1
        self._emit({"type": "call_ended", "call": asdict(snap)})

    def mark_battle(self, session_id: str, active: bool = True) -> None:
        snap = self.calls.get(session_id)
        if not snap:
            return
        snap.battle = active
        if active:
            self.stats["battles"] += 1
        snap.touch()
        self._emit({"type": "battle", "session_id": session_id, "active": active})

    def list_active(self) -> List[dict]:
        return [asdict(c) for c in self.calls.values() if c.status == "active"]

    def overview(self) -> dict:
        active = self.list_active()
        by_state: Dict[str, int] = {}
        by_persona: Dict[str, int] = {}
        for c in active:
            by_state[c["state"]] = by_state.get(c["state"], 0) + 1
            by_persona[c["persona"]] = by_persona.get(c["persona"], 0) + 1
        return {
            "active_calls": len(active),
            "by_state": by_state,
            "by_persona": by_persona,
            "stats": dict(self.stats),
            "server_time": datetime.now().isoformat(),
        }

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def _emit(self, event: dict) -> None:
        event = {**event, "ts": time.time()}
        self.events.append(event)
        self.events = self.events[-500:]
        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.unsubscribe(q)


REGISTRY = CallRegistry()


HTML_PAGE = """<!doctype html>
<html lang="he" dir="rtl">
<head>
  <meta charset="utf-8"/>
  <title>Predator Live Dashboard</title>
  <style>
    :root { --bg:#0f1419; --card:#1a2332; --text:#e7ecf3; --muted:#8b9bb4; --accent:#3dd6c6; --warn:#f5a524; --bad:#ff6b6b; }
    body { margin:0; font-family: "Segoe UI", Arial, sans-serif; background:linear-gradient(160deg,#0f1419,#162033); color:var(--text); }
    header { padding:20px 28px; border-bottom:1px solid #243044; display:flex; justify-content:space-between; align-items:center; }
    h1 { margin:0; font-size:1.35rem; letter-spacing:.02em; }
    .meta { color:var(--muted); font-size:.9rem; }
    main { display:grid; grid-template-columns: 280px 1fr; gap:16px; padding:16px 28px 40px; }
    .card { background:var(--card); border:1px solid #2a3a52; border-radius:14px; padding:16px; }
    .stat { font-size:2rem; font-weight:700; color:var(--accent); }
    .grid { display:grid; grid-template-columns: repeat(auto-fill,minmax(280px,1fr)); gap:12px; }
    .call { background:#121a27; border:1px solid #2a3a52; border-radius:12px; padding:14px; }
    .call.battle { border-color:var(--bad); box-shadow:0 0 0 1px rgba(255,107,107,.25); }
    .row { display:flex; justify-content:space-between; gap:8px; margin:6px 0; color:var(--muted); font-size:.85rem; }
    .pill { display:inline-block; padding:2px 8px; border-radius:999px; background:#243044; color:var(--text); font-size:.75rem; }
    .pill.warn { background:#3a2a12; color:var(--warn); }
    .pill.bad { background:#3a1515; color:var(--bad); }
    pre { white-space:pre-wrap; color:#c9d4e5; font-size:.8rem; }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Predator Live</h1>
      <div class="meta">שיחות בזמן אמת · :8080</div>
    </div>
    <div class="meta" id="clock">—</div>
  </header>
  <main>
    <aside class="card">
      <div>פעילות עכשיו</div>
      <div class="stat" id="active">0</div>
      <div class="row"><span>התחייבויות</span><span id="commits">0</span></div>
      <div class="row"><span>Battle</span><span id="battles">0</span></div>
      <div class="row"><span>הסתיימו</span><span id="ended">0</span></div>
      <h3>לפי מצב</h3>
      <pre id="byState">{}</pre>
      <h3>לפי פרסונה</h3>
      <pre id="byPersona">{}</pre>
    </aside>
    <section>
      <div class="grid" id="calls"></div>
    </section>
  </main>
  <script>
    const callsEl = document.getElementById('calls');
    function render(overview, calls) {
      document.getElementById('active').textContent = overview.active_calls;
      document.getElementById('commits').textContent = overview.stats.commitments || 0;
      document.getElementById('battles').textContent = overview.stats.battles || 0;
      document.getElementById('ended').textContent = overview.stats.ended || 0;
      document.getElementById('byState').textContent = JSON.stringify(overview.by_state || {}, null, 2);
      document.getElementById('byPersona').textContent = JSON.stringify(overview.by_persona || {}, null, 2);
      document.getElementById('clock').textContent = overview.server_time || '';
      callsEl.innerHTML = calls.map(c => `
        <div class="call ${c.battle ? 'battle' : ''}">
          <div><strong>${c.voter || c.phone || c.session_id}</strong>
            ${c.battle ? '<span class="pill bad">BATTLE</span>' : ''}
            <span class="pill">${c.persona}</span>
            <span class="pill warn">${c.state}</span>
          </div>
          <div class="row"><span>התנגדות</span><span>${c.resistance}</span></div>
          <div class="row"><span>טקטיקה</span><span>${c.tactic || '—'}</span></div>
          <div class="row"><span>DISC</span><span>${c.disc || '—'}</span></div>
          <div class="row"><span>ציון</span><span>${(c.persuadability||0).toFixed(2)}</span></div>
          <div class="row"><span>חילופים</span><span>${c.exchange}</span></div>
          <pre>${(c.last_voter_text||'').slice(0,120)}</pre>
        </div>`).join('') || '<div class="card">אין שיחות פעילות</div>';
    }
    async function refresh() {
      const [o, c] = await Promise.all([
        fetch('/api/overview').then(r => r.json()),
        fetch('/api/calls').then(r => r.json()),
      ]);
      render(o, c);
    }
    refresh();
    setInterval(refresh, 2000);
    try {
      const es = new EventSource('/api/stream');
      es.onmessage = () => refresh();
    } catch (e) {}
  </script>
</body>
</html>
"""


def create_app(registry: CallRegistry = REGISTRY):
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

    app = FastAPI(title="Predator Live Dashboard", version="1.0.0")

    @app.get("/")
    async def index():
        return HTMLResponse(HTML_PAGE)

    @app.get("/api/overview")
    async def overview():
        return JSONResponse(registry.overview())

    @app.get("/api/calls")
    async def calls():
        return JSONResponse(registry.list_active())

    @app.get("/api/events")
    async def events():
        return JSONResponse(registry.events[-100:])

    @app.post("/api/hooks/call-update")
    async def hook_update(payload: dict):
        snap = LiveCallSnapshot(
            session_id=str(payload.get("session_id") or payload.get("id") or "unknown"),
            voter=str(payload.get("voter", "")),
            phone=str(payload.get("phone", "")),
            persona=str(payload.get("persona", "S")),
            state=str(payload.get("state", "opening")),
            resistance=str(payload.get("resistance", "medium")),
            tactic=str(payload.get("tactic", "")),
            disc=str(payload.get("disc", "")),
            persuadability=float(payload.get("persuadability") or 0),
            battle=bool(payload.get("battle")),
            exchange=int(payload.get("exchange") or 0),
            last_voter_text=str(payload.get("last_voter_text", "")),
            last_agent_text=str(payload.get("last_agent_text", "")),
            status="active",
        )
        registry.upsert(snap)
        return {"ok": True}

    @app.post("/api/hooks/call-end")
    async def hook_end(payload: dict):
        registry.end(str(payload.get("session_id", "")), str(payload.get("final_state", "")))
        return {"ok": True}

    @app.get("/api/stream")
    async def stream():
        queue = registry.subscribe()

        async def gen():
            try:
                yield f"data: {json.dumps({'type': 'hello'})}\n\n"
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15.0)
                        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    except asyncio.TimeoutError:
                        yield f"data: {json.dumps({'type': 'ping'})}\n\n"
            finally:
                registry.unsubscribe(queue)

        return StreamingResponse(gen(), media_type="text/event-stream")

    return app


class LiveDashboard:
    """שרת דשבורד — מחובר ל-PredatorAgent דרך REGISTRY."""

    def __init__(self, host: str = DASHBOARD_HOST, port: int = DASHBOARD_PORT, registry: CallRegistry = REGISTRY):
        self.host = host
        self.port = port
        self.registry = registry
        self._server = None

    @property
    def enabled(self) -> bool:
        return os.getenv("DASHBOARD_ENABLED", "true").lower() in ("1", "true", "yes")

    def publish_turn(self, session_id: str, payload: dict) -> None:
        if not self.enabled:
            return
        snap = self.registry.calls.get(session_id) or LiveCallSnapshot(session_id=session_id)
        for k in (
            "voter", "phone", "persona", "state", "resistance", "tactic",
            "disc", "persuadability", "battle", "exchange",
            "last_voter_text", "last_agent_text",
        ):
            if k in payload and payload[k] is not None:
                setattr(snap, k, payload[k])
        snap.status = "active"
        self.registry.upsert(snap)

    def publish_end(self, session_id: str, final_state: str = "") -> None:
        if self.enabled:
            self.registry.end(session_id, final_state)

    async def start(self) -> None:
        if not self.enabled:
            logger.info("Dashboard disabled (DASHBOARD_ENABLED=false)")
            return
        import uvicorn

        app = create_app(self.registry)
        config = uvicorn.Config(app, host=self.host, port=self.port, log_level="info")
        self._server = uvicorn.Server(config)
        logger.info("Live Dashboard on http://%s:%s", self.host, self.port)
        await self._server.serve()


def run_dashboard() -> None:
    dash = LiveDashboard()
    asyncio.run(dash.start())


if __name__ == "__main__":
    run_dashboard()
