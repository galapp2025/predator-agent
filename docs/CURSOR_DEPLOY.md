# 🎯 PREDATOR AGENT — DEPLOYMENT PACKAGE
## חבילת פריסה מלאה לבדיקת צוות המשקיע
### תאריך: 13.07.2026 — סטטוס: ✅ מוכן לקרב

---

## ⚡ הפעלה מהירה (3 שורות)

```bash
cd /home/user/predator-agent
./start_outbound.sh       # חיוג יזום לצוות הבדיקה
# או
./start_battle.sh         # במקלדת ← סוכן (battle mode)
```

---

## 📁 מבנה הפרויקט — 25 קבצים

```
predator-agent/
├── 📄 start_battle.sh                 # הפעלה מהירה — battle mode
├── 📄 start_outbound.sh               # הפעלה מהירה — חיוג יזום
├── 📄 .env.example                    # תבנית API keys
├── 📁 data/
│   ├── tester_leads.csv               # ⭐ רשימת הבוחרים לטסט (3 שורות)
│   ├── inbound_whitelist.csv          # ⭐ רשימת שיחות נכנסות מסומנות
│   └── leads.csv                      # 10 בוחרים לדוגמה
├── 📁 docs/
│   ├── CURSOR_DEPLOY.md               # ⭐ המסמך הזה
│   └── tester-briefing.txt            # תקציר מפעיל
├── 📁 src/
│   ├── __init__.py
│   ├── main.py                        # ⭐ נקודת כניסה ראשית
│   ├── battle_mode.py                 # ⭐ סימולציית שיחה חיה
│   ├── 📁 agent/
│   │   └── predator.py                # ⭐ מכונת מצבים + LLM orchestrator
│   ├── 📁 llm/
│   │   ├── prompt_builder.py          # ⭐ V3 SABRA — 372 שורות עברית ילידית
│   │   └── slow_llm.py                # Claude Sonnet 4 — analyzer
│   ├── 📁 personas/
│   │   └── persona_base.py            # ⭐ 4 DISC פרסונות + Cartesia TTS
│   ├── 📁 state_machine/
│   │   └── states.py                  # 11 מצבי שיחה + מעברים
│   ├── 📁 persuasion/
│   │   ├── resistance_meter.py        # ⭐ מד התנגדות v2 מכויל
│   │   └── tactics.py                 # 13 טקטיקות (8 קלאסיות + 5 שחורות)
│   ├── 📁 telephony/
│   │   ├── outbound_dialer.py         # ⭐ LeadLoader + OutboundDialer
│   │   ├── inbound_handler.py         # ⭐ PreMarkedRegistry + InboundHandler
│   │   ├── call_queue.py              # ⭐ CallQueue — priority 1-3
│   │   └── sip_manager.py             # LiveKit SIP bridge
│   ├── 📁 profile/
│   │   └── disc_classifier.py         # D/I/S/C classifier
│   └── 📁 enrichment/
│       └── voter_context.py           # 5D voter profile
```

---

## 🚀 תרחיש 1 — חיוג יזום לצוות הבדיקה

```bash
# 1. ערוך את data/tester_leads.csv
#    החלף את המספרים 0500000001/2/3 במספרים האמיתיים של צוות הבדיקה
#    (או הוסף שורות חדשות)

# 2. ודא שיש .env עם API keys
cp .env.example .env
# ערוך .env: DEEPGRAM_API_KEY, CARTESIA_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY

# 3. הרץ
./start_outbound.sh
```

**מה קורה:**
1. הסוכן טוען את `data/tester_leads.csv`
2. לכל שורה — בונה CallRecord עם שם מלא + כתובת + סניף + תמיכה
3. מחייג (rate-limited: 10/דקה, עובד רק 9-21)
4. כל שיחה → `agent.process_voter_turn()` → 11 מצבים → LLM → TTS
5. שומר היסטוריה ב-`data/call_history.json`

---

## 🎮 תרחיש 2 — Battle Mode (טסטר במקלדת)

```bash
./start_battle.sh
```

**פקודות בתוך battle mode:**
- `/state` — הצג מצב נוכחי (פרסונה, state, התנגדות, טקטיקה, TTS)
- `/history` — היסטוריית שיחה מלאה
- `/prompt` — system prompt אחרון (עד 3000 תווים)
- `/tts` — פרמטרי TTS + LLM אחרונים
- `/reset` — אפס שיחה
- `/quit` — יציאה

**מה לבדוק:**
1. זיהוי AI — "אתה רובוט?" → סוכן מגיב באנושיות
2. סלנג — "תכלס", "וואלה", "אחי" → סוכן מתאים את המשלב
3. בדיקות תרבותיות → ANTI_DETECTION block
4. פסיכולוגיה שחורה — 5 טקטיקות פעילות
5. מסלול — 7-10 חילופים → closing
6. מד התנגדות — calibrated v2

---

## 📞 תרחיש 3 — שיחה נכנסת מסומנת מראש

המספרים ב-`data/inbound_whitelist.csv` (priority=3 — הכי גבוה) מקבלים מענה אנושי. מספרים אחרים → דחייה מנומסת.

---

## 🔑 API Keys נדרשים (.env)

