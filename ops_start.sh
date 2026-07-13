#!/usr/bin/env bash
# Predator Agent — operational stack
set -euo pipefail
cd "$(dirname "$0")"
export PYTHONPATH=.
source .venv/bin/activate 2>/dev/null || true

mkdir -p data logs

start_one() {
  local name="$1"; shift
  local log="logs/${name}.log"
  if pgrep -f "$1" >/dev/null 2>&1; then
    echo "[ok] $name already running"
    return
  fi
  nohup "$@" >"$log" 2>&1 &
  echo "[start] $name pid=$! log=$log"
}

echo "=== Predator OPS start ==="
start_one voice   .venv/bin/python live_voice_server.py
start_one dash    .venv/bin/python -m src.dashboard.live_dashboard
start_one whisper .venv/bin/python -m src.supervisor.whisper_mode
start_one worker  .venv/bin/python src/livekit_worker.py start

sleep 2
echo
echo "Voice agent :  http://localhost:8765/"
echo "Dashboard   :  http://localhost:8080/"
echo "Whisper     :  http://localhost:9001/whisper"
echo
echo "PSTN dial requires TWILIO_* + ENABLE_SIP_DIAL=true + SIP_CALL_WEBHOOK_URL"
echo "=== ready ==="
