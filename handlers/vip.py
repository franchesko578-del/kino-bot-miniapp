from datetime import datetime, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

from config import ADMIN_IDS
from database.db import User, SessionLocal

router = Router()


@router.message(Command("grantvip"))
async def grant_vip(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    parts = (message.text or "").split()

    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await message.answer(
            "Foydalanish:\n/grantvip USER_ID KUN\n"
            "Masalan: /grantvip 123456789 30"
        )
        return

    user_id = int(parts[1])
    days = int(parts[2])

    async with SessionLocal() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            await message.answer("❌ Foydalanuvchi bazada topilmadi.")
            return

        user.is_vip = True
        user.vip_until = datetime.utcnow() + timedelta(days=days)
        await session.commit()

    await message.answer(f"✅ {user_id} ga {days} kunlik VIP berildi.")


@router.message(Command("removevip"))
async def remove_vip(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    parts = (message.text or "").split()

    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Foydalanish: /removevip USER_ID")
        return

    user_id = int(parts[1])

    async with SessionLocal() as session:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        user = result.scalar_one_or_none()

        if not user:
            await message.answer("❌ Foydalanuvchi topilmadi.")
            return

        user.is_vip = False
        user.vip_until = None
        await session.commit()

    await message.answer(f"✅ {user_id} VIP huquqi bekor qilindi.")


@router.message(Command("vipinfo"))
async def vip_info(message: Message):
    async with SessionLocal() as session:
        result = await session.execute(
            select(User).where(User.id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

        if user and user.is_vip and user.vip_until:
            if user.vip_until > datetime.utcnow():
                await message.answer(
                    f"⭐ VIP faol!\n"
                    f"Amal qilish muddati: {user.vip_until}"
                )
                return

    await message.answer("Sizda hozir faol VIP obunasi yo‘q.")