```bash
DEEPGRAM_API_KEY=e93ed9ecca49444bc6cc650595a9587486a14d06
CARTESIA_API_KEY=sk_car_mr5CUtg4AquS6N5AJJmQUz
CARTESIA_VOICE_MALE=ff857c8e-e7f9-4afd-af42-dce9f3c5ab02
CARTESIA_VOICE_FEMALE=3e32f3c5-9ac0-4192-9994-87fdb277120f
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxxxxx
```

---

## 🧠 מה רץ מתחת למכסה המנוע

```
טסטר/בוחר (STT/מקלדת)
    ↓
agent.process_voter_turn()
    ├── resistance_meter.measure_resistance()  ← v2 מכויל
    ├── disc_classifier.classify()             ← D/I/S/C
    ├── predator._maybe_transition()           ← 11 מצבים + timeouts
    ├── tactics.get_tactic_for_moment()        ← 13 טקטיקות
    ├── slow_llm.analyze()                     ← Claude Sonnet 4 (כל 2 חילופים)
    └── prompt_builder.build()                 ← V3 SABRA
            ↓
        system_prompt + tts_params + llm_params
            ↓
        OpenAI GPT-4.1-mini → Hebrew response
            ↓
        Cartesia Sonic-3 → Hebrew voice (ff857c8e / 3e32f3c5)
```

**פרמטרי LLM (Hebrew-optimized):**
```python
temperature=0.82, max_tokens=150, top_p=0.92
frequency_penalty=0.15, presence_penalty=0.10
```

**פרמטרי TTS (Cartesia Sonic-3):**
```python
stability=0.38-0.50   # נמוך יותר מאנגלית — עברית גרונית
similarity=0.80-0.84  # גבוה יותר — שומר על זהות הקול בעברית
speed=0.90-1.12       # תלוי state — 1.12 ב-persuasion, 0.90 ב-closing
style_exaggeration=0.06-0.12  # נמוך מאוד — עברית לא צריכה דרמה
```

---

## 🛡️ Anti-AI Detection (v2 calibrated)

הסוכן מזהה ומגיב לניסיונות חשיפה:

| ביטוי מהבוחר | רמת התנגדות | תגובה |
|---|---|---|
| "אתה רובוט?" | HIGH (0.67) | טקטיקת reciprocity + deescalation |
| "אני לא מאמין" | VERY_HIGH (0.92) | objection_handling |
| "אתה בינה מלאכותית" | HIGH | social_proof |
| "זה מחשב" | HIGH | fear_then_relief |
| "הקלטה" | HIGH | emotional_time_travel |
| "עזוב אותי" | VERY_HIGH | three_cards (3 ניסיונות אחרונים) |

**word-boundary matching** — `שמע` לא מזהה ב-`שמעון`.

---

## 📊 מסלול השיחה (7-10 חילופים)

```
OPENING → EXPLORATION → PROFILING → PERSUASION → COMMITMENT → CLOSING
   │           │            │            │             │
   │           │            │            └─→ OBJECTION_HANDLING (אם התנגדות)
   │           │            │            └─→ SEED_PLANTING (אם 10+ חילופים)
   │           └─→ AMPLIFICATION (אם רגש חזק)
   └─→ DEESCALATION (אם HIGH/VERY_HIGH)
```

**Timeouts:**
- PERSUASION ≥ 8 חילופים → OBJECTION_HANDLING
- PERSUASION ≥ 10 חילופים → SEED_PLANTING
- COMMITMENT ≥ 8 חילופים → CLOSING
- OBJECTION_HANDLING ≥ 8 חילופים → SEED_PLANTING

---

## ✅ checklist לפני הבדיקה

- [ ] `.env` קיים עם 4 API keys
- [ ] `data/tester_leads.csv` עם מספרי צוות הבדיקה האמיתיים
- [ ] `data/inbound_whitelist.csv` עם אותם מספרים (priority=3)
- [ ] syntax check — `python3 -c "import ast, os; [ast.parse(open(os.path.join(r,f)).read()) for r,_,fs in os.walk('src') for f in fs if f.endswith('.py')]"`
- [ ] `./start_battle.sh` עובד (בדיקה מקומית)
- [ ] `./start_outbound.sh` עובד (שיחה יזומה)

---

## 🆘 גיבוי — הרצה ידנית

```bash
# Battle mode
cd /home/user/predator-agent
AGENT_MODE=battle PYTHONPATH=. python3 -m src.main

# Outbound dialer
cd /home/user/predator-agent
PYTHONPATH=. python3 -c "
import asyncio
from src.agent.predator import PredatorAgent
from src.telephony.outbound_dialer import OutboundDialer
from src.telephony.call_queue import CallQueue

async def main():
    agent = PredatorAgent()
    queue = CallQueue(agent)
    dialer = OutboundDialer(agent, queue=queue, csv_path='data/tester_leads.csv')
    records = await dialer.run_campaign_from_csv()
    print(f'Completed {len(records)} calls')

asyncio.run(main())
"

# Dev mode (סימולציה עם 9 קלטים)
cd /home/user/predator-agent
PYTHONPATH=. python3 -m src.main
```

---

## 📞 תמיכה

- תקציר מפעיל: `docs/tester-briefing.txt`
- קוד מקור: `src/`
- API keys: `.env.example`
