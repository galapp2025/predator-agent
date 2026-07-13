#!/bin/bash
#═══════════════════════════════════════════════════════════════
# Predator Agent — OUTBOUND CAMPAIGN LAUNCHER
# חיוג יזום לרשימת הבוחרים (כולל צוות הבדיקה של המשקיע)
#═══════════════════════════════════════════════════════════════

set -e
cd "$(dirname "$0")"

echo "═══════════════════════════════════════════════════════════════"
echo "  📞 PREDATOR AGENT — OUTBOUND CAMPAIGN"
echo "  חיוג יזום לרשימת הבוחרים"
echo "═══════════════════════════════════════════════════════════════"
echo ""

if [ ! -f .env ]; then
  echo "⚠️  אין .env — יוצר מ-.env.example"
  cp .env.example .env
fi

export PYTHONPATH=.
python3 -c "
import asyncio
import sys
from dotenv import load_dotenv
load_dotenv()

from src.agent.predator import PredatorAgent
from src.telephony.outbound_dialer import OutboundDialer, LeadLoader
from src.telephony.call_queue import CallQueue, QueueItem

CSV_PATH = 'data/tester_leads.csv'

async def main():
    print('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
    print('  Predator Agent — Outbound Campaign Mode')
    print('  חיוג יזום לרשימת הבוחרים')
    print('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
    print()

    # Load leads
    loader = LeadLoader(CSV_PATH)
    leads = loader.load()
    print(f'📋 נטענו {len(leads)} בוחרים מ-{CSV_PATH}:')
    for i, lead in enumerate(leads, 1):
        print(f'   {i}. {lead[\"full_name\"]} — {lead[\"phone\"]} ({lead[\"city\"]})')
    print()

    if not leads:
        print('❌ לא נמצאו בוחרים. ערוך את data/tester_leads.csv')
        return

    # Build agent
    agent = PredatorAgent()
    queue = CallQueue(agent)
    dialer = OutboundDialer(agent, queue=queue, csv_path=CSV_PATH)

    # Run campaign
    print('🚀 מתחיל חיוג יזום...')
    print()
    records = await dialer.run_campaign_from_csv()
    print()
    print('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')
    print(f'  ✅ סיימנו {len(records)} שיחות')
    print(f'  📁 היסטוריה נשמרה ב: data/call_history.json')
    print('━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━')

asyncio.run(main())
"
