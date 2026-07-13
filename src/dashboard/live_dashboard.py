"""Live Campaign Dashboard — לוח בקרה בזמן אמת לקמפיין"""
import asyncio
import json
import logging
import os
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from ..agent.predator import PredatorAgent
from ..state_machine.states import ConversationState

logger = logging.getLogger("live-dashboard")

# ── Dashboard State (in-memory, shared across API calls) ──
# Tracks live campaign metrics updated by the agent during calls

DASHBOARD_STATE = {
    "campaign_name": os.getenv("CAMPAIGN_NAME", "פריימריז 2026"),
    "started_at": datetime.now().isoformat(),
    "total_calls": 0,
    "completed_calls": 0,
    "failed_calls": 0,
    "total_exchanges": 0,
    "state_counts": defaultdict(int),          # {state_name: count}
    "resistance_distribution": defaultdict(int), # {level: count}
    "persona_distribution": defaultdict(int),    # {disc: count}
    "tier_distribution": defaultdict(int),       # {tier: count}
    "calls": [],                                 # Recent call records (last 200)
    "funnel": {                                  # State funnel
        "opening": 0,
        "exploration": 0,
        "profiling": 0,
        "persuasion": 0,
        "commitment": 0,
        "closing": 0,
        "objection_handling": 0,
        "seed_planting": 0,
        "gotv": 0,
    },
    "conversion_events": [],                     # [{phone, name, from_state, to_state, at}]
    "active_sessions": 0,
    "avg_exchanges_per_call": 0.0,
    "avg_support_score": 0.0,
}

# Thread-safe lock
import threading
_state_lock = threading.Lock()


def update_dashboard(**kwargs):
    """Thread-safe dashboard state update."""
    with _state_lock:
        for key, value in kwargs.items():
            if key in DASHBOARD_STATE:
                if isinstance(DASHBOARD_STATE[key], (defaultdict, dict)):
                    if isinstance(value, dict):
                        for k, v in value.items():
                            DASHBOARD_STATE[key][k] = v
                    else:
                        DASHBOARD_STATE[key] = value
                elif isinstance(DASHBOARD_STATE[key], list):
                    if isinstance(value, list):
                        DASHBOARD_STATE[key].extend(value)
                        if key == "calls" and len(DASHBOARD_STATE[key]) > 200:
                            DASHBOARD_STATE[key] = DASHBOARD_STATE[key][-200:]
                    else:
                        DASHBOARD_STATE[key].append(value)
                        if key == "calls" and len(DASHBOARD_STATE[key]) > 200:
                            DASHBOARD_STATE[key] = DASHBOARD_STATE[key][-200:]
                else:
                    DASHBOARD_STATE[key] = value


def record_call_start(phone: str, name: str, tier: str = "B", support_score: float = 0.5):
    """Record a call starting in the dashboard."""
    with _state_lock:
        DASHBOARD_STATE["total_calls"] += 1
        DASHBOARD_STATE["active_sessions"] += 1
        DASHBOARD_STATE["tier_distribution"][tier] += 1
        DASHBOARD_STATE["calls"].append({
            "phone": phone,
            "name": name,
            "tier": tier,
            "support_score": support_score,
            "current_state": "opening",
            "resistance": "medium",
            "exchanges": 0,
            "started_at": datetime.now().isoformat(),
            "status": "active",
        })


def record_call_update(phone: str, state: str, resistance: str, exchanges: int, persona: str = "S"):
    """Record a call state update."""
    with _state_lock:
        DASHBOARD_STATE["total_exchanges"] += 1
        DASHBOARD_STATE["state_counts"][state] += 1
        DASHBOARD_STATE["resistance_distribution"][resistance] += 1
        DASHBOARD_STATE["persona_distribution"][persona] += 1

        funnel_state = state if state in DASHBOARD_STATE["funnel"] else "opening"
        DASHBOARD_STATE["funnel"][funnel_state] += 1

        for call in DASHBOARD_STATE["calls"]:
            if call["phone"] == phone and call["status"] == "active":
                call["current_state"] = state
                call["resistance"] = resistance
                call["exchanges"] = exchanges
                break

        if DASHBOARD_STATE["completed_calls"] > 0:
            DASHBOARD_STATE["avg_exchanges_per_call"] = round(
                DASHBOARD_STATE["total_exchanges"] / DASHBOARD_STATE["completed_calls"], 1
            )


