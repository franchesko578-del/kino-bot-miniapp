from datetime import datetime, timedelta
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, LabeledPrice, PreCheckoutQuery
from sqlalchemy import select

from database.db import SessionLocal, User

router = Router()

VIP_STARS = 100
VIP_DAYS = 30


@router.message(Command("buyvip"))
async def buy_vip(message: Message):
    await message.answer_invoice(
        title="VIP obuna",
        description="30 kunlik VIP obuna",
        payload="vip_30_days",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="VIP 30 kun", amount=VIP_STARS)]
    )


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    if query.invoice_payload == "vip_30_days" and query.currency == "XTR" and query.total_amount == VIP_STARS:
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="To‘lov noto‘g‘ri.")


@router.message(lambda m: m.successful_payment is not None)
async def successful_payment(message: Message):
    payment = message.successful_payment

    if payment.invoice_payload != "vip_30_days" or payment.currency != "XTR" or payment.total_amount != VIP_STARS:
        await message.answer("To‘lov tasdiqlanmadi.")
        return

    async with SessionLocal() as session:
        result = await session.execute(
            select(User).where(User.id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

        if not user:
            user = User(
                id=message.from_user.id,
                username=message.from_user.username,
                full_name=message.from_user.full_name
            )
            session.add(user)
            await session.flush()

        now = datetime.utcnow()
        start = user.vip_until if user.is_vip and user.vip_until and user.vip_until > now else now

        user.is_vip = True
        user.vip_until = start + timedelta(days=VIP_DAYS)

        await session.commit()

    await message.answer("VIP obunangiz 30 kunga faollashtirildi!")
