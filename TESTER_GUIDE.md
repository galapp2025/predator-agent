# 🎙️ Predator Agent — קישור בדיקה לצוות

## 🔗 קישור לבדיקה חיה
```
https://copper-drain-skin-powerpoint.trycloudflare.com
```

**פתחו בדפדפן** — דף הבדיקה נטען אוטומטית.

## 🧪 איך בודקים

### בדיקת דפדפן (2 דקות)
1. פתחו את הקישור בכרום (מחשב, לא בנייד)
2. תראו 5 נורות חיווי — כולן צריכות להיות ירוקות
3. לחצו **"התחל שיחה"** — הסוכן יענה בעברית
4. דברו למיקרופון — הסוכן יקשיב ויענה
5. השיחה תופיע בתמליל על המסך

### בדיקת Health Check
```
curl https://copper-drain-skin-powerpoint.trycloudflare.com/health
```
כל 5 השירותים צריכים להחזיר `true`.

## 📦 קבצי הפרויקט (GitHub)
```
https://github.com/galapp2025/predator-agent
```

## 📞 שילוב Twilio (לאחר Deployment)
ה-Webhook להגדיר ב-Twilio:
```
POST https://{railway-url}/twilio/voice
```

## 🔑 שירותים מחוברים
| שירות | סטטוס |
|--------|--------|
| Deepgram STT (עברית) | ✅ |
| Cartesia TTS | ✅ |
| Groq LLM | ✅ |
| OpenAI | ✅ |
| Twilio | ✅ |

---

**שימו לב:** השרת רץ על טונל Cloudflare — הקישור זמני. לגרסה קבועה יש לדפלוי ל-Railway.