def record_call_end(phone: str, result: str = "completed", final_state: str = "closing"):
    """Record a call ending."""
    with _state_lock:
        DASHBOARD_STATE["active_sessions"] = max(0, DASHBOARD_STATE["active_sessions"] - 1)
        DASHBOARD_STATE["completed_calls"] += 1

        for call in DASHBOARD_STATE["calls"]:
            if call["phone"] == phone and call["status"] == "active":
                call["status"] = result
                call["ended_at"] = datetime.now().isoformat()
                call["final_state"] = final_state
                break

        DASHBOARD_STATE["conversion_events"].append({
            "phone": phone,
            "final_state": final_state,
            "result": result,
            "at": datetime.now().isoformat(),
        })


def get_dashboard_snapshot() -> Dict:
    """Returns a copy of the dashboard state for API responses."""
    with _state_lock:
        snapshot = dict(DASHBOARD_STATE)
        snapshot["state_counts"] = dict(snapshot["state_counts"])
        snapshot["resistance_distribution"] = dict(snapshot["resistance_distribution"])
        snapshot["persona_distribution"] = dict(snapshot["persona_distribution"])
        snapshot["tier_distribution"] = dict(snapshot["tier_distribution"])
        snapshot["funnel"] = dict(snapshot["funnel"])
        snapshot["calls"] = list(snapshot["calls"][-50:])  # Last 50 for table
        snapshot["conversion_rate"] = (
            round(snapshot["completed_calls"] / max(1, snapshot["total_calls"]) * 100, 1)
            if snapshot["total_calls"] > 0 else 0.0
        )
        return snapshot


