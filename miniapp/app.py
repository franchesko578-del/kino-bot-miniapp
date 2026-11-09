import asyncio
import hashlib
import hmac
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import parse_qsl

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BufferedInputFile, LabeledPrice
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, or_, select

from config import ADMIN_IDS, BOT_TOKEN, OWNER_IDS
from database.db import (
    SETTINGS, S, S_int, Movie, MoviePart, Payment, SessionLocal, SubscriptionChannel, User,
    init_db, set_setting,
)
from handlers import admin, movies, payments, user
from utils.keyboards import parse_buttons
from utils.services import (
    CODE_RE, BROADCAST, add_admin, add_part, autopost, backup_bytes, broadcast, chart_text,
    daily_users, deliver_movie, delete_movie, grant_vip, load_admins, part_counts, ref_count,
    ref_link, remove_admin, remove_vip, send_backup, stats, top_movies, touch_user, vip_active,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("kino")

dp = Dispatcher()
# tartib muhim: admin (FSM) -> user -> payments -> kod bo'yicha qidiruv (oxirida)
dp.include_routers(admin.router, user.router, payments.router, movies.router)

bot: Bot | None = None
STATIC = Path(__file__).parent / "static"


async def daily_backup():
    while True:
        await asyncio.sleep(24 * 3600)
        for aid in list(ADMIN_IDS)[:1]:
            try:
                await send_backup(bot, aid)
            except Exception as e:
                log.warning("Avto-zaxira xatosi: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN topilmadi! Render > Environment ga qo'shing.")
    await init_db()
    await load_admins()
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.delete_webhook(drop_pending_updates=False)
    tasks = [asyncio.create_task(dp.start_polling(bot, handle_signals=False)),
             asyncio.create_task(daily_backup())]
    yield
    for t in tasks:
        t.cancel()
    await bot.session.close()


app = FastAPI(title="KINO BOT Mini App", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.exception_handler(Exception)
async def on_error(request, exc):
    log.exception("API xatosi: %s", request.url.path)
    return JSONResponse({"detail": f"Server xatosi: {type(exc).__name__}"}, status_code=500)


# ---------------------- Telegram initData tekshiruvi ----------------------
def verify_init_data(init_data: str) -> dict | None:
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        given = parsed.pop("hash", "")
        check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, given):
            return None
        if time.time() - int(parsed.get("auth_date", 0)) > 86400:
            return None
        return json.loads(parsed["user"])
    except Exception:
        return None


async def current_user(x_init_data: str = Header(default="")) -> dict:
    u = verify_init_data(x_init_data)
    if not u:
        raise HTTPException(401, "Telegram orqali oching")
    return u


async def owner_user(u: dict = Depends(current_user)) -> dict:
    if u["id"] not in OWNER_IDS:
        raise HTTPException(403, "Faqat bot egasi uchun")
    return u


async def admin_user(u: dict = Depends(current_user)) -> dict:
    if u["id"] not in ADMIN_IDS:
        raise HTTPException(403, "Faqat adminlar uchun")
    return u


# ---------------------- Sahifalar ----------------------
@app.get("/")
async def home():
    return FileResponse(STATIC / "index.html")


@app.get("/admin")
async def admin_page():
    return FileResponse(STATIC / "admin.html")


@app.get("/health")
async def health():
    return {"status": "ok"}


PUBLIC_KEYS = ["bot_name", "welcome_text", "announcement", "vip_stars", "vip_days", "btn_app", "btn_top",
               "btn_vip", "btn_profile", "color_primary", "color_green", "color_yellow", "color_black",
               "color_bg", "color_card", "maintenance"]


@app.get("/api/config")
async def public_config():
    return {k: S(k) for k in PUBLIC_KEYS}


# ---------------------- Foydalanuvchi API ----------------------
async def movies_json(ms):
    pc = await part_counts([m.id for m in ms])
    return [{"id": m.id, "code": m.code, "title": m.title, "views": m.views or 0,
             "vip_only": bool(m.vip_only), "parts": pc.get(m.id, 1)} for m in ms]


@app.post("/api/me")
async def me(u: dict = Depends(current_user)):
    row = await touch_user(u)
    return {"id": row.id, "name": row.full_name, "vip": vip_active(row),
            "vip_until": row.vip_until.isoformat() if vip_active(row) else None,
            "is_admin": row.id in ADMIN_IDS, "ref_link": await ref_link(bot, row.id),
            "ref_count": await ref_count(row.id), "ref_bonus": S_int("ref_bonus_days")}


class CodeIn(BaseModel):
    code: str
    part: int = 1


@app.post("/api/movie")
async def get_movie(body: CodeIn, u: dict = Depends(current_user)):
    res = await deliver_movie(bot, u["id"], u["id"], body.code, body.part)
    if res["status"] == "not_subscribed":
        res["channels"] = [{"title": c.title, "url": c.invite_link} for c in res["channels"]]
    return res


@app.get("/api/top")
async def top(u: dict = Depends(current_user)):
    return await movies_json(await top_movies(10))


@app.get("/api/search")
async def search(q: str, u: dict = Depends(current_user)):
    q = q.strip()[:50]
    if not q:
        return []
    async with SessionLocal() as s:
        rows = (await s.execute(select(Movie).where(or_(
            Movie.title.ilike(f"%{q}%"), func.lower(Movie.code) == q.lower())).limit(20))).scalars().all()
    return await movies_json(rows)


@app.post("/api/vip/invoice")
async def vip_invoice(u: dict = Depends(current_user)):
    stars, days = S_int("vip_stars"), S_int("vip_days")
    link = await bot.create_invoice_link(
        title="⭐ VIP obuna", description=f"{days} kunlik VIP obuna", payload=f"vip:{stars}:{days}",
        provider_token="", currency="XTR", prices=[LabeledPrice(label=f"VIP {days} kun", amount=stars)])
    return {"link": link}


# ---------------------- Admin API ----------------------
@app.get("/api/admin/stats")
async def a_stats(a=Depends(admin_user)):
    return await stats()


@app.get("/api/admin/chart")
async def a_chart(days: int = 14, a=Depends(admin_user)):
    return [{"d": f"{d:%d.%m}", "n": n} for d, n in await daily_users(min(max(days, 7), 60))]


@app.get("/api/admin/movies")
async def a_movies(q: str = "", a=Depends(admin_user)):
    async with SessionLocal() as s:
        st = select(Movie).order_by(Movie.id.desc()).limit(200)
        if q:
            st = st.where(or_(Movie.title.ilike(f"%{q}%"), Movie.code.ilike(f"%{q}%")))
        ms = (await s.execute(st)).scalars().all()
    return await movies_json(ms)


class MovieEdit(BaseModel):
    code: str | None = None
    title: str | None = None
    vip_only: bool | None = None


@app.put("/api/admin/movies/{mid}")
async def a_movie_edit(mid: int, body: MovieEdit, a=Depends(admin_user)):
    async with SessionLocal() as s:
        m = await s.get(Movie, mid)
        if not m:
            raise HTTPException(404)
        if body.code is not None:
            if not CODE_RE.match(body.code):
                raise HTTPException(400, "Kod noto'g'ri formatda")
            dup = await s.scalar(select(Movie.id).where(func.lower(Movie.code) == body.code.lower(), Movie.id != mid))
            if dup:
                raise HTTPException(400, "Bu kod band")
            m.code = body.code
        if body.title:
            m.title = body.title[:255]
        if body.vip_only is not None:
            m.vip_only = body.vip_only
        await s.commit()
    return {"ok": True}


@app.delete("/api/admin/movies/{mid}")
async def a_movie_del(mid: int, a=Depends(admin_user)):
    await delete_movie(mid)
    return {"ok": True}


@app.post("/api/admin/movies")
async def a_movie_upload(code: str = Form(...), title: str = Form(""), vip_only: bool = Form(False),
                         part: int = Form(1), file: UploadFile = File(...), a=Depends(admin_user)):
    """Mini App'dan video yuklash (Telegram Bot API limiti: 50 MB). Kattaroq video — botga yuboring."""
    code = code.strip()
    if not CODE_RE.match(code):
        raise HTTPException(400, "Kod noto'g'ri formatda")
    data = await file.read()
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(400, "Fayl 50 MB dan katta. Katta videoni botga «KOD | NOM» izohi bilan yuboring.")
    if part == 1 and not title.strip():
        raise HTTPException(400, "Kino nomini kiriting")
    msg = await bot.send_video(a["id"], BufferedInputFile(data, file.filename or "movie.mp4"),
                               caption=f"✅ Saqlandi: {code} ({part}-qism)")
    fid = msg.video.file_id if msg.video else msg.document.file_id
    if part > 1:  # serial: mavjud kinoga qism
        ok, res = await add_part(code, fid, part)
        if not ok:
            raise HTTPException(400, str(res))
        return {"ok": True, "info": f"{res}-qism qo'shildi"}
    async with SessionLocal() as s:
        m = (await s.execute(select(Movie).where(func.lower(Movie.code) == code.lower()))).scalar_one_or_none()
        new = m is None
        if m:
            m.title, m.file_id, m.vip_only = title[:255], fid, vip_only
        else:
            s.add(Movie(code=code, title=title[:255], file_id=fid, vip_only=vip_only))
        await s.commit()
    return {"ok": True, "info": (await autopost(bot, code, title)) if new else "Yangilandi"}


@app.get("/api/admin/users")
async def a_users(q: str = "", a=Depends(admin_user)):
    async with SessionLocal() as s:
        st = select(User).order_by(User.created_at.desc()).limit(50)
        if q:
            qq = q.strip().lstrip("@")
            st = st.where(User.id == int(qq) if qq.isdigit() else User.username.ilike(f"%{qq}%"))
        us = (await s.execute(st)).scalars().all()
    return [{"id": x.id, "name": x.full_name, "username": x.username, "vip": vip_active(x),
             "vip_until": x.vip_until.strftime("%d.%m.%Y") if vip_active(x) else None, "banned": bool(x.banned)}
            for x in us]


class UserAct(BaseModel):
    action: str  # ban | unban | vip | unvip
    days: int = 30


@app.post("/api/admin/users/{uid}")
async def a_user_act(uid: int, body: UserAct, a=Depends(admin_user)):
    if body.action in ("ban", "unban"):
        async with SessionLocal() as s:
            u = await s.get(User, uid)
            if not u:
                raise HTTPException(404)
            u.banned = body.action == "ban"
            await s.commit()
    elif body.action == "vip":
        if not 1 <= body.days <= 3650 or not await grant_vip(uid, body.days):
            raise HTTPException(400, "Foydalanuvchi topilmadi yoki kun noto'g'ri")
    elif body.action == "unvip":
        await remove_vip(uid)
    else:
        raise HTTPException(400)
    return {"ok": True}


@app.get("/api/admin/payments")
async def a_payments(a=Depends(admin_user)):
    async with SessionLocal() as s:
        ps = (await s.execute(select(Payment).order_by(Payment.id.desc()).limit(100))).scalars().all()
    return [{"user_id": p.user_id, "stars": p.stars, "days": p.days, "at": p.created_at.strftime("%d.%m.%Y %H:%M")} for p in ps]


@app.get("/api/admin/channels")
async def a_channels(a=Depends(admin_user)):
    async with SessionLocal() as s:
        return [{"id": c.id, "title": c.title, "url": c.invite_link, "chat_id": c.chat_id}
                for c in (await s.execute(select(SubscriptionChannel))).scalars().all()]


class ChIn(BaseModel):
    ref: str  # @username yoki -100... ID


@app.post("/api/admin/channels")
async def a_channel_add(body: ChIn, a=Depends(admin_user)):
    ref = body.ref.strip()
    try:
        chat = await bot.get_chat(int(ref) if ref.lstrip("-").isdigit() else ref)
        me_ = await bot.get_chat_member(chat.id, (await bot.me()).id)
        if me_.status not in ("administrator", "creator"):
            raise HTTPException(400, "Bot kanalda admin emas")
        link = f"https://t.me/{chat.username}" if chat.username else (await bot.create_chat_invite_link(chat.id)).invite_link
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"Kanal topilmadi: {e}")
    async with SessionLocal() as s:
        c = (await s.execute(select(SubscriptionChannel).where(SubscriptionChannel.chat_id == chat.id))).scalar_one_or_none()
        if c:
            c.title, c.invite_link, c.is_active = chat.title, link, True
        else:
            s.add(SubscriptionChannel(chat_id=chat.id, title=chat.title or str(chat.id), invite_link=link))
        await s.commit()
    return {"ok": True}


