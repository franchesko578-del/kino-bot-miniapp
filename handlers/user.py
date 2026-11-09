import html
from datetime import datetime
from urllib.parse import quote

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from config import ADMIN_IDS, WEBAPP_URL
from database.db import Movie, S, S_int, SessionLocal, User
from utils.keyboards import B, kb, webapp_btn
from utils.services import (
    deliver_movie, handle_referral, ref_count, ref_link, status_text, subs_markup, top_movies,
    touch_user, vip_active,
)

router = Router()
BACK = [B("◀️ Orqaga", "black", callback_data="menu:home")]


def main_menu(user_id: int):
    rows = []
    if WEBAPP_URL:
        rows.append([webapp_btn("🎬 " + S("btn_app"), WEBAPP_URL, "blue")])
    rows.append([B(S("btn_top"), "yellow", callback_data="menu:top"),
                 B(S("btn_new"), "blue", callback_data="menu:new")])
    rows.append([B(S("btn_vip"), "green", callback_data="vip:buy"),
                 B(S("btn_profile"), "black", callback_data="menu:profile")])
    if S_int("ref_bonus_days") > 0:
        rows.append([B("🎁 " + S("btn_ref"), "yellow", callback_data="menu:ref")])
    if user_id in ADMIN_IDS:
        rows.append([B("🛠 Admin panel", "red", callback_data="adm:home")])
    return kb(*rows)


def welcome_text() -> str:
    text = f"<b>{html.escape(S('bot_name'))}</b>\n\n{S('welcome_text')}"
    if S("announcement"):
        text += f"\n\n📣 {S('announcement')}"
    return text


async def show(call: CallbackQuery, text: str, markup):
    """Xabarni joyida yangilaydi (chat to'lib ketmasin). Video xabar bo'lsa — yangisini yuboradi."""
    try:
        await call.message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        await call.message.answer(text, reply_markup=markup)
    await call.answer()


async def send_result(bot, message: Message, res: dict):
    """deliver_movie natijasini foydalanuvchiga ko'rsatadi."""
    st = res["status"]
    if st == "ok":
        return
    if st == "not_subscribed":
        await message.answer(
            "🎬 Kinoni olish uchun quyidagi kanallarga a'zo bo'ling, so'ng «Tekshirish»ni bosing.",
            reply_markup=subs_markup(res["channels"], res["code"]),
        )
    elif st == "vip_only":
        await message.answer(status_text(res), reply_markup=kb([B("⭐ VIP olish", "green", callback_data="vip:buy")]))
    else:
        await message.answer(res.get("detail") or status_text(res))


@router.message(CommandStart())
async def start(message: Message, command: CommandObject):
    _, created = await touch_user(message.from_user, return_created=True)
    arg = command.args or ""
    if arg.startswith("r_") and arg[2:].isdigit() and created:  # faqat yangi foydalanuvchi hisoblanadi
        await handle_referral(message.bot, message.from_user.id, int(arg[2:]))
    if arg == "top":
        text, markup = movies_text_markup("🔥 <b>TOP 10</b>", await top_movies(10))
        return await message.answer(text, reply_markup=markup)
    if arg.startswith("m_"):  # ulashilgan havola: /start m_KOD
        res = await deliver_movie(message.bot, message.chat.id, message.from_user.id, arg[2:])
        return await send_result(message.bot, message, res)
    await message.answer(welcome_text(), reply_markup=main_menu(message.from_user.id))


@router.message(Command("id"))
async def my_id(message: Message):
    await message.answer(f"Telegram ID: <code>{message.from_user.id}</code>")


@router.message(Command("admin"))
async def not_admin(message: Message):
    # admin.router oldin ishlaydi; bu yerga faqat admin bo'lmaganlar tushadi
    await message.answer(
        f"🚫 Siz admin emassiz.\nSizning ID: <code>{message.from_user.id}</code>\n"
        "Egasi bu ID ni Render → Environment → ADMIN_IDS ga qo'shsa, panel ochiladi."
    )


