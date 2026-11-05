import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from pathlib import Path

from aiogram import Bot, Dispatcher
from config import BOT_TOKEN
from database.db import init_db

from handlers.admin import router as admin_router
from handlers.channels import router as channels_router
from handlers.vip import router as vip_router
from handlers.payments import router as payments_router
from handlers.movies import router as movies_router

logging.basicConfig(level=logging.INFO)

dp = Dispatcher()

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
    await bot.session.close()


app = FastAPI(title="KINO BOT Mini App", lifespan=lifespan)

HTML_FILE = Path(__file__).parent / "static" / "index.html"


@app.get("/")
async def home():
    return FileResponse(HTML_FILE)


@app.get("/health")
async def health():
    return {"status": "ok"}