@app.delete("/api/admin/channels/{cid}")
async def a_channel_del(cid: int, a=Depends(admin_user)):
    async with SessionLocal() as s:
        c = await s.get(SubscriptionChannel, cid)
        if c:
            await s.delete(c)
            await s.commit()
    return {"ok": True}


class BcIn(BaseModel):
    text: str
    buttons: str = ""


@app.post("/api/admin/broadcast")
async def a_broadcast(body: BcIn, a=Depends(admin_user)):
    if BROADCAST["running"]:
        raise HTTPException(400, "Boshqa reklama yuborilmoqda")
    if not body.text.strip():
        raise HTTPException(400, "Matn bo'sh")
    try:
        markup = parse_buttons(body.buttons)
    except ValueError as e:
        raise HTTPException(400, str(e))

    async def sender(uid):
        await bot.send_message(uid, body.text, reply_markup=markup)

    asyncio.create_task(broadcast(bot, sender, a["id"]))
    return {"ok": True}


@app.get("/api/admin/broadcast")
async def a_broadcast_state(a=Depends(admin_user)):
    return BROADCAST


@app.get("/api/admin/settings")
async def a_settings(a=Depends(admin_user)):
    return [{"key": k, "label": v[1], "kind": v[2], "value": S(k)} for k, v in SETTINGS.items()]


