# 🎯 PREDATOR AGENT — דוח בדיקת 5 שיחות לייב

**תאריך:** 2026-07-13  
**גרסת סוכן:** Predator Agent v3 SABRA  
**צינור:** DISC ← State ← Resistance ← Tactic ← TTS ← Prompt  

---

## 📊 סיכום ביצועים

| מדד | ערך |
|---|---|
| סה"כ שיחות | 5 |
| סה"כ חילופים | 43 |
| ממוצע חילופים לשיחה | 8.6 |
| המרות (conversions) | **5/5 (100%)** |
| זמן הרצה | 0.3 שניות |
| Prompt ממוצע | 16,535 תווים |
| TTS speed ממוצע | 0.99 |
| החלפות פרסונה | 0 ⚠️ |

---

## 📋 5 הלידים — תוצאות

| # | שם | עיר | תמיכה | שכנוע | Tier | תוצאה | חילופים |
|---|---|---|---|---|---|---|---|
| 1 | אורי כהן | תל אביב | 0.72 | 0.428 | B | ✅ המרה | 8 |
| 2 | מיכל לוי | רמת גן | 0.48 | 0.307 | C | ✅ המרה | 9 |
| 3 | דוד אוחנה | באר שבע | 0.35 | 0.266 | C | ✅ המרה | 9 |
| 4 | רבקה אברמוב | נתניה | 0.18 | 0.216 | C | ✅ המרה | 9 |
| 5 | עומר גולן | הרצליה | 0.55 | 0.397 | C | ✅ המרה | 8 |

---

## 🔬 מעבר צינור (Pipeline)

### 📈 מצבים
```
exploration   ████ 4
profiling     ████ 4
persuasion    ████ 4
commitment    ████ 4
closing       ████ 4
gotv          █ 1
```

### 🛡 התנגדות
```
low           █████████████████████████████████ 33
high          █████ 5
medium        █████ 5
very_high     0
```

### 🎯 טקטיקות
```
אבדן / הפסד            ▌▌▌▌ 4
מסע בזמן רגשי          ▌▌▌▌ 4
יצירת חוב              ▌▌▌▌ 4
דלת קטנה               ▌▌▌▌ 4
אשליית בחירה מוגבלת    ▌▌▌▌ 4
3 הקלפים               ▌▌ 2
```

---

## ✅ מה עובד

| רכיב | סטטוס | הערה |
|---|---|---|
| State Machine | ✅ | מעברים תקינים: exploration→profiling→persuasion→commitment→closing |
| Resistance Meter | ✅ | מזהה low/medium/high, כולל anti-AI markers |
| DISC Classifier | ✅ | מזהה D/I/S/C לפי טקסט בעברית |
| Tactic Selector | ✅ | בוחר טקטיקה לפי state+resistance |
| TTS Params | ✅ | speed מכויל לפי state (0.81–1.18) |
| Prompt Builder | ✅ | ~16,500 תווים עקביים |
| Persuadability Scoring | ✅ | 5 אותות: support/demographic/geographic/branch/contact |
| Dashboard Hooks | ✅ | record_start/update/end נקראים |
| Whisper Hooks | ✅ | on_session_start/agent_response/end נקראים |

---

## ⚠️ בעיות שדורשות טיפול

### 1. **אפס החלפות פרסונה** (אזהרה)
**סיבה:** Slow LLM (Claude) לא מוגדר — אין `ANTHROPIC_API_KEY`.  
המערכת נופלת ל-fallback עם `confidence=0.3` שלא עובר את הסף `>0.6`.  
**פתרון:** הגדר `ANTHROPIC_API_KEY` במשתני הסביבה.

### 2. **רוב הלידים Tier C** (הערה)
**סיבה:** כל הערים/סניפים מקבלים בונוסים דומים (0.03–0.10). צריך יותר גיוון גיאוגרפי אמיתי.  
**פתרון:** הוסף לידים מערים חלשות (פריפריה בלי סניף) + הוסף `contact_history` אמיתי.

### 3. **Prompt אחיד מדי** (הערה)
כל ה-prompts סביב 16,500 תווים — אין הבדל משמעותי בין שיחות.  
**פתרון:** כוונן את `prompt_builder.py` להוסיף יותר הקשר דינמי לפי city/branch.

---

## 🚀 פקודות הרצה

```bash
# 1. כניסה לספריית הפרויקט
cd /home/user/predator-agent

# 2. ניקוד בוחרים
PYTHONPATH=. python3 -c "
from src.scoring.persuadability import PersudadabilityScorer
s = PersudadabilityScorer()
s.export_scored_csv('data/leads.csv', 'data/scored_leads.csv')
print('Done — scored_leads.csv ready')
"

# 3. הרצת 5 שיחות בדיקה
PYTHONPATH=. python3 simulations/test_harness_5_calls.py

# 4. בדיקת דוח JSON
PYTHONPATH=. python3 -c "
import json
with open('data/test_report_5_calls_*.json') as f:
    r = json.load(f)
for c in r['call_results']:
    print(f'{c[\"first_name\"]} {c[\"last_name\"]}: {c[\"outcome\"]} [{c[\"total_exchanges\"]} exchanges]')
"

# 5. Battle Mode (טסטר ידני)
PYTHONPATH=. python3 -m src.battle_mode
```

---

## 📦 קבצים חדשים

| קובץ | תיאור |
|---|---|
| `data/test_campaign_5_leads.csv` | 5 לידים מגוונים למבחן |
| `data/scored_5_leads.csv` | ניקוד persuadability + דירוג |
| `data/test_report_5_calls_*.json` | דוח בדיקה מלא (JSON) |
| `simulations/test_harness_5_calls.py` | Test harness אוטומטי |
| `docs/TEST_REPORT_5_CALLS.md` | דוח זה |

---

## 🔧 תיקונים מומלצים לפני production

1. **הגדר `ANTHROPIC_API_KEY`** — קריטי ל-persona switching
2. **הגדל גיוון לידים** — הוסף ערים ללא סניף, תמיכה נמוכה, שמות ממגזרים שונים
3. **בדוק resistance meter על שיחות אמיתיות** — כרגע 33/43 low, כנראה כי התסריטים לא אדוורסריים מספיק
4. **כוונן TTS speed** — טווח 0.81–1.18 סביר אבל הקצוות עלולים להישמע לא טבעיים
5. **הוסף `contact_history`** — כרגע 0 לכל הלידים, צריך data/contact_history.json
