# 🎬 Kino Bot + Mini App

Bot, foydalanuvchi Mini App, **admin Mini App** (`/admin`) va **bot ichidagi admin panel** (`/admin`).

## Render'ga o'rnatish
1. GitHub'ga yuklang (`.env` yuklanmaydi — `.gitignore` da).
2. Render → New Web Service → Build: `pip install -r requirements.txt`, Start: `uvicorn miniapp.app:app --host 0.0.0.0 --port $PORT`
3. **Environment** bo'limiga qo'shing:
   - `BOT_TOKEN` — BotFather tokeni
   - `ADMIN_IDS` — adminlar ID si, vergul bilan (`123,456`)
   - `DATABASE_URL` — Render PostgreSQL "Internal Database URL" (SQLite Render'da har deployda o'chib ketadi!)
   - `WEBAPP_URL` — `https://sizning-app.onrender.com` (bo'sh qolsa `RENDER_EXTERNAL_URL` olinadi)
4. BotFather → `/mybots` → Bot Settings → Menu Button → Web App URL ni kiriting.
5. Botga `/admin` yozing.

## Muhim
- Token va parollar faqat Render Environment'da. Token GitHub'ga tushib qolgan bo'lsa — BotFather'da `/revoke` qiling.
- Botni majburiy obuna kanallarida **admin** qiling.
- Bot faqat **1 nusxada** ishlasin (polling) — Render'da instance sonini 1 qoldiring.

## Tugma ranglari
Telegram faqat 🔵 ko'k (`primary`), 🟢 yashil (`success`) va 🔴 qizil (`danger`) tugmani qo'llaydi.
Sariq va qora uchun rasmiy rang yo'q — shuning uchun ular 🟨 / ⬛ belgisi bilan ko'rsatiladi.
Reklama tugmalari: `Matn | https://havola | ko'k/yashil/sariq/qora/qizil`.
