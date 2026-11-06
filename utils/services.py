import asyncio
import html
import json
import logging
import re
from datetime import datetime
from urllib.parse import quote

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter,
)
from aiogram.types import BufferedInputFile
from sqlalchemy import func, select, update

from config import ADMIN_IDS, WEBAPP_URL
from database.db import (
    Movie, Payment, S, S_on, SessionLocal, Setting, SubscriptionChannel, User,
)
from utils.keyboards import B, kb, webapp_btn

log = logging.getLogger(__name__)

CODE_RE = re.compile(r"^[A-Za-z0-9_\-]{1,50}$")


def vip_active(u: User | None) -> bool:
    return bool(u and u.is_vip and u.vip_until and u.vip_until > datetime.utcnow())


async def touch_user(tg_user) -> User:
    """Foydalanuvchini bazaga yozadi/yangilaydi."""
    async with SessionLocal() as s:
        u = await s.get(User, tg_user.id)
        if not u:
            u = User(id=tg_user.id)
            s.add(u)
        u.username = tg_user.username if hasattr(tg_user, "username") else tg_user.get("username")
        u.full_name = (
            tg_user.full_name if hasattr(tg_user, "full_name")
            else " ".join(filter(None, [tg_user.get("first_name"), tg_user.get("last_name")]))
        )
        u.last_seen = datetime.utcnow()
        u.blocked = False
        if u.vip_until and u.vip_until <= datetime.utcnow():
            u.is_vip, u.vip_until = False, None
        await s.commit()
        return u


async def missing_channels(bot: Bot, user_id: int) -> list[SubscriptionChannel]:
    async with SessionLocal() as s:
        chans = (await s.execute(
            select(SubscriptionChannel).where(SubscriptionChannel.is_active == True)  # noqa: E712
        )).scalars().all()
    out = []
    for ch in chans:
        try:
            m = await bot.get_chat_member(ch.chat_id, user_id)
            if m.status in ("left", "kicked") or (
                m.status == "restricted" and not getattr(m, "is_member", True)
            ):
                out.append(ch)
        except Exception as e:  # bot kanalda admin emas va hokazo — foydalanuvchini bloklamaymiz
            log.warning("Kanal tekshirilmadi %s: %s", ch.chat_id, e)
    return out


def subs_markup(channels, code: str):
    rows = [[B(f"📢 {c.title}", "blue", url=c.invite_link)] for c in channels]
    rows.append([B("✅ Tekshirish", "green", callback_data=f"chk:{code}")])
    return kb(*rows)


def render_caption(m: Movie) -> str:
    return (
        S("movie_caption")
        .replace("{title}", html.escape(m.title))
        .replace("{code}", html.escape(m.code))
        .replace("{views}", str(m.views or 0))
    )


async def movie_markup(bot: Bot, code: str):
    me = await bot.me()
    share = f"https://t.me/share/url?url={quote(f'https://t.me/{me.username}?start=m_{code}')}"
    rows = []
    if WEBAPP_URL:
        rows.append([webapp_btn("🎬 " + S("btn_app"), WEBAPP_URL, "blue")])
    rows.append([B(S("btn_vip"), "green", callback_data="menu:vip"),
                 B(S("btn_top"), "yellow", callback_data="menu:top")])
    rows.append([B(S("btn_share"), "black", url=share)])
    return kb(*rows)


async def deliver_movie(bot: Bot, chat_id: int, user_id: int, raw_code: str) -> dict:
    """Bot ham, Mini App ham shu funksiyani ishlatadi.
    status: ok | bad_code | not_found | banned | maintenance | vip_only | not_subscribed | error
    """
    code = (raw_code or "").strip()
    if not CODE_RE.match(code):
        return {"status": "bad_code"}
    is_admin = user_id in ADMIN_IDS

    async with SessionLocal() as s:
        u = await s.get(User, user_id)
        if u and u.banned and not is_admin:
            return {"status": "banned"}
        if S_on("maintenance") and not is_admin:
            return {"status": "maintenance"}
        vip = vip_active(u)

        movie = (await s.execute(
            select(Movie).where(func.lower(Movie.code) == code.lower())
        )).scalar_one_or_none()
        if not movie:
            return {"status": "not_found"}
        if movie.vip_only and not (vip or is_admin):
            return {"status": "vip_only", "title": movie.title}

        if S_on("force_sub") and not (vip or is_admin):
            miss = await missing_channels(bot, user_id)
            if miss:
                return {"status": "not_subscribed", "code": movie.code, "channels": miss}

        try:
            await bot.send_video(
                chat_id, movie.file_id,
                caption=render_caption(movie),
                reply_markup=await movie_markup(bot, movie.code),
                protect_content=S_on("protect_content"),
            )
        except TelegramBadRequest as e:
            # file_id yaroqsiz bo'lsa document sifatida urinib ko'ramiz
            try:
                await bot.send_document(chat_id, movie.file_id, caption=render_caption(movie),
                                        reply_markup=await movie_markup(bot, movie.code),
                                        protect_content=S_on("protect_content"))
            except Exception:
                log.error("Kino yuborilmadi %s: %s", code, e)
                return {"status": "error"}
        except TelegramForbiddenError:
            return {"status": "error", "detail": "Avval botga /start bosing"}

        await s.execute(update(Movie).where(Movie.id == movie.id).values(views=Movie.views + 1))
        await s.commit()
        return {"status": "ok", "title": movie.title}


