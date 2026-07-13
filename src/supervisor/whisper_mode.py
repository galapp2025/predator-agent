"""Whisper Mode - Human-in-the-Loop Supervisor"""
import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Set

logger = logging.getLogger("whisper-mode")

_whisper_hint: Optional[str] = None
_whisper_hint_lock = threading.Lock()

def set_whisper_hint(hint: str):
    global _whisper_hint
    with _whisper_hint_lock:
        _whisper_hint = hint.strip() if hint else None

def get_whisper_hint() -> Optional[str]:
    with _whisper_hint_lock:
        return _whisper_hint

def clear_whisper_hint():
    global _whisper_hint
    with _whisper_hint_lock:
        _whisper_hint = None

@dataclass
class WhisperSession:
    session_id: str
    phone: str = ""
    first_name: str = ""
    state: str = "opening"
    resistance: str = "medium"
    persona: str = "S"
    exchanges: int = 0
    last_voter_text: str = ""
    last_agent_text: str = ""
    transcript: List[Dict] = field(default_factory=list)
    whisper_hints_sent: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

class WhisperSessionManager:
    def __init__(self):
        self._sessions: Dict[str, WhisperSession] = {}
        self._lock = threading.Lock()

    def create_session(self, session_id, phone="", first_name=""):
        with self._lock:
            s = WhisperSession(session_id=session_id, phone=phone, first_name=first_name)
            self._sessions[session_id] = s
            if len(self._sessions) > 100:
                oldest = list(self._sessions.keys())[0]
                del self._sessions[oldest]
            return s

    def update_session(self, session_id, **kwargs):
        with self._lock:
            s = self._sessions.get(session_id)
            if s:
                for k, v in kwargs.items():
                    if hasattr(s, k):
                        setattr(s, k, v)

    def add_transcript_line(self, session_id, role, text):
        with self._lock:
            s = self._sessions.get(session_id)
            if s:
                s.transcript.append({"role": role, "text": text[:500], "at": datetime.now().isoformat()})
                if role == "user":
                    s.last_voter_text = text[:300]
                elif role == "assistant":
                    s.last_agent_text = text[:300]

    def get_session(self, session_id):
        with self._lock:
            return self._sessions.get(session_id)

    def get_active_sessions(self):
        with self._lock:
            return [
                {
                    "session_id": s.session_id, "phone": s.phone, "first_name": s.first_name,
                    "state": s.state, "resistance": s.resistance, "persona": s.persona,
                    "exchanges": s.exchanges,
                    "last_voter_text": s.last_voter_text[-120:] if s.last_voter_text else "",
                    "last_agent_text": s.last_agent_text[-120:] if s.last_agent_text else "",
                    "transcript": s.transcript[-30:],
                    "hints_sent": s.whisper_hints_sent, "created_at": s.created_at,
                }
                for s in self._sessions.values()
            ]

    def remove_session(self, session_id):
        with self._lock:
            self._sessions.pop(session_id, None)

whisper_manager = WhisperSessionManager()

def inject_whisper_hint_into_prompt() -> str:
    hint = get_whisper_hint()
    if not hint:
        return ""
    return f"""
[הנחיית סופרבייזר — שים לב!]
הסופרבייזר שלח לך הנחיה חשאית:
"{hint}"
הטמע את ההנחיה הזו באופן טבעי בתוך התגובה הבאה. אל תזכיר אותה. אל תצטט אותה.
"""

class WhisperIntegrator:
    def __init__(self, enabled=True):
        self.enabled = enabled

    def on_session_start(self, session_id, phone="", first_name=""):
        if not self.enabled:
            return
        whisper_manager.create_session(session_id, phone=phone, first_name=first_name)

    def on_voter_message(self, session_id, voter_text):
        if not self.enabled:
            return
        whisper_manager.add_transcript_line(session_id, "user", voter_text)

    def on_agent_response(self, session_id, agent_result):
        if not self.enabled:
            return
        text = agent_result.get("system_prompt", "") if isinstance(agent_result, dict) else str(agent_result)
        whisper_manager.add_transcript_line(session_id, "assistant", text[:300])
        if isinstance(agent_result, dict):
            whisper_manager.update_session(
                session_id,
                state=agent_result.get("state", "opening"),
                resistance=agent_result.get("resistance", "medium"),
                persona=agent_result.get("persona", "S"),
                exchanges=agent_result.get("exchange_count", 0),
            )

    def on_session_end(self, session_id):
        if not self.enabled:
            return
        whisper_manager.remove_session(session_id)
        clear_whisper_hint()

