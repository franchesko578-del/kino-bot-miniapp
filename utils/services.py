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
from sqlalchemy import delete, func, select, update

from config import ADMIN_IDS, OWNER_IDS, WEBAPP_URL
from database.db import (
    Admin, Movie, MoviePart, Payment, S, S_int, S_on, SessionLocal, Setting, SubscriptionChannel, User,
)
from utils.keyboards import B, kb, webapp_btn

log = logging.getLogger(__name__)

CODE_RE = re.compile(r"^[A-Za-z0-9_\-]{1,50}$")


def vip_active(u: User | None) -> bool:
    return bool(u and u.is_vip and u.vip_until and u.vip_until > datetime.utcnow())


def _norm_user(t):
    """aiogram User yoki Mini App'dan kelgan dict -> (id, username, to'liq ism)"""
    if isinstance(t, dict):
        return t["id"], t.get("username"), " ".join(filter(None, [t.get("first_name"), t.get("last_name")]))
    return t.id, t.username, t.full_name


async def touch_user(tg_user, return_created: bool = False):
    """Foydalanuvchini bazaga yozadi/yangilaydi."""
    uid, username, full_name = _norm_user(tg_user)
    async with SessionLocal() as s:
        u = await s.get(User, uid)
        created = u is None
        if created:
            u = User(id=uid)
            s.add(u)
        u.username, u.full_name = username, full_name
        u.last_seen = datetime.utcnow()
        u.blocked = False
        if u.vip_until and u.vip_until <= datetime.utcnow():
            u.is_vip, u.vip_until = False, None
        await s.commit()
        return (u, created) if return_created else u


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


async def movie_markup(bot: Bot, code: str, parts=(1,), current: int = 1):
    me = await bot.me()
    share = f"https://t.me/share/url?url={quote(f'https://t.me/{me.username}?start=m_{code}')}"
    rows = []
    if len(parts) > 1:  # serial: qism tugmalari
        btns = [B(f"▶️ {n}" if n == current else str(n), "green" if n == current else "blue",
                  callback_data=f"pt:{code}:{n}") for n in list(parts)[:50]]
        rows += [btns[k:k + 5] for k in range(0, len(btns), 5)]
    if WEBAPP_URL:
        rows.append([webapp_btn("🎬 " + S("btn_app"), WEBAPP_URL, "blue")])
    rows.append([B(S("btn_vip"), "green", callback_data="vip:buy"),
                 B(S("btn_top"), "yellow", callback_data="menu:top")])
    rows.append([B(S("btn_share"), "black", url=share)])
    return kb(*rows)


