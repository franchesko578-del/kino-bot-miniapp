import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import (
    Message,
    ReplyKeyboardMarkup,
    KeyboardButton,
    WebAppInfo
)
from sqlalchemy import select

from config import BOT_TOKEN, WEBAPP_URL
from database.db import init_db, SessionLocal, User

from handlers.admin import router as admin_router
from handlers.channels import router as channels_router
from handlers.vip import router as vip_router
from handlers.payments import router as payments_router
from handlers.movies import router as movies_router

logging.basicConfig(level=logging.INFO)

dp = Dispatcher()

MINI_APP_URL = WEBAPP_URL or "https://kino-bot-miniapp.onrender.com"


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

    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(
                    text="🎬 KINO MINI APP",
                    web_app=WebAppInfo(url=MINI_APP_URL)
                )
            ]
        ],
        resize_keyboard=True
    )

    await message.answer(
        "🎬 KINO BOTga xush kelibsiz!\n\n"
        "Kino kodini yuboring yoki Mini App tugmasini bosing.\n"
        "⭐ VIP ma’lumot: /vipinfo",
        reply_markup=keyboard
    )




dp.include_router(admin_router)
dp.include_router(channels_router)
dp.include_router(vip_router)
dp.include_router(payments_router)
dp.include_router(movies_router)

bot = None
polling_task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot, polling_task

    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN topilmadi!")

    await init_db()

    bot = Bot(token=BOT_TOKEN)
    await bot.delete_webhook(drop_pending_updates=True)

    polling_task = asyncio.create_task(dp.start_polling(bot))

    yield

    await dp.stop_polling()
    if polling_task:
        await polling_task
    await bot.session.close()


app = FastAPI(title="KINO BOT Mini App", lifespan=lifespan)

HTML_FILE = Path(__file__).parent / "static" / "index.html"


@app.get("/")
async def home():
    return FileResponse(HTML_FILE)


@app.get("/health")
async def health():
    return {"status": "ok"}