# ── HTTP API Routes ────────────────────────────────────
def mount_whisper_routes(app):
    """Mount whisper API routes on a FastAPI app."""
    from fastapi import Request
    from fastapi.responses import JSONResponse, HTMLResponse
    import os

    WHISPER_HTML_PATH = os.path.join(os.path.dirname(__file__), "whisper_supervisor.html")

    @app.get("/whisper", response_class=HTMLResponse)
    async def whisper_ui():
        html = _get_whisper_html()
        return HTMLResponse(content=html)

    @app.get("/api/whisper/sessions")
    async def api_sessions():
        sessions = whisper_manager.get_active_sessions()
        return JSONResponse(content={"sessions": sessions, "count": len(sessions)})

    @app.get("/api/whisper/hint")
    async def api_get_hint():
        h = get_whisper_hint()
        return JSONResponse(content={"hint": h, "active": h is not None})

    @app.post("/api/whisper")
    async def api_set_hint(request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        session_id = body.get("session_id", "")
        hint = body.get("hint", "")
        if hint:
            set_whisper_hint(hint)
            s = whisper_manager.get_session(session_id)
            if s:
                whisper_manager.update_session(session_id, whisp_hints_sent=s.whisper_hints_sent + 1)
            return JSONResponse(content={"status": "ok", "session_id": session_id})
        return JSONResponse(content={"status": "skipped"}, status_code=400)

    @app.post("/api/whisper/clear")
    async def api_clear():
        clear_whisper_hint()
        return JSONResponse(content={"status": "ok"})

    return app


def start_whisper_server(host="0.0.0.0", port=9001):
    from fastapi import FastAPI
    import uvicorn
    app = FastAPI(title="Predator Whisper")
    mount_whisper_routes(app)
    logger.info(f"Whisper supervisor on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")


def start_whisper_server_async(host="0.0.0.0", port=9001):
    t = threading.Thread(target=start_whisper_server, args=(host, port), daemon=True)
    t.start()
    logger.info(f"Whisper server bg on {host}:{port}")
    return t


def _get_whisper_html() -> str:
    return """<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Predator - Whisper Mode</title>
<style>
  :root{--bg:#0a0e14;--card:#141b22;--border:#1e2a36;--text:#c9cdd3;--accent:#e63946;--green:#2a9d8f;--orange:#e9c46a}
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:system-ui,sans-serif;background:var(--bg);color:var(--text);direction:rtl;height:100vh;display:flex}
  .sidebar{width:300px;background:var(--card);border-left:1px solid var(--border);padding:14px;display:flex;flex-direction:column;overflow-y:auto;flex-shrink:0}
  .sidebar h2{font-size:16px;color:var(--accent);margin-bottom:12px}
  .session-btn{display:block;width:100%;text-align:right;padding:10px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);cursor:pointer;margin-bottom:6px;font-size:13px}
  .session-btn:hover,.session-btn.active{border-color:var(--accent)}
  .session-btn .phone{color:#6b7280;font-size:11px}
  .session-btn .state{font-size:10px;color:var(--orange)}
  .main{flex:1;display:flex;flex-direction:column;overflow:hidden}
  .transcript{flex:1;overflow-y:auto;padding:16px}
  .msg{margin-bottom:10px;padding:8px 12px;border-radius:8px;max-width:80%;font-size:13px;line-height:1.5}
  .msg.agent{background:var(--card);margin-left:auto;text-align:left;border:1px solid var(--border)}
  .msg.voter{background:#1a2434;margin-right:auto;text-align:right}
  .msg .role{font-size:10px;color:#6b7280;margin-bottom:4px}
  .msg .time{font-size:9px;color:#4b5563;float:left}
  .whisper-bar{display:flex;gap:8px;padding:12px 16px;background:var(--card);border-top:1px solid var(--border);align-items:center}
  .whisper-bar input{flex:1;padding:10px 14px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:14px}
  .whisper-bar input:focus{outline:none;border-color:var(--accent)}
  .whisper-bar button{padding:10px 20px;background:var(--accent);color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:13px;font-weight:600}
  .whisper-bar button.clear{background:transparent;border:1px solid var(--border);color:var(--text)}
  .info-bar{display:flex;gap:16px;padding:8px 16px;background:var(--card);border-bottom:1px solid var(--border);font-size:12px}
  .info-item .label{color:#6b7280}
  .info-item .value{font-weight:600}
  .resistance-low{color:var(--green)}.resistance-medium{color:var(--orange)}.resistance-high{color:var(--accent)}
  .empty-state{text-align:center;color:#6b7280;margin-top:60px}
  .empty-state .icon{font-size:48px;margin-bottom:12px}
</style>
</head>
<body>
<div class="sidebar" id="sidebar">
  <h2>👂 שיחות פעילות</h2>
  <div id="session-list"></div>
</div>
<div class="main">
  <div class="info-bar" id="info-bar" style="display:none">
    <div class="info-item"><span class="label">מצב:</span><span class="value" id="info-state">-</span></div>
    <div class="info-item"><span class="label">התנגדות:</span><span class="value" id="info-resistance">-</span></div>
    <div class="info-item"><span class="label">פרסונה:</span><span class="value" id="info-persona">-</span></div>
    <div class="info-item"><span class="label">החלפות:</span><span class="value" id="info-exchanges">0</span></div>
    <div class="info-item"><span class="label">לחישות:</span><span class="value" id="info-hints">0</span></div>
  </div>
  <div class="transcript" id="transcript">
    <div class="empty-state"><div class="icon">🎧</div><div>בחר שיחה פעילה מהרשימה</div></div>
  </div>
  <div class="whisper-bar" id="whisper-bar" style="display:none">
    <input type="text" id="hint-input" placeholder="הכנס הנחיה לסוכן... (לדוגמה: 'תזכיר על הגן', 'תלחץ על מחירי דיור')" />
    <button onclick="sendHint()">🔥 לחישה</button>
    <button class="clear" onclick="clearHint()">נקה</button>
  </div>
</div>
<script>
let currentSessionId=null,sessions={},pollInterval=null;
function escapeHtml(t){const d=document.createElement('div');d.textContent=t;return d.innerHTML}
function renderSessionList(){
  const list=document.getElementById('session-list');
  const entries=Object.values(sessions);
  if(!entries.length){list.innerHTML='<div style="text-align:center;color:#6b7280;margin-top:12px;font-size:12px;">אין שיחות פעילות</div>';return}
  list.innerHTML=entries.map(s=>`<button class="session-btn ${s.session_id===currentSessionId?'active':''}" onclick="selectSession('${s.session_id}')"><div>${s.first_name||s.phone||s.session_id}</div><div class="phone">${s.phone||''}</div><div class="state">${s.state||'opening'} · ${s.resistance||'medium'}</div></button>`).join('')
}
function selectSession(id){
  currentSessionId=id;
  const s=sessions[id];
  if(s){renderTranscript(s);updateInfoBar(s);document.getElementById('info-bar').style.display='flex';document.getElementById('whisper-bar').style.display='flex';document.getElementById('hint-input').focus()}
  renderSessionList()
}
function renderTranscript(session){
  const div=document.getElementById('transcript');
  const lines=session.transcript||[];
  div.innerHTML=lines.map(l=>{const cls=l.role==='assistant'?'agent':'voter';const rl=l.role==='assistant'?'🤖 סוכן':'🗣️ בוחר';const tm=l.at?new Date(l.at).toLocaleTimeString('he-IL'):'';return`<div class="msg ${cls}"><div class="role">${rl}<span class="time">${tm}</span></div><div>${escapeHtml(l.text)}</div></div>`}).join('');
  div.scrollTop=div.scrollHeight
}
function updateInfoBar(session){
  document.getElementById('info-state').textContent=session.state||'-';
  document.getElementById('info-resistance').textContent=session.resistance||'-';
  document.getElementById('info-resistance').className='value resistance-'+(session.resistance||'medium');
  document.getElementById('info-persona').textContent=session.persona||'-';
  document.getElementById('info-exchanges').textContent=session.exchanges||0;
  document.getElementById('info-hints').textContent=session.hints_sent||0
}
async function sendHint(){
  const input=document.getElementById('hint-input');
  const hint=input.value.trim();
  if(!hint||!currentSessionId)return;
  try{
    await fetch('/api/whisper',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:currentSessionId,hint:hint})});
    input.value=''
  }catch(e){console.error(e)}
}
async function clearHint(){
  document.getElementById('hint-input').value='';
  if(currentSessionId){try{await fetch('/api/whisper/clear',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:currentSessionId})})}catch(e){}}
}
async function pollSessions(){
  try{
    const r=await fetch('/api/whisper/sessions');
    const d=await r.json();
    d.sessions.forEach(s=>{sessions[s.session_id]=s});
    renderSessionList();
    if(currentSessionId&&sessions[currentSessionId]){renderTranscript(sessions[currentSessionId]);updateInfoBar(sessions[currentSessionId])}
  }catch(e){}
}
document.addEventListener('DOMContentLoaded',()=>{
  document.getElementById('hint-input').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendHint()}});
  pollSessions();
  pollInterval=setInterval(pollSessions,2000)
});
</script>
</body>
</html>"""