STATUS_TEXT = {
    "bad_code": "❌ Kod noto'g'ri formatda. Faqat harf, raqam, <code>-</code> va <code>_</code> bo'lishi mumkin.",
    "not_found": "❌ Bunday kino kodi topilmadi. Kodni tekshirib qayta yuboring.",
    "banned": "🚫 Siz bloklangansiz.",
    "vip_only": "⭐ Bu kino faqat VIP foydalanuvchilar uchun.",
    "error": "⚠️ Kinoni yuborib bo'lmadi. Keyinroq urinib ko'ring.",
}


def status_text(res: dict) -> str:
    if res["status"] == "maintenance":
        return S("maintenance_text")
    return STATUS_TEXT.get(res["status"], "⚠️ Xatolik")


async def top_movies(limit: int = 10) -> list[Movie]:
    async with SessionLocal() as s:
        return (await s.execute(
            select(Movie).order_by(Movie.views.desc(), Movie.id.desc()).limit(limit)
        )).scalars().all()


# ---------------- Reklama (Telegram limitlariga mos) ----------------
BROADCAST = {"running": False, "sent": 0, "failed": 0, "blocked": 0, "total": 0}


async def broadcast(bot: Bot, sender, report_to: int | None = None):
    """sender(uid) — bitta foydalanuvchiga yuboradigan coroutine.
    Telegram: sekundiga ~30 xabar. Biz ~20/s yuboramiz, RetryAfter bo'lsa kutamiz."""
    if BROADCAST["running"]:
        return False
    async with SessionLocal() as s:
        ids = [r[0] for r in (await s.execute(
            select(User.id).where((User.banned == False) & (User.blocked == False))  # noqa: E712
        )).all()]
    BROADCAST.update(running=True, sent=0, failed=0, blocked=0, total=len(ids))
    blocked_ids = []
    try:
        for uid in ids:
            for _ in range(3):
                try:
                    await sender(uid)
                    BROADCAST["sent"] += 1
                    break
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after + 1)
                except TelegramForbiddenError:
                    BROADCAST["blocked"] += 1
                    blocked_ids.append(uid)
                    break
                except Exception:
                    BROADCAST["failed"] += 1
                    break
            await asyncio.sleep(0.05)
        if blocked_ids:
            async with SessionLocal() as s:
                await s.execute(update(User).where(User.id.in_(blocked_ids)).values(blocked=True))
                await s.commit()
    finally:
        BROADCAST["running"] = False
    if report_to:
        try:
            await bot.send_message(
                report_to,
                f"📣 Reklama tugadi\n✅ Yuborildi: {BROADCAST['sent']}\n"
                f"🚫 Bloklagan: {BROADCAST['blocked']}\n⚠️ Xato: {BROADCAST['failed']}\n"
                f"👥 Jami: {BROADCAST['total']}",
            )
        except Exception:
            pass
    return True


# ---------------- Zaxira nusxa ----------------
async def backup_bytes() -> bytes:
    from database.db import Base
    data = {"created_at": datetime.utcnow().isoformat(), "tables": {}}
    async with SessionLocal() as s:
        for table in Base.metadata.sorted_tables:
            rows = (await s.execute(select(table))).mappings().all()
            data["tables"][table.name] = [
                {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in r.items()}
                for r in rows
            ]
    return json.dumps(data, ensure_ascii=False, indent=1).encode()


async def send_backup(bot: Bot, chat_id: int):
    name = f"backup_{datetime.utcnow():%Y%m%d_%H%M}.json"
    await bot.send_document(chat_id, BufferedInputFile(await backup_bytes(), name),
                            caption="💾 Zaxira nusxa")


async def stats() -> dict:
    now = datetime.utcnow()
    async with SessionLocal() as s:
        one = lambda q: s.scalar(q)  # noqa: E731
        return {
            "users": await one(select(func.count(User.id))),
            "vip": await one(select(func.count(User.id)).where(User.is_vip == True, User.vip_until > now)),  # noqa: E712
            "banned": await one(select(func.count(User.id)).where(User.banned == True)),  # noqa: E712
            "new_today": await one(select(func.count(User.id)).where(User.created_at >= now.replace(hour=0, minute=0, second=0))),
            "movies": await one(select(func.count(Movie.id))),
            "views": await one(select(func.coalesce(func.sum(Movie.views), 0))),
            "payments": await one(select(func.count(Payment.id))),
            "stars": await one(select(func.coalesce(func.sum(Payment.stars), 0))),
            "channels": await one(select(func.count(SubscriptionChannel.id)).where(SubscriptionChannel.is_active == True)),  # noqa: E712
        }


async def grant_vip(user_id: int, days: int) -> bool:
    from datetime import timedelta
    async with SessionLocal() as s:
        u = await s.get(User, user_id)
        if not u:
            return False
        now = datetime.utcnow()
        start = u.vip_until if vip_active(u) else now
        u.is_vip, u.vip_until = True, start + timedelta(days=days)
        await s.commit()
        return True


async def remove_vip(user_id: int) -> bool:
    async with SessionLocal() as s:
        u = await s.get(User, user_id)
        if not u:
            return False
        u.is_vip, u.vip_until = False, None
        await s.commit()
        return True
