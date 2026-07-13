#!/bin/bash
#═══════════════════════════════════════════════════════════════
# Predator Agent — BATTLE MODE LAUNCHER
# מצב קרב — הפעלה מהירה לטסטר
#═══════════════════════════════════════════════════════════════

set -e
cd "$(dirname "$0")"

echo "═══════════════════════════════════════════════════════════════"
echo "  🎯 PREDATOR AGENT — BATTLE MODE"
echo "  הפעלה מהירה — הקלד בעברית ← ENTER"
echo "═══════════════════════════════════════════════════════════════"
echo ""

if [ ! -f .env ]; then
  echo "⚠️  אין .env — יוצר מ-.env.example"
  cp .env.example .env
  echo "📝 ערוך .env ומלא API keys אמיתיים:"
  echo "   DEEPGRAM_API_KEY, CARTESIA_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY"
  echo ""
fi

export PYTHONPATH=.
export AGENT_MODE=battle
python3 -m src.main
