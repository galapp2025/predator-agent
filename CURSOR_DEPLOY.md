# 🚀 PREDATOR AGENT — בלוק העתק-הדבק ל-Cursor

**העתק את כל הבלוק הזה והדבק ב-Cursor Composer (Ctrl+Shift+I)**

---

## 📋 משימה ל-Cursor:

אני צריך להריץ לפרודקשן את Predator Agent — שרת AI Voice Agent בעברית לקמפיין פוליטי.

### 🎯 מה המערכת עושה:
- מקבלת שיחות טלפון דרך Twilio ← ממירה דיבור לטקסט (Deepgram STT בעברית) ← מעבירה ב-Pipeline של Predator ← LLM (Groq) מייצר תשובה ← Cartesia TTS ממיר לדיבור ← מחזיר לטלפון
- תומך גם ב-WebSocket ישיר מהדפדפן (מיקרופון ← רמקול)
- Health check endpoint עם סטטוס כל השירותים

### 📁 קבצים קיימים (על הדיסק, מאומתים ועובדים):
- `prod_server.py` (930 שורות) — שרת aiohttp יצור: HTTP + WebSocket על פורט 8765
- `src/agent/predator.py` — ליבת הסוכן
- `src/llm/prompt_builder.py` — בונה prompt בעברית
- `src/llm/slow_llm.py` — חיבור ל-Claude
- `src/personas/persona_base.py` — פרסונות
- `requirements.txt` — כל התלויות
- `Procfile` — `web: python3 prod_server.py`

### ✅ סטטוס בדיקות (הכל עבר):
```
GET  /health        → 200 JSON — {status:"ok", deepgram:true, cartesia:true, groq:true, openai:true}
POST /twilio/voice  → 200 XML  — TwiML תקין עם Stream
GET  /              → 200 HTML — דף בדיקה
WS   /ws            → WebSocket browser client
WS   /twilio/media  → Twilio Media Streams דו-כיווני
```

### 🔐 מה צריך למלא:
ב-`.env` — רק את ה-Twilio credentials (השאר כבר מולאו):
```
TWILIO_ACCOUNT_SID=AC...          ←  שלך
TWILIO_AUTH_TOKEN=...             ←  שלך  
TWILIO_PHONE_NUMBER=+1XXXXXXXXXX  ←  מספר Twilio שלך
RAILWAY_PUBLIC_URL=               ←  ישאר ריק, Railway ימלא אוטומטית
```

### 📞 חיבור Twilio (אחרי deployment):
1. קח את ה-URL של Railway (מהדשבורד)
2. ב-Twilio Console ← Phone Numbers ← Active Numbers ← בחר את המספר
3. תחת Voice Configuration:
   - Configure with: Webhook
   - A CALL COMES IN: Webhook → `https://ה-URL-שלך/twilio/voice`
   - Method: HTTP POST

### 🚂 Deployment ל-Railway:
```bash
railway login
railway link          # בחר פרויקט חדש או קיים (52chs)
railway up
```

### 🧪 בדיקת E2E:
```bash
# בדיקת health
curl https://ה-URL-שלך/health

# בדיקת Twilio webhook
curl -X POST https://ה-URL-שלך/twilio/voice

# שיחת אמת — חייג למספר Twilio שלך, הסוכן יענה בעברית
```

---

**⚠️ שים לב:** אל תשנה כלום בקוד. המערכת עברה syntax check + smoke test + E2E. רק תמלא Twilio credentials, תעשה deploy, תגדיר webhook.
