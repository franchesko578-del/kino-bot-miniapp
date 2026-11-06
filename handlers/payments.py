from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery
from sqlalchemy import select

from database.db import Payment, S_int, SessionLocal
from utils.services import grant_vip

router = Router()


def vip_payload() -> str:
    # Narx/muddat payload ichida — sozlama o'zgarsa ham eski hisob-faktura to'g'ri ishlaydi
    return f"vip:{S_int('vip_stars')}:{S_int('vip_days')}"


def parse_payload(p: str):
    """'vip:STARS:DAYS' -> (stars, days) yoki None"""
    try:
        kind, stars, days = p.split(":")
        if kind != "vip":
            return None
        return int(stars), int(days)
    except Exception:
        return None


async def send_vip_invoice(bot, chat_id: int):
    stars, days = S_int("vip_stars"), S_int("vip_days")
    await bot.send_invoice(
        chat_id, title="⭐ VIP obuna", description=f"{days} kunlik VIP obuna",
        payload=vip_payload(), provider_token="", currency="XTR",
        prices=[LabeledPrice(label=f"VIP {days} kun", amount=stars)],
    )


@router.message(Command("buyvip"))
async def buy_cmd(message: Message):
    await send_vip_invoice(message.bot, message.chat.id)


@router.callback_query(F.data == "vip:buy")
async def buy_cb(call: CallbackQuery):
    await send_vip_invoice(call.bot, call.message.chat.id)
    await call.answer()


@router.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    p = parse_payload(q.invoice_payload)
    if p and q.currency == "XTR" and q.total_amount == p[0]:
        await q.answer(ok=True)
    else:
        await q.answer(ok=False, error_message="To'lov ma'lumotlari noto'g'ri.")


@router.message(F.successful_payment)
async def paid(message: Message):
    pay = message.successful_payment
    p = parse_payload(pay.invoice_payload)
    if not p or pay.currency != "XTR" or pay.total_amount != p[0]:
        return await message.answer("To'lov tasdiqlanmadi. Admin bilan bog'laning.")
    stars, days = p
    async with SessionLocal() as s:
        exists = await s.scalar(select(Payment.id).where(Payment.charge_id == pay.telegram_payment_charge_id))
        if exists:  # takroriy xabardan himoya
            return
        s.add(Payment(user_id=message.from_user.id, stars=stars, days=days,
                      charge_id=pay.telegram_payment_charge_id))
        await s.commit()
    from utils.services import touch_user
    await touch_user(message.from_user)
    await grant_vip(message.from_user.id, days)
    await message.answer(f"⭐ VIP obunangiz {days} kunga faollashtirildi! Rahmat 🎉")
