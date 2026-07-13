# 🎯 PREDATOR AGENT — העתק-הדבק ל-Cursor IDE
## מוכן לבדיקת צוות המשקיע — שיחה יזומה בעברית

---

## 📦 רשימת קבצים להעתקה (לפי סדר)

### שלב 1: ליבת הסוכן (3 קבצים)

**1. `src/llm/prompt_builder.py`** (701 שורות, ~16K תווים)
— V3 SABRA: קול ישראלי ילידי, פונטיקה, מילויי דיבור, אנטי-זיהוי AI, סלנג, בדיקות תרבותיות
```python
# העתק את כל תוכן הקובץ
```

**2. `src/personas/persona_base.py`** (164 שורות)
— 4 פרסונות (D/I/S/C), כיוונון Cartesia TTS לעברית
```python
# העתק את כל תוכן הקובץ
```

**3. `src/agent/predator.py`** (249 שורות)
— PredatorAgent head: פרמטרי LLM בעברית + state machine עם timeout fallbacks
```python
# העתק את כל תוכן הקובץ
```

### שלב 2: מודולי שיחה (3 קבצים)

**4. `src/persuasion/resistance_meter.py`** (235 שורות)
— מד התנגדות v3: VERY_HIGH/HIGH/MEDIUM/LOW, word-boundary regex, anti-AI detection, cross-category dedup
```python
# העתק את כל תוכן הקובץ
```

**5. `src/persuasion/tactics.py`**
— 8 טקטיקות קלאסיות + 5 טקטיקות פסיכולוגיה שחורה
```python
# העתק את כל תוכן הקובץ
```

**6. `src/state_machine/states.py`** (50 שורות)
— 11 מצבי שיחה + לוגיקת מעברים
```python
# העתק את כל תוכן הקובץ
```

### שלב 3: טלפוניה (3 קבצים)

**7. `src/telephony/outbound_dialer.py`** (195 שורות)
— LeadLoader מקובץ CSV + OutboundDialer לחיוג יזום
```python
# העתק את כל תוכן הקובץ
```

**8. `src/telephony/inbound_handler.py`** (183 שורות)
— PreMarkedRegistry לסימון מראש של נכנסות + InboundHandler
```python
# העתק את כל תוכן הקובץ
```

**9. `src/telephony/call_queue.py`** (111 שורות)
— CallQueue עם עדיפויות: whitelisted_inbound=3 > inbound=2 > outbound=1
```python
# העתק את כל תוכן הקובץ
```

### שלב 4: קבצי נתונים

**10. `data/leads.csv`**
```
phone,full_name,address,city,age,priority
050-1234567,ישראל ישראלי,הרצל 1,תל אביב,45,high
```

**11. `data/inbound_whitelist.csv`**
```
phone,full_name,role,priority
050-1111111,ראש צוות בדיקה,בודק מקצועי,3
```

### שלב 5: קבצי עזר (אופציונלי)

**12. `src/battle_mode.py`** (205 שורות) — CLI למבחן אש מול טסטר
**13. `src/main.py`** (94 שורות) — נקודת כניסה ראשית

---

## 🔑 משתני סביבה (`.env`)

```bash
DEEPGRAM_API_KEY=e93ed9ecca49444bc6cc650595a9587486a14d06
CARTESIA_API_KEY=sk_car_mr5CUtg4AquS6N5AJJmQUz
CARTESIA_VOICE_MALE=ff857c8e-e7f9-4afd-af42-dce9f3c5ab02
CARTESIA_VOICE_FEMALE=3e32f3c5-9ac0-4192-9994-87fdb277120f
OPENAI_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here
LIVEKIT_API_KEY=your_key_here
LIVEKIT_API_SECRET=your_key_here
TWILIO_ACCOUNT_SID=your_key_here
TWILIO_AUTH_TOKEN=your_key_here
```

---

## 🚀 הפעלה

```bash
# התקנת תלויות
pip install -r requirements.txt

# מבחן אש — Battle Mode (מול טסטר דרך מקלדת)
AGENT_MODE=battle PYTHONPATH=. python3 -m src.main

# או ישירות
PYTHONPATH=. python3 -m src.battle_mode
```

---

## 🧪 בדיקת מוכנות

```bash
cd predator-agent
python3 -m py_compile src/llm/prompt_builder.py && echo "✓ prompt_builder"
python3 -m py_compile src/personas/persona_base.py && echo "✓ persona_base"
python3 -m py_compile src/agent/predator.py && echo "✓ predator"
python3 -m py_compile src/persuasion/resistance_meter.py && echo "✓ resistance_meter"
python3 -m py_compile src/persuasion/tactics.py && echo "✓ tactics"
python3 -m py_compile src/state_machine/states.py && echo "✓ states"
python3 -m py_compile src/telephony/outbound_dialer.py && echo "✓ outbound_dialer"
python3 -m py_compile src/telephony/inbound_handler.py && echo "✓ inbound_handler"
python3 -m py_compile src/telephony/call_queue.py && echo "✓ call_queue"
python3 -m py_compile src/main.py && echo "✓ main"
python3 -m py_compile src/battle_mode.py && echo "✓ battle_mode"
echo "✅ כל 11 הקבצים תקינים תחבירית"
```

---

## ⚡ שימוש ב-Battle Mode

פקודות במהלך שיחה:
- `/state` — הצג מצב נוכחי
- `/history` — הצג היסטוריית שיחה
- `/prompt` — הצג system prompt מלא
- `/tts` — הצג פרמטרי TTS נוכחיים
- `/reset` — אפס שיחה
- `/quit` — יציאה

---

**מבנה תקייה נדרש ב-Cursor:**
```
predator-agent/
├── .env
├── requirements.txt
├── data/
│   ├── leads.csv
│   └── inbound_whitelist.csv
└── src/
    ├── __init__.py
    ├── main.py
    ├── battle_mode.py
    ├── agent/
    │   ├── __init__.py
    │   └── predator.py
    ├── llm/
    │   ├── __init__.py
    │   ├── prompt_builder.py
    │   └── slow_llm.py
    ├── personas/
    │   ├── __init__.py
    │   └── persona_base.py
    ├── persuasion/
    │   ├── __init__.py
    │   ├── resistance_meter.py
    │   └── tactics.py
    ├── state_machine/
    │   ├── __init__.py
    │   └── states.py
    ├── profile/
    │   ├── __init__.py
    │   └── disc_classifier.py
    ├── enrichment/
    │   ├── __init__.py
    │   └── voter_context.py
    ├── telephony/
    │   ├── __init__.py
    │   ├── outbound_dialer.py
    │   ├── inbound_handler.py
    │   ├── call_queue.py
    │   └── sip_manager.py
    └── utils/
        └── __init__.py
```
