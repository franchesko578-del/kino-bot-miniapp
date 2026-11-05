import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Command
from aiogram.types import Message
from sqlalchemy import select

from config import BOT_TOKEN
from database.db import init_db, SessionLocal, User
from handlers.admin import router as admin_router
from handlers.channels import router as channels_router
from handlers.movies import router as movies_router
from handlers.vip import router as vip_router
from handlers.payments import router as payments_router

logging.basicConfig(level=logging.INFO)

dp = Dispatcher()


@dp.message(CommandStart())
async def start_handler(message: Message):
    async with SessionLocal() as session:
        result = await session.execute(
            select(User).where(User.id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

        if not user:
            session.add(
                User(
                    id=message.from_user.id,
                    username=message.from_user.username,
                    full_name=message.from_user.full_name
                )
            )
        else:
            user.username = message.from_user.username
            user.full_name = message.from_user.full_name

        await session.commit()

    await message.answer(
        "🎬 KINO BOTga xush kelibsiz!\n\n"
        "Kino kodini yuboring va filmingizni oling.\n\n"
        f"🆔 ID: {message.from_user.id}\n"
        "⭐ VIP holati: /vipinfo"
    )


@dp.message(Command("id"))
async def id_handler(message: Message):
    await message.answer(f"Telegram ID: {message.from_user.id}")


dp.include_router(admin_router)
dp.include_router(channels_router)
dp.include_router(vip_router)
dp.include_router(payments_router)
dp.include_router(movies_router)


async def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN topilmadi!")

    await init_db()
    bot = Bot(token=BOT_TOKEN)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        print("KINO BOT ishga tushdi!")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
