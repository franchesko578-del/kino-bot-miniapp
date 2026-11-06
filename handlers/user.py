import html
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message

from config import ADMIN_IDS, WEBAPP_URL
from database.db import S, SessionLocal, User
from utils.keyboards import B, kb, webapp_btn
from utils.services import (
    deliver_movie, status_text, subs_markup, top_movies, touch_user, vip_active,
)

router = Router()


def main_menu(user_id: int):
    rows = []
    if WEBAPP_URL:
        rows.append([webapp_btn("🎬 " + S("btn_app"), WEBAPP_URL, "blue")])
    rows.append([B(S("btn_top"), "yellow", callback_data="menu:top"),
                 B(S("btn_vip"), "green", callback_data="menu:vip")])
    rows.append([B(S("btn_profile"), "black", callback_data="menu:profile")])
    if user_id in ADMIN_IDS:
        rows.append([B("🛠 Admin panel", "red", callback_data="adm:home")])
    return kb(*rows)


async def send_result(bot, message: Message, res: dict, code: str = ""):
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
        await message.answer(status_text(res), reply_markup=kb([B("⭐ VIP olish", "green", callback_data="menu:vip")]))
    else:
        await message.answer(res.get("detail") or status_text(res))


@router.message(CommandStart())
async def start(message: Message, command: CommandObject):
    await touch_user(message.from_user)
    arg = command.args or ""
    if arg.startswith("m_"):  # ulashilgan havola: /start m_KOD
        res = await deliver_movie(message.bot, message.chat.id, message.from_user.id, arg[2:])
        return await send_result(message.bot, message, res)
    text = f"<b>{html.escape(S('bot_name'))}</b>\n\n{S('welcome_text')}"
    if S("announcement"):
        text += f"\n\n📣 {S('announcement')}"
    text += f"\n\n🆔 ID: <code>{message.from_user.id}</code>"
    await message.answer(text, reply_markup=main_menu(message.from_user.id))


@router.message(Command("id"))
async def my_id(message: Message):
    await message.answer(f"Telegram ID: <code>{message.from_user.id}</code>")


async def top_text() -> str:
    movies = await top_movies(10)
    if not movies:
        return "Hozircha kinolar yo'q."
    lines = [f"{i}. <b>{html.escape(m.title)}</b> — <code>{html.escape(m.code)}</code> · 👁 {m.views or 0}"
             for i, m in enumerate(movies, 1)]
    return "🔥 <b>TOP 10</b>\n\n" + "\n".join(lines) + "\n\nKodni yuboring — kino keladi."


async def profile_text(user_id: int) -> str:
    async with SessionLocal() as s:
        u = await s.get(User, user_id)
    if vip_active(u):
        left = (u.vip_until - datetime.utcnow()).days
        vip = f"⭐ VIP faol — {u.vip_until:%d.%m.%Y} gacha ({left} kun)"
    else:
        vip = "VIP yo'q"
    return f"👤 <b>Profil</b>\n🆔 <code>{user_id}</code>\n{vip}"


@router.message(Command("top"))
async def top_cmd(message: Message):
    await message.answer(await top_text())


@router.message(Command("vipinfo"))
async def vipinfo(message: Message):
    await message.answer(await profile_text(message.from_user.id))


@router.callback_query(F.data == "menu:top")
async def cb_top(call: CallbackQuery):
    await call.message.answer(await top_text())
    await call.answer()


@router.callback_query(F.data == "menu:profile")
async def cb_profile(call: CallbackQuery):
    await call.message.answer(await profile_text(call.from_user.id))
    await call.answer()


@router.callback_query(F.data == "menu:vip")
async def cb_vip(call: CallbackQuery):
    stars, days = S("vip_stars"), S("vip_days")
    await call.message.answer(
        f"⭐ <b>VIP obuna</b>\n\n• Majburiy obunasiz foydalanish\n• VIP kinolarga kirish\n\n"
        f"💰 Narxi: {stars} ⭐ / {days} kun",
        reply_markup=kb([B(f"⭐ {stars} Stars — sotib olish", "green", callback_data="vip:buy")]),
    )
    await call.answer()


@router.callback_query(F.data.startswith("chk:"))
async def cb_check(call: CallbackQuery):
    res = await deliver_movie(call.bot, call.message.chat.id, call.from_user.id, call.data[4:])
    if res["status"] == "ok":
        await call.answer("✅ Kino yuborildi")
    elif res["status"] == "not_subscribed":
        await call.answer("❌ Hali hamma kanalga a'zo emassiz", show_alert=True)
    else:
        await call.answer()
        await send_result(call.bot, call.message, res)