class SetIn(BaseModel):
    key: str
    value: str


@app.put("/api/admin/settings")
async def a_setting_put(body: SetIn, a=Depends(admin_user)):
    try:
        await set_setting(body.key, body.value)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.get("/api/admin/backup")
async def a_backup(a=Depends(admin_user)):
    return Response(await backup_bytes(), media_type="application/json",
                    headers={"Content-Disposition": "attachment; filename=backup.json"})


@app.get("/api/admin/admins")
async def a_admins(a=Depends(admin_user)):
    return [{"id": i, "owner": i in OWNER_IDS} for i in sorted(ADMIN_IDS)] + [{"viewer_is_owner": a["id"] in OWNER_IDS}]


class AdminIn(BaseModel):
    ref: str  # ID yoki @username


@app.post("/api/admin/admins")
async def a_admin_add(body: AdminIn, a=Depends(owner_user)):
    q = body.ref.strip().lstrip("@")
    if q.isdigit():
        uid = int(q)
    else:
        async with SessionLocal() as s:
            u = (await s.execute(select(User).where(func.lower(User.username) == q.lower()))).scalars().first()
        if not u:
            raise HTTPException(400, "Bu username bazada yo'q. ID raqamini kiriting.")
        uid = u.id
    await add_admin(uid, a["id"])
    try:
        await bot.send_message(uid, "👮 Sizga admin huquqi berildi. /admin yozing.")
    except Exception:
        pass
    return {"ok": True}


@app.delete("/api/admin/admins/{uid}")
async def a_admin_del(uid: int, a=Depends(owner_user)):
    if not await remove_admin(uid):
        raise HTTPException(400, "Egani o'chirib bo'lmaydi")
    return {"ok": True}