# ---------------- TOP 10 / Yangi kinolar ----------------
def movies_text_markup(title: str, movies):
    if not movies:
        return f"{title}\n\nHozircha kinolar yo'q.", kb(BACK)
    lines = [f"{i}. <b>{html.escape(m.title)}</b> · <code>{html.escape(m.code)}</code> · 👁 {m.views or 0}"
             for i, m in enumerate(movies, 1)]
    rows = [[B(f"▶️ {i}. {m.title}"[:40], "blue" if i % 2 else "green", callback_data=f"mv:{m.code}")]
            for i, m in enumerate(movies, 1)]
    return f"{title}\n\n" + "\n".join(lines) + "\n\nKinoni olish uchun tugmani bosing yoki kodni yuboring.", kb(*rows, BACK)


async def new_movies(limit: int = 10):
    async with SessionLocal() as s:
        return (await s.execute(select(Movie).order_by(Movie.id.desc()).limit(limit))).scalars().all()


@router.message(Command("top"))
async def top_cmd(message: Message):
    text, markup = movies_text_markup("🔥 <b>TOP 10</b>", await top_movies(10))
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "menu:top")
async def cb_top(call: CallbackQuery):
    await show(call, *movies_text_markup("🔥 <b>TOP 10</b>", await top_movies(10)))


@router.callback_query(F.data == "menu:new")
async def cb_new(call: CallbackQuery):
    await show(call, *movies_text_markup("🆕 <b>Yangi kinolar</b>", await new_movies(10)))


# ---------------- Profil ----------------
async def profile_text(user_id: int) -> str:
    async with SessionLocal() as s:
        u = await s.get(User, user_id)
    if vip_active(u):
        left = (u.vip_until - datetime.utcnow()).days
        vip = f"⭐ VIP faol — {u.vip_until:%d.%m.%Y} gacha ({left} kun qoldi)"
    else:
        vip = "VIP yo'q"
    return f"👤 <b>Profil</b>\n🆔 <code>{user_id}</code>\n{vip}"


@router.message(Command("vipinfo"))
async def vipinfo(message: Message):
    await message.answer(await profile_text(message.from_user.id))


@router.callback_query(F.data == "menu:profile")
async def cb_profile(call: CallbackQuery):
    await show(call, await profile_text(call.from_user.id), kb(BACK))


@router.callback_query(F.data == "menu:home")
async def cb_home(call: CallbackQuery):
    await show(call, welcome_text(), main_menu(call.from_user.id))


# ---------------- Kino olish tugmalari ----------------
@router.callback_query(F.data.startswith("chk:") | F.data.startswith("mv:"))
async def cb_movie(call: CallbackQuery):
    code = call.data.split(":", 1)[1]
    res = await deliver_movie(call.bot, call.message.chat.id, call.from_user.id, code)
    if res["status"] == "ok":
        await call.answer("✅ Kino yuborildi")
    elif res["status"] == "not_subscribed" and call.data.startswith("chk:"):
        await call.answer("❌ Hali hamma kanalga a'zo emassiz", show_alert=True)
    else:
        await call.answer()
        await send_result(call.bot, call.message, res)


@router.callback_query(F.data.startswith("pt:"))
async def cb_part(call: CallbackQuery):
    code, _, num = call.data[3:].rpartition(":")
    if not num.isdigit():
        return await call.answer()
    res = await deliver_movie(call.bot, call.message.chat.id, call.from_user.id, code, part=int(num))
    if res["status"] == "ok":
        await call.answer(f"📺 {num}-qism")
    else:
        await call.answer()
        await send_result(call.bot, call.message, res)


@router.callback_query(F.data == "menu:ref")
async def cb_ref(call: CallbackQuery):
    link = await ref_link(call.bot, call.from_user.id)
    n = await ref_count(call.from_user.id)
    text = (f"🎁 <b>Do'st taklif qilish</b>\n\nHar bir yangi do'stingiz uchun <b>+{S('ref_bonus_days')} kun VIP</b> olasiz.\n"
            f"👥 Taklif qilganlaringiz: <b>{n}</b>\n\n🔗 Sizning havolangiz:\n<code>{link}</code>")
    share = f"https://t.me/share/url?url={quote(link)}&text={quote('🎬 Kinolar boti — kodni yuboring, kino keladi!')}"
    await show(call, text, kb([B("📤 Do'stlarga yuborish", "green", url=share)], BACK))