async def deliver_movie(bot: Bot, chat_id: int, user_id: int, raw_code: str, part: int = 1) -> dict:
    """Bot ham, Mini App ham shu funksiyani ishlatadi.
    status: ok | bad_code | not_found | no_part | banned | maintenance | vip_only | not_subscribed | error
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

        extra = (await s.execute(
            select(MoviePart).where(MoviePart.movie_id == movie.id).order_by(MoviePart.number)
        )).scalars().all()
        numbers = [1] + [p.number for p in extra]
        file_id = movie.file_id
        if part != 1:
            row = next((p for p in extra if p.number == part), None)
            if not row:
                return {"status": "no_part"}
            file_id = row.file_id

        caption = render_caption(movie)
        if len(numbers) > 1:
            caption += f"\n📺 {part}-qism / {len(numbers)}"
        markup = await movie_markup(bot, movie.code, numbers, part)
        protect = S_on("protect_content")
        try:
            try:
                await bot.send_video(chat_id, file_id, caption=caption, reply_markup=markup, protect_content=protect)
            except TelegramBadRequest:  # file_id video bo'lmasa — document sifatida
                await bot.send_document(chat_id, file_id, caption=caption, reply_markup=markup, protect_content=protect)
        except TelegramForbiddenError:
            return {"status": "error", "detail": "Avval botga /start bosing"}
        except Exception as e:
            log.error("Kino yuborilmadi %s: %s", code, e)
            return {"status": "error"}

        await s.execute(update(Movie).where(Movie.id == movie.id).values(views=Movie.views + 1))
        await s.commit()
        return {"status": "ok", "title": movie.title}


STATUS_TEXT = {
    "bad_code": "❌ Kod noto'g'ri formatda. Faqat harf, raqam, <code>-</code> va <code>_</code> bo'lishi mumkin.",
    "not_found": "❌ Bunday kino kodi topilmadi. Kodni tekshirib qayta yuboring.",
    "no_part": "❌ Bunday qism yo'q.",
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


# ---------------- Qismlar (serial) ----------------
async def add_part(code: str, file_id: str, number: int | None = None) -> tuple[bool, int | str]:
    """Mavjud kinoga qism qo'shadi. number=None bo'lsa — keyingi raqam. -> (True, raqam) | (False, xato)"""
    async with SessionLocal() as s:
        m = (await s.execute(select(Movie).where(func.lower(Movie.code) == code.lower()))).scalar_one_or_none()
        if not m:
            return False, "Bunday kodli kino yo'q. Avval 1-qismni qo'shing."
        nums = [r[0] for r in (await s.execute(select(MoviePart.number).where(MoviePart.movie_id == m.id))).all()]
        if number is None:
            number = max([1] + nums) + 1
        if number < 1 or number > 500:
            return False, "Qism raqami 1–500 oralig'ida bo'lsin."
        if number == 1:
            m.file_id = file_id
        else:
            row = (await s.execute(select(MoviePart).where(MoviePart.movie_id == m.id, MoviePart.number == number))).scalar_one_or_none()
            if row:
                row.file_id = file_id
            else:
                s.add(MoviePart(movie_id=m.id, number=number, file_id=file_id))
        await s.commit()
        return True, number


async def part_counts(movie_ids: list[int]) -> dict[int, int]:
    """movie_id -> jami qismlar soni (1-qism bilan)."""
    if not movie_ids:
        return {}
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(MoviePart.movie_id, func.count(MoviePart.id)).where(MoviePart.movie_id.in_(movie_ids)).group_by(MoviePart.movie_id)
        )).all()
    return {mid: c + 1 for mid, c in rows}


async def delete_movie(movie_id: int):
    async with SessionLocal() as s:
        await s.execute(delete(MoviePart).where(MoviePart.movie_id == movie_id))
        await s.execute(delete(Movie).where(Movie.id == movie_id))
        await s.commit()


# ---------------- Kanalga avto-post ----------------
async def autopost(bot: Bot, code: str, title: str) -> str:
    """Yangi kinoni kanalga e'lon qiladi. Natija matni adminga ko'rsatiladi ('' = o'chiq)."""
    ch = S("post_channel").strip()
    if not S_on("autopost") or not ch:
        return ""
    me = await bot.me()
    link = f"https://t.me/{me.username}?start=m_{code}"
    markup = kb(
        [B("▶️ Ko'rish", "green", url=link)],
        [B("TOP 10", "yellow", url=f"https://t.me/{me.username}?start=top"),
         B(S("btn_share"), "black", url=f"https://t.me/share/url?url={quote(link)}")],
        [B("🤖 Botga o'tish", "blue", url=f"https://t.me/{me.username}")],
    )
    text = (f"🎬 <b>{html.escape(title)}</b>\n\n🔑 Kod: <code>{html.escape(code)}</code>\n\n"
            "👇 Tugmani bosing yoki botga kodni yuboring.")
    try:
        await bot.send_message(int(ch) if re.fullmatch(r"-?\d+", ch) else ch, text, reply_markup=markup)
        return "📢 Kanalga e'lon qilindi"
    except Exception as e:
        log.warning("Avto-post xatosi: %s", e)
        return f"⚠️ Kanalga e'lon yuborilmadi (bot kanalda admin bo'lsin): {html.escape(str(e))[:120]}"


# ---------------- Do'st taklif qilish ----------------
async def ref_link(bot: Bot, user_id: int) -> str:
    return f"https://t.me/{(await bot.me()).username}?start=r_{user_id}"


async def ref_count(user_id: int) -> int:
    async with SessionLocal() as s:
        return await s.scalar(select(func.count(User.id)).where(User.referred_by == user_id)) or 0


async def handle_referral(bot: Bot, new_uid: int, ref_id: int):
    """Faqat YANGI foydalanuvchi uchun chaqiriladi. Taklif qilganga VIP kun beradi."""
    bonus = S_int("ref_bonus_days")
    if bonus <= 0 or ref_id == new_uid:
        return
    async with SessionLocal() as s:
        ref, me = await s.get(User, ref_id), await s.get(User, new_uid)
        if not ref or ref.banned or not me or me.referred_by:
            return
        used = await s.scalar(select(func.count(User.id)).where(User.referred_by == ref_id)) or 0
        me.referred_by = ref_id
        await s.commit()
    if used >= S_int("ref_limit"):
        return
    await grant_vip(ref_id, bonus)
    try:
        await bot.send_message(ref_id, f"🎉 Do'stingiz botga qo'shildi! Sizga <b>+{bonus} kun VIP</b> berildi.")
    except Exception:
        pass


# ---------------- Kunlik yangi foydalanuvchilar ----------------
async def daily_users(days: int = 14) -> list[tuple]:
    from datetime import timedelta
    today = datetime.utcnow().date()
    first = today - timedelta(days=days - 1)
    async with SessionLocal() as s:
        rows = (await s.execute(
            select(User.created_at).where(User.created_at >= datetime.combine(first, datetime.min.time()))
        )).scalars().all()
    cnt: dict = {}
    for r in rows:
        if r:
            cnt[r.date()] = cnt.get(r.date(), 0) + 1
    return [(first + timedelta(days=i), cnt.get(first + timedelta(days=i), 0)) for i in range(days)]


def chart_text(rows: list[tuple]) -> str:
    mx = max([c for _, c in rows] + [1])
    lines = [f"{d:%d.%m} {'█' * (max(1, round(c / mx * 14)) if c else 0)} {c}" for d, c in rows]
    return "<pre>" + "\n".join(lines) + "</pre>"


# ---------------- Adminlar ----------------
async def load_admins():
    async with SessionLocal() as s:
        for (uid,) in (await s.execute(select(Admin.id))).all():
            ADMIN_IDS.add(uid)


async def add_admin(uid: int, by: int):
    async with SessionLocal() as s:
        if not await s.get(Admin, uid):
            s.add(Admin(id=uid, added_by=by))
            await s.commit()
    ADMIN_IDS.add(uid)


async def remove_admin(uid: int) -> bool:
    if uid in OWNER_IDS:
        return False
    async with SessionLocal() as s:
        await s.execute(delete(Admin).where(Admin.id == uid))
        await s.commit()
    ADMIN_IDS.discard(uid)
    return True
