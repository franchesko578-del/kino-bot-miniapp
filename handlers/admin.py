from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

from config import ADMIN_IDS
from database.db import Movie, SessionLocal

router = Router()


@router.message(Command("add"))
async def add_help(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    await message.answer(
        "🎬 Kino qo‘shish:\n\n"
        "Videoni quyidagi izoh bilan yuboring:\n"
        "KOD | KINO NOMI\n\n"
        "Masalan:\n"
        "101 | Avatar"
    )


@router.message(F.video)
async def save_movie(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return

    caption = message.caption or ""

    if "|" not in caption:
        await message.answer("❌ Izoh formati: KOD | KINO NOMI")
        return

    code, title = [x.strip() for x in caption.split("|", 1)]

    if not code or not title:
        await message.answer("❌ Kod va kino nomini kiriting.")
        return

    async with SessionLocal() as session:
        result = await session.execute(
            select(Movie).where(Movie.code == code)
        )
        movie = result.scalar_one_or_none()

        if movie:
            movie.title = title
            movie.file_id = message.video.file_id
            await message.answer("✅ Kino yangilandi!")
        else:
            session.add(
                Movie(
                    code=code,
                    title=title,
                    file_id=message.video.file_id
                )
            )
            await message.answer("✅ Kino bazaga qo‘shildi!")

        await session.commit()