# ── Dashboard HTML ──────────────────────────────────────
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Predator Agent — לוח בקרה</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0a0e14;
    --card: #141b22;
    --border: #1e2a36;
    --text: #c9cdd3;
    --accent: #e63946;
    --accent2: #457b9d;
    --green: #2a9d8f;
    --orange: #e9c46a;
    --danger: #e63946;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); direction: rtl; }
  .container { max-width: 1440px; margin:0 auto; padding: 16px; }
  header { display:flex; justify-content:space-between; align-items:center; padding:8px 0 16px; border-bottom: 1px solid var(--border); margin-bottom: 16px; }
  header h1 { font-size: 22px; color: var(--accent); }
  header .status { font-size: 13px; padding:4px 12px; border-radius:12px; }
  .status.active { background:#2a9d8f33; color:var(--green); }
  .status.idle { background:#e9c46a33; color:var(--orange); }
  .kpi-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(160px,1fr)); gap:12px; margin-bottom:16px; }
  .kpi { background:var(--card); border:1px solid var(--border); border-radius:8px; padding:14px; }
  .kpi .label { font-size:11px; color:#6b7280; text-transform:uppercase; letter-spacing:0.5px; }
  .kpi .value { font-size:28px; font-weight:700; margin-top:4px; }
  .kpi .sub { font-size:11px; color:#6b7280; margin-top:2px; }
  .charts { display:grid; grid-template-columns: 1fr 1fr; gap:12px; margin-bottom:16px; }
  @media(max-width:860px) { .charts { grid-template-columns:1fr; } }
  .chart-card { background:var(--card); border:1px solid var(--border); border-radius:8px; padding:14px; }
  .chart-card h3 { font-size:14px; margin-bottom:10px; color:var(--text); }
  .chart-card canvas { max-height:260px; }
  .table-card { background:var(--card); border:1px solid var(--border); border-radius:8px; padding:14px; overflow-x:auto; }
  .table-card h3 { font-size:14px; margin-bottom:10px; }
  table { width:100%; border-collapse:collapse; font-size:12px; }
  th { text-align:right; padding:8px 6px; border-bottom:2px solid var(--border); color:#6b7280; font-weight:600; white-space:nowrap; }
  td { padding:6px; border-bottom:1px solid var(--border); white-space:nowrap; }
  .badge { font-size:10px; padding:2px 8px; border-radius:10px; }
  .badge-A { background:#2a9d8f33; color:var(--green); }
  .badge-B { background:#e9c46a33; color:var(--orange); }
  .badge-C { background:#e6394633; color:var(--danger); }
  .resistance-low { color:var(--green); }
  .resistance-medium { color:var(--orange); }
  .resistance-high { color:var(--danger); }
  .resistance-very_high { color:#ff4444; font-weight:700; }
  @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.6; } }
  .live-dot { display:inline-block; width:8px; height:8px; border-radius:50%; background:var(--green); animation:pulse 1.5s infinite; margin-left:6px; }
</style>
</head>
<body>
<div class="container">
<header>
  <h1>🐺 Predator Agent — <span id="campaign-name">...</span></h1>
  <div>
    <span class="live-dot"></span>
    <span class="status active" id="connection-status">מחובר</span>
    <span style="margin-right:12px; font-size:12px; color:#6b7280;" id="update-time"></span>
  </div>
</header>

<div class="kpi-grid">
  <div class="kpi"><div class="label">סה״כ שיחות</div><div class="value" id="kpi-total">0</div></div>
  <div class="kpi"><div class="label">הושלמו</div><div class="value" style="color:var(--green)" id="kpi-completed">0</div></div>
  <div class="kpi"><div class="label">פעילות כרגע</div><div class="value" style="color:var(--accent2)" id="kpi-active">0</div></div>
  <div class="kpi"><div class="label">שיעור המרה</div><div class="value" style="color:var(--orange)" id="kpi-conversion">0%</div></div>
  <div class="kpi"><div class="label">ממוצע החלפות לשיחה</div><div class="value" id="kpi-avg-exchanges">0</div></div>
  <div class="kpi"><div class="label">A-Tier מחויג</div><div class="value" style="color:var(--green)" id="kpi-tier-a">0</div></div>
</div>

<div class="charts">
  <div class="chart-card">
    <h3>משפך שיחה</h3>
    <canvas id="funnel-chart"></canvas>
  </div>
  <div class="chart-card">
    <h3>התפלגות התנגדות</h3>
    <canvas id="resistance-chart"></canvas>
  </div>
</div>

<div class="table-card">
  <h3>שיחות אחרונות</h3>
  <table id="calls-table">
    <thead><tr>
      <th>#</th><th>טלפון</th><th>שם</th><th>דירוג</th><th>מצב</th><th>התנגדות</th><th>החלפות</th><th>סטטוס</th>
    </tr></thead>
    <tbody></tbody>
  </table>
</div>
</div>

<script>
const REFRESH_MS = 3000;
let funnelChart, resistanceChart;

function initCharts() {
  const funnelCtx = document.getElementById('funnel-chart').getContext('2d');
  funnelChart = new Chart(funnelCtx, {
    type: 'bar',
    data: {
      labels: ['פתיחה','חקירה','פרופיילינג','שכנוע','מחויבות','סגירה'],
      datasets: [{
        label: 'מספר שיחות',
        data: [0,0,0,0,0,0],
        backgroundColor: ['#457b9d','#457b9d','#e9c46a','#e63946','#2a9d8f','#2a9d8f'],
        borderRadius: 4,
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: '#1e2a36' }, ticks: { color: '#6b7280' } },
        y: { grid: { display: false }, ticks: { color: '#c9cdd3' } }
      }
    }
  });

  const resCtx = document.getElementById('resistance-chart').getContext('2d');
  resistanceChart = new Chart(resCtx, {
    type: 'doughnut',
    data: {
      labels: ['נמוכה','בינונית','גבוהה','גבוהה מאד'],
      datasets: [{
        data: [0,0,0,0],
        backgroundColor: ['#2a9d8f','#e9c46a','#e63946','#ff4444'],
        borderColor: '#141b22',
        borderWidth: 2,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: 'bottom', labels: { color: '#c9cdd3', padding: 16 } }
      }
    }
  });
}

async function fetchData() {
  try {
    const resp = await fetch('/api/snapshot');
    const data = await resp.json();
    updateUI(data);
  } catch(e) {
    document.getElementById('connection-status').textContent = 'מנותק';
    document.getElementById('connection-status').className = 'status idle';
  }
}

function updateUI(d) {
  document.getElementById('campaign-name').textContent = d.campaign_name || '...';
  document.getElementById('kpi-total').textContent = d.total_calls || 0;
  document.getElementById('kpi-completed').textContent = d.completed_calls || 0;
  document.getElementById('kpi-active').textContent = d.active_sessions || 0;
  document.getElementById('kpi-conversion').textContent = (d.conversion_rate || 0) + '%';
  document.getElementById('kpi-avg-exchanges').textContent = d.avg_exchanges_per_call || 0;
  document.getElementById('kpi-tier-a').textContent = (d.tier_distribution || {})['A'] || 0;
  document.getElementById('update-time').textContent = 'עודכן: ' + new Date().toLocaleTimeString('he-IL');

  // Update funnel chart
  if (funnelChart && d.funnel) {
    const f = d.funnel;
    funnelChart.data.datasets[0].data = [
      f.opening || 0, f.exploration || 0, f.profiling || 0,
      f.persuasion || 0, f.commitment || 0, f.closing || 0
    ];
    funnelChart.update('none');
  }

  // Update resistance chart
  if (resistanceChart && d.resistance_distribution) {
    const r = d.resistance_distribution;
    resistanceChart.data.datasets[0].data = [
      r.low || 0, r.medium || 0, r.high || 0, r.very_high || 0
    ];
    resistanceChart.update('none');
  }

  // Update calls table
  const tbody = document.querySelector('#calls-table tbody');
  const calls = (d.calls || []).slice(-20).reverse();
  let html = '';
  calls.forEach((c, i) => {
    const tierClass = 'badge-' + (c.tier || 'B');
    const resClass = 'resistance-' + (c.resistance || 'medium');
    const statusText = c.status === 'active' ? '🟢 פעיל' : (c.status === 'completed' ? '✅ הסתיים' : '❌ ' + c.status);
    html += `<tr>
      <td>${i+1}</td>
      <td>${c.phone || ''}</td>
      <td>${c.name || ''}</td>
      <td><span class="badge ${tierClass}">${c.tier || 'B'}</span></td>
      <td>${c.current_state || ''}</td>
      <td class="${resClass}">${c.resistance || ''}</td>
      <td>${c.exchanges || 0}</td>
      <td>${statusText}</td>
    </tr>`;
  });
  tbody.innerHTML = html || '<tr><td colspan="8" style="text-align:center;color:#6b7280;">אין שיחות להצגה</td></tr>';
}

// SSE fallback — auto-refresh via polling
setInterval(fetchData, REFRESH_MS);
initCharts();
fetchData();
</script>
</body>
</html>"""

# ── FastAPI App ─────────────────────────────────────────
app = FastAPI(title="Predator Agent Dashboard", version="1.0")

# Store connected WebSocket clients
_ws_clients: List[WebSocket] = []


@app.get("/", response_class=HTMLResponse)
async def dashboard_root():
    """Serve the live dashboard HTML."""
    return HTMLResponse(content=DASHBOARD_HTML)


@app.get("/api/snapshot")
async def api_snapshot():
    """Get full dashboard snapshot."""
    return JSONResponse(content=get_dashboard_snapshot())


@app.get("/api/stats")
async def api_stats():
    """Get basic stats."""
    snap = get_dashboard_snapshot()
    return JSONResponse(content={
        "total_calls": snap["total_calls"],
        "completed_calls": snap["completed_calls"],
        "active_sessions": snap["active_sessions"],
        "conversion_rate": snap["conversion_rate"],
        "avg_exchanges": snap["avg_exchanges_per_call"],
        "campaign_name": snap["campaign_name"],
        "started_at": snap["started_at"],
    })


@app.get("/api/funnel")
async def api_funnel():
    """Get conversion funnel data."""
    snap = get_dashboard_snapshot()
    return JSONResponse(content={
        "funnel": snap["funnel"],
        "total": snap["total_calls"],
        "conversion_rate": snap["conversion_rate"],
    })


@app.get("/api/calls")
async def api_calls(limit: int = 50):
    """Get recent call records."""
    snap = get_dashboard_snapshot()
    calls = snap["calls"][-limit:]
    return JSONResponse(content={"calls": calls, "total": len(calls)})


@app.get("/api/resistance")
async def api_resistance():
    """Get resistance distribution."""
    snap = get_dashboard_snapshot()
    return JSONResponse(content={
        "distribution": snap["resistance_distribution"],
        "persona_distribution": snap["persona_distribution"],
    })


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """WebSocket for real-time dashboard updates."""
    await ws.accept()
    _ws_clients.append(ws)
    try:
        while True:
            await ws.receive_text()  # Keep alive
    except WebSocketDisconnect:
        _ws_clients.remove(ws)
    except Exception:
        if ws in _ws_clients:
            _ws_clients.remove(ws)


async def broadcast_update():
    """Push update to all connected WebSocket clients."""
    snapshot = get_dashboard_snapshot()
    message = json.dumps(snapshot, ensure_ascii=False)
    disconnected = []
    for ws in _ws_clients:
        try:
            await ws.send_text(message)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        if ws in _ws_clients:
            _ws_clients.remove(ws)


def start_dashboard(host: str = "0.0.0.0", port: int = 8080):
    """Start the dashboard server (blocking)."""
    logger.info(f"Starting dashboard on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")


def start_dashboard_async(host: str = "0.0.0.0", port: int = 8080):
    """Start the dashboard server in the background (non-blocking)."""
    import threading
    t = threading.Thread(target=start_dashboard, args=(host, port), daemon=True)
    t.start()
    logger.info(f"Dashboard started in background on {host}:{port}")
    return t
