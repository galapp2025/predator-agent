#!/bin/bash
#═══════════════════════════════════════════════════════════════
# 🎙 PREDATOR AGENT — VOICE TEST LAUNCHER
# ═══════════════════════════════════════════════════════════════
# מריץ שרת WebSocket קולי:
#   מיקרופון ← Deepgram STT ← Predator Pipeline ← Cartesia TTS ← רמקול
#
# שימוש:
#   טרמינל 1: bash start_voice.sh
#   דפדפן:   פתח test_voice.html ← לחץ "התחל שיחה" ← דבר בעברית
#═══════════════════════════════════════════════════════════════

set -e
cd "$(dirname "$0")"

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  🎙 PREDATOR AGENT — VOICE TEST"
echo "═══════════════════════════════════════════════════════════"
echo ""

if [ ! -f .env ]; then
  echo "⚠️  יוצר .env מ-.env.example"
  cp .env.example .env
  echo "📝 ערוך .env ומלא API keys"
  echo ""
fi

export PYTHONPATH=.

# Check Python deps
python3 -c "import websockets, aiohttp, dotenv" 2>/dev/null || {
  echo "📦 מתקין תלויות..."
  pip install websockets aiohttp python-dotenv --break-system-packages -q 2>&1
}

echo "🔌 מפעיל שרת WebSocket קולי..."
echo ""
echo "   אחרי שהשרת עולה:"
echo "   1. פתח את test_voice.html בדפדפן (Drag & Drop)"
echo "   2. לחץ 'התחל שיחה'"
echo "   3. דבר בעברית — הסוכן יענה בקול"
echo "   4. Esc = סיום שיחה"
echo ""

python3 live_voice_server.py
