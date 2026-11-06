"""Bot ichidagi admin panel (/admin). Faqat ADMIN_IDS."""
import asyncio
import html
import re
from datetime import datetime

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy import func, select

from config import ADMIN_IDS, WEBAPP_URL
from database.db import (
    SETTINGS, S, Movie, Payment, SessionLocal, SubscriptionChannel, User,
    set_setting,
)
from utils.keyboards import B, back, kb, parse_buttons, webapp_btn
from utils.services import (
    CODE_RE, BROADCAST, backup_bytes, broadcast, grant_vip, remove_vip, stats,
    vip_active,
)

router = Router()
router.message.filter(F.from_user.id.in_(ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(ADMIN_IDS))


class AddMovie(StatesGroup):
    code = State(); title = State(); video = State()
class AddCh(StatesGroup):
    ref = State()
class Bc(StatesGroup):
    post = State(); buttons = State(); confirm = State()
class VipSt(StatesGroup):
    grant = State(); remove = State()
class UserSt(StatesGroup):
    search = State()
class SetSt(StatesGroup):
    value = State()


async def show(event, text: str, markup=None):
    """Callback bo'lsa xabarni tahrirlaydi, aks holda yangi yuboradi."""
    if isinstance(event, CallbackQuery):
        try:
            await event.message.edit_text(text, reply_markup=markup)
        except TelegramBadRequest:
            await event.message.answer(text, reply_markup=markup)
        await event.answer()
    else:
        await event.answer(text, reply_markup=markup)


def home_kb():
    rows = [
        [B("📊 Statistika", "blue", callback_data="adm:stats")],
        [B("🎬 Kino qo'shish", "green", callback_data="adm:addmovie"),
         B("🗂 Kinolar", "blue", callback_data="adm:movies:0")],
        [B("Foydalanuvchilar", "yellow", callback_data="adm:users"),
         B("VIP", "black", callback_data="adm:vip")],
        [B("📢 Kanallar", "blue", callback_data="adm:ch"),
         B("📣 Reklama", "green", callback_data="adm:bc")],
        [B("Sozlamalar", "yellow", callback_data="adm:set"),
         B("Zaxira", "black", callback_data="adm:backup")],
    ]
    if WEBAPP_URL:
        rows.append([webapp_btn("🧩 Admin Mini App", WEBAPP_URL + "/admin", "green")])
    return kb(*rows)


@router.message(Command("admin"))
async def admin_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🛠 <b>Admin panel</b>", reply_markup=home_kb())


@router.callback_query(F.data == "adm:home")
async def admin_home(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await show(call, "🛠 <b>Admin panel</b>", home_kb())


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Bekor qilindi.", reply_markup=kb(back()))


# ------------------------------ Statistika ------------------------------
@router.callback_query(F.data == "adm:stats")
async def adm_stats(call: CallbackQuery):
    s = await stats()
    await show(call, (
        "📊 <b>Statistika</b>\n\n"
        f"👥 Foydalanuvchilar: {s['users']} (bugun +{s['new_today']})\n"
        f"⭐ Faol VIP: {s['vip']}\n🚫 Bloklangan: {s['banned']}\n"
        f"🎬 Kinolar: {s['movies']} · 👁 {s['views']} ko'rish\n"
        f"📢 Kanallar: {s['channels']}\n"
        f"💳 To'lovlar: {s['payments']} ta · {s['stars']} ⭐"
    ), kb(back()))


# ------------------------------ Kino qo'shish ------------------------------
@router.callback_query(F.data == "adm:addmovie")
async def add_movie_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(AddMovie.code)
    await show(call, "🔑 Kino <b>kodini</b> yuboring (harf/raqam, masalan <code>101</code>).\n/cancel — bekor qilish")


@router.message(AddMovie.code, F.text)
async def add_movie_code(message: Message, state: FSMContext):
    code = message.text.strip()
    if not CODE_RE.match(code):
        return await message.answer("❌ Kod faqat harf, raqam, - va _ dan iborat bo'lsin (1–50 belgi).")
    await state.update_data(code=code)
    await state.set_state(AddMovie.title)
    await message.answer("🎬 Kino <b>nomini</b> yuboring:")


@router.message(AddMovie.title, F.text)
async def add_movie_title(message: Message, state: FSMContext):
    await state.update_data(title=message.text.strip()[:255])
    await state.set_state(AddMovie.video)
    await message.answer("📹 Endi <b>videoni</b> yuboring:")


async def save_movie(code: str, title: str, file_id: str) -> bool:
    """True = yangi, False = yangilandi."""
    async with SessionLocal() as s:
        m = (await s.execute(select(Movie).where(func.lower(Movie.code) == code.lower()))).scalar_one_or_none()
        if m:
            m.title, m.file_id = title, file_id
        else:
            s.add(Movie(code=code, title=title, file_id=file_id))
        await s.commit()
        return m is None


def video_file_id(message: Message):
    if message.video:
        return message.video.file_id
    if message.document and (message.document.mime_type or "").startswith("video/"):
        return message.document.file_id


@router.message(AddMovie.video, F.video | F.document)
async def add_movie_video(message: Message, state: FSMContext):
    fid = video_file_id(message)
    if not fid:
        return await message.answer("❌ Bu video emas. Video yuboring.")
    d = await state.get_data()
    new = await save_movie(d["code"], d["title"], fid)
    await state.clear()
    await message.answer(
        f"✅ Kino {'qo‘shildi' if new else 'yangilandi'}: <b>{html.escape(d['title'])}</b> (<code>{html.escape(d['code'])}</code>)",
        reply_markup=kb([B("➕ Yana qo'shish", "green", callback_data="adm:addmovie")], back()),
    )


@router.message(StateFilter(None), F.video, F.caption.contains("|"))
async def quick_add(message: Message):
    """Eski usul: videoga 'KOD | NOM' izoh yozib yuborish."""
    code, title = [x.strip() for x in message.caption.split("|", 1)]
    if not CODE_RE.match(code) or not title:
        return await message.answer("❌ Format: KOD | KINO NOMI")
    new = await save_movie(code, title[:255], message.video.file_id)
    await message.answer(f"✅ Kino {'qo‘shildi' if new else 'yangilandi'}!")


# ------------------------------ Kinolar ro'yxati ------------------------------
PAGE = 8


@router.callback_query(F.data.startswith("adm:movies:"))
async def movies_list_cb(call: CallbackQuery):
    await render_movies(call, int(call.data.split(":")[2]))


async def render_movies(call: CallbackQuery, page: int):
    async with SessionLocal() as s:
        total = await s.scalar(select(func.count(Movie.id)))
        items = (await s.execute(select(Movie).order_by(Movie.id.desc()).offset(page * PAGE).limit(PAGE))).scalars().all()
    rows, lines = [], []
    for m in items:
        lines.append(f"{'⭐' if m.vip_only else '🆓'} <code>{html.escape(m.code)}</code> — {html.escape(m.title)} · 👁 {m.views or 0}")
        rows.append([B(f"🗑 {m.code}", "red", callback_data=f"adm:mdel:{m.id}:{page}"),
                     B("VIP ↔ Ochiq", "yellow", callback_data=f"adm:mvip:{m.id}:{page}")])
    nav = []
    if page > 0:
        nav.append(B("◀️", "black", callback_data=f"adm:movies:{page-1}"))
    if (page + 1) * PAGE < total:
        nav.append(B("▶️", "black", callback_data=f"adm:movies:{page+1}"))
    await show(call, f"🗂 <b>Kinolar</b> ({total})\n\n" + ("\n".join(lines) or "Bo'sh"), kb(*rows, nav, back()))


@router.callback_query(F.data.startswith("adm:mdel:"))
async def movie_del(call: CallbackQuery):
    _, _, mid, page = call.data.split(":")
    async with SessionLocal() as s:
        m = await s.get(Movie, int(mid))
        if m:
            await s.delete(m)
            await s.commit()
    await render_movies(call, int(page))


@router.callback_query(F.data.startswith("adm:mvip:"))
async def movie_vip(call: CallbackQuery):
    _, _, mid, page = call.data.split(":")
    async with SessionLocal() as s:
        m = await s.get(Movie, int(mid))
        if m:
            m.vip_only = not m.vip_only
            await s.commit()
    await render_movies(call, int(page))


# ------------------------------ Foydalanuvchilar ------------------------------
@router.callback_query(F.data == "adm:users")
async def users_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    s = await stats()
    await show(call, f"👥 Foydalanuvchilar: <b>{s['users']}</b>\n⭐ VIP: {s['vip']} · 🚫 Ban: {s['banned']}",
               kb([B("🔎 ID / @username bo'yicha qidirish", "blue", callback_data="adm:usearch")], back()))


@router.callback_query(F.data == "adm:usearch")
async def user_search_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(UserSt.search)
    await show(call, "ID yoki @username yuboring:")


async def user_card(uid: int):
    async with SessionLocal() as s:
        u = await s.get(User, uid)
    if not u:
        return "❌ Topilmadi.", kb(back("adm:users"))
    vip = f"⭐ {u.vip_until:%d.%m.%Y} gacha" if vip_active(u) else "yo'q"
    text = (f"👤 <b>{html.escape(u.full_name or '-')}</b> @{u.username or '-'}\n🆔 <code>{u.id}</code>\n"
            f"VIP: {vip}\n{'🚫 BLOKLANGAN' if u.banned else '✅ Faol'}\n"
            f"Qo'shilgan: {u.created_at:%d.%m.%Y}" if u.created_at else f"🆔 {u.id}")
    ban = (B("✅ Blokdan chiqarish", "green", callback_data=f"adm:uban:{uid}:0") if u.banned
           else B("🚫 Bloklash", "red", callback_data=f"adm:uban:{uid}:1"))
    return text, kb([ban], [B("⭐ +30 kun VIP", "green", callback_data=f"adm:uvip:{uid}:30"),
                            B("VIP ni olish", "red", callback_data=f"adm:uunvip:{uid}")], back("adm:users"))


@router.message(UserSt.search, F.text)
async def user_search(message: Message, state: FSMContext):
    q = message.text.strip().lstrip("@")
    async with SessionLocal() as s:
        cond = User.id == int(q) if q.isdigit() else func.lower(User.username) == q.lower()
        u = (await s.execute(select(User).where(cond))).scalars().first()
    await state.clear()
    text, markup = await user_card(u.id) if u else ("❌ Topilmadi.", kb(back("adm:users")))
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("adm:uban:"))
async def user_ban(call: CallbackQuery):
    _, _, uid, flag = call.data.split(":")
    async with SessionLocal() as s:
        u = await s.get(User, int(uid))
        if u:
            u.banned = flag == "1"
            await s.commit()
    await show(call, *await user_card(int(uid)))


@router.callback_query(F.data.startswith("adm:uvip:"))
async def user_vip(call: CallbackQuery):
    _, _, uid, days = call.data.split(":")
    await grant_vip(int(uid), int(days))
    await show(call, *await user_card(int(uid)))


@router.callback_query(F.data.startswith("adm:uunvip:"))
async def user_unvip(call: CallbackQuery):
    uid = int(call.data.split(":")[2])
    await remove_vip(uid)
    await show(call, *await user_card(uid))


# ------------------------------ VIP ------------------------------
@router.callback_query(F.data == "adm:vip")
async def vip_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await show(call, "⭐ <b>VIP boshqaruvi</b>", kb(
        [B("➕ VIP berish", "green", callback_data="adm:vgrant"), B("➖ VIP olish", "red", callback_data="adm:vremove")],
        [B("📋 Faol VIPlar", "yellow", callback_data="adm:vlist"), B("💳 To'lovlar", "blue", callback_data="adm:pay")],
        back()))


@router.callback_query(F.data == "adm:vgrant")
async def vgrant(call: CallbackQuery, state: FSMContext):
    await state.set_state(VipSt.grant)
    await show(call, "Yuboring: <code>USER_ID KUN</code>\nMasalan: <code>123456789 30</code>")


@router.message(VipSt.grant, F.text)
async def vgrant_do(message: Message, state: FSMContext):
    p = message.text.split()
    if len(p) != 2 or not all(x.isdigit() for x in p) or not 1 <= int(p[1]) <= 3650:
        return await message.answer("❌ Format: USER_ID KUN")
    ok = await grant_vip(int(p[0]), int(p[1]))
    await state.clear()
    await message.answer(f"✅ {p[0]} ga {p[1]} kun VIP berildi." if ok else "❌ Foydalanuvchi bazada yo'q (u botga /start bosishi kerak).",
                         reply_markup=kb(back("adm:vip")))


@router.callback_query(F.data == "adm:vremove")
async def vremove(call: CallbackQuery, state: FSMContext):
    await state.set_state(VipSt.remove)
    await show(call, "VIP olinadigan <b>USER_ID</b> ni yuboring:")


@router.message(VipSt.remove, F.text)
async def vremove_do(message: Message, state: FSMContext):
    if not message.text.strip().isdigit():
        return await message.answer("❌ Faqat ID raqami.")
    ok = await remove_vip(int(message.text))
    await state.clear()
    await message.answer("✅ VIP olib tashlandi." if ok else "❌ Topilmadi.", reply_markup=kb(back("adm:vip")))


@router.callback_query(F.data == "adm:vlist")
async def vlist(call: CallbackQuery):
    async with SessionLocal() as s:
        us = (await s.execute(select(User).where(User.is_vip == True, User.vip_until > datetime.utcnow())  # noqa: E712
                              .order_by(User.vip_until).limit(30))).scalars().all()
    txt = "\n".join(f"<code>{u.id}</code> {html.escape(u.full_name or '')} — {u.vip_until:%d.%m.%Y}" for u in us) or "Yo'q"
    await show(call, f"📋 <b>Faol VIPlar</b>\n\n{txt}", kb(back("adm:vip")))


@router.callback_query(F.data == "adm:pay")
async def pay_list(call: CallbackQuery):
    async with SessionLocal() as s:
        ps = (await s.execute(select(Payment).order_by(Payment.id.desc()).limit(15))).scalars().all()
    txt = "\n".join(f"{p.created_at:%d.%m %H:%M} · <code>{p.user_id}</code> · {p.stars}⭐ · {p.days} kun" for p in ps) or "To'lovlar yo'q"
    await show(call, f"💳 <b>So'nggi to'lovlar</b>\n\n{txt}", kb(back("adm:vip")))


# ------------------------------ Kanallar ------------------------------
@router.callback_query(F.data == "adm:ch")
async def channels(call: CallbackQuery, state: FSMContext):
    await state.clear()
    async with SessionLocal() as s:
        chs = (await s.execute(select(SubscriptionChannel))).scalars().all()
    rows = [[B(f"🗑 {c.title}", "red", callback_data=f"adm:chdel:{c.id}")] for c in chs]
    txt = "\n".join(f"• {html.escape(c.title)} — {c.invite_link}" for c in chs) or "Kanallar yo'q"
    await show(call, f"📢 <b>Majburiy obuna kanallari</b>\n\n{txt}",
               kb(*rows, [B("➕ Kanal qo'shish", "green", callback_data="adm:chadd")], back()))


@router.callback_query(F.data == "adm:chadd")
async def ch_add(call: CallbackQuery, state: FSMContext):
    await state.set_state(AddCh.ref)
    await show(call, "Kanalni qo'shish uchun:\n• kanal <code>@username</code> yoki <code>-100...</code> ID yuboring, yoki\n"
                     "• kanaldan biror postni shu yerga forward qiling.\n\n⚠️ Bot kanalda <b>admin</b> bo'lishi shart.")


@router.message(AddCh.ref)
async def ch_add_do(message: Message, state: FSMContext):
    ref = None
    if message.forward_origin and getattr(message.forward_origin, "chat", None):
        ref = message.forward_origin.chat.id
    elif message.text:
        t = message.text.strip()
        ref = int(t) if re.fullmatch(r"-?\d+", t) else t if t.startswith("@") else None
    if ref is None:
        return await message.answer("❌ @username, ID yoki forward kerak.")
    try:
        chat = await message.bot.get_chat(ref)
        me = await message.bot.get_chat_member(chat.id, (await message.bot.me()).id)
        if me.status not in ("administrator", "creator"):
            return await message.answer("❌ Bot bu kanalda admin emas. Avval botni admin qiling.")
        link = f"https://t.me/{chat.username}" if chat.username else (await message.bot.create_chat_invite_link(chat.id)).invite_link
    except Exception as e:
        return await message.answer(f"❌ Kanal topilmadi yoki bot huquqi yetmaydi: {html.escape(str(e))}")
    async with SessionLocal() as s:
        c = (await s.execute(select(SubscriptionChannel).where(SubscriptionChannel.chat_id == chat.id))).scalar_one_or_none()
        if c:
            c.title, c.invite_link, c.is_active = chat.title, link, True
        else:
            s.add(SubscriptionChannel(chat_id=chat.id, title=chat.title or str(chat.id), invite_link=link))
        await s.commit()
    await state.clear()
    await message.answer(f"✅ Kanal qo'shildi: <b>{html.escape(chat.title or '')}</b>", reply_markup=kb(back("adm:ch")))


@router.callback_query(F.data.startswith("adm:chdel:"))
async def ch_del(call: CallbackQuery, state: FSMContext):
    async with SessionLocal() as s:
        c = await s.get(SubscriptionChannel, int(call.data.split(":")[2]))
        if c:
            await s.delete(c)
            await s.commit()
    await channels(call, state)


# ------------------------------ Reklama ------------------------------
COLORS_HELP = "ko'k / yashil / sariq / qora / qizil"


@router.callback_query(F.data == "adm:bc")
async def bc_start(call: CallbackQuery, state: FSMContext):
    if BROADCAST["running"]:
        return await show(call, f"⏳ Reklama yuborilmoqda: {BROADCAST['sent']}/{BROADCAST['total']}", kb(back()))
    await state.set_state(Bc.post)
    await show(call, "📣 Reklama postini yuboring (matn, rasm yoki video — nima yuborsangiz shuni o'zi ko'chiriladi).\n/cancel")


@router.message(Bc.post)
async def bc_post(message: Message, state: FSMContext):
    await state.update_data(chat=message.chat.id, mid=message.message_id)
    await state.set_state(Bc.buttons)
    await message.answer(
        "🎨 Post tagiga tugmalar qo'shasizmi? Har qatorga bittadan:\n"
        f"<code>Matn | https://havola | rang</code>\nRanglar: {COLORS_HELP}\n\n"
        "Masalan:\n<code>Kanalga o'tish | https://t.me/kanal | ko'k\nVIP olish | https://t.me/bot | yashil\n"
        "TOP 10 | https://t.me/bot | sariq\nUlashish | https://t.me/bot | qora</code>\n\n"
        "Tugmasiz yuborish uchun /skip",
    )


@router.message(Bc.buttons, F.text)
async def bc_buttons(message: Message, state: FSMContext):
    markup = None
    if message.text.strip() != "/skip":
        try:
            markup = parse_buttons(message.text)
        except ValueError as e:
            return await message.answer(f"❌ {e}")
        if not markup:
            return await message.answer("❌ Tugma topilmadi. Formatni tekshiring yoki /skip.")
    d = await state.get_data()
    await state.update_data(buttons=message.text if markup else "")
    await message.bot.copy_message(message.chat.id, d["chat"], d["mid"], reply_markup=markup)
    async with SessionLocal() as s:
        n = await s.scalar(select(func.count(User.id)).where(User.banned == False, User.blocked == False))  # noqa: E712
    await state.set_state(Bc.confirm)
    await message.answer(f"👆 Ko'rinishi shunday. <b>{n}</b> kishiga yuboriladi.",
                         reply_markup=kb([B("🚀 Yuborish", "green", callback_data="adm:bcgo"),
                                          B("❌ Bekor", "red", callback_data="adm:home")]))


@router.callback_query(Bc.confirm, F.data == "adm:bcgo")
async def bc_go(call: CallbackQuery, state: FSMContext):
    d = await state.get_data()
    await state.clear()
    markup = parse_buttons(d.get("buttons", ""))
    bot = call.bot

    async def sender(uid):
        await bot.copy_message(uid, d["chat"], d["mid"], reply_markup=markup)

    asyncio.create_task(broadcast(bot, sender, call.from_user.id))
    await show(call, "🚀 Reklama yuborish boshlandi (sekundiga ~20 ta). Tugagach hisobot keladi.", kb(back()))


# ------------------------------ Sozlamalar ------------------------------
@router.callback_query(F.data == "adm:set")
async def settings_menu(call: CallbackQuery, state: FSMContext):
    await state.clear()
    keys = list(SETTINGS)
    cols = ["blue", "yellow"]
    rows = [[B(SETTINGS[k][1][:28], cols[i % 2], callback_data=f"adm:se:{k}")] for i, k in enumerate(keys)]
    await show(call, "⚙️ <b>Sozlamalar</b> — o'zgartirmoqchi bo'lganingizni tanlang:", kb(*rows, back()))


@router.callback_query(F.data.startswith("adm:se:"))
async def setting_edit(call: CallbackQuery, state: FSMContext):
    key = call.data.split(":")[2]
    await state.set_state(SetSt.value)
    await state.update_data(key=key)
    await show(call, f"⚙️ <b>{SETTINGS[key][1]}</b>\n\nHozirgi: <code>{html.escape(S(key)) or '—'}</code>\n\n"
                     "Yangi qiymatni yuboring (/cancel — bekor):")


@router.message(SetSt.value, F.text)
async def setting_save(message: Message, state: FSMContext):
    key = (await state.get_data())["key"]
    try:
        await set_setting(key, message.text)
    except ValueError as e:
        return await message.answer(f"❌ {e}")
    await state.clear()
    await message.answer("✅ Saqlandi.", reply_markup=kb([B("⚙️ Sozlamalar", "blue", callback_data="adm:set")], back()))


# ------------------------------ Zaxira ------------------------------
@router.callback_query(F.data == "adm:backup")
async def backup(call: CallbackQuery):
    name = f"backup_{datetime.utcnow():%Y%m%d_%H%M}.json"
    await call.message.answer_document(BufferedInputFile(await backup_bytes(), name), caption="💾 Zaxira nusxa")
    await call.answer("Yuborildi")
