from datetime import datetime

from aiogram import Router, F
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select

from database.db import Movie, User, SubscriptionChannel, SessionLocal

router = Router()


@router.message(F.web_app_data)
@router.message(F.text)
async def find_movie(message: Message):
    if message.web_app_data:
        data = message.web_app_data.data.strip()
        if not data.startswith("/movie "):
            return
        code = data.replace("/movie ", "", 1).strip()
    else:
        code = (message.text or "").strip()

    if not code or code.startswith("/"):
        return

    async with SessionLocal() as session:
        result = await session.execute(
            select(User).where(User.id == message.from_user.id)
        )
        user = result.scalar_one_or_none()

        is_vip = bool(
            user and user.is_vip and user.vip_until
            and user.vip_until > datetime.utcnow()
        )

        if user and user.is_vip and not is_vip:
            user.is_vip = False
            user.vip_until = None
            await session.commit()

        if not is_vip:
            result = await session.execute(
                select(SubscriptionChannel).where(
                    SubscriptionChannel.is_active == True
                )
            )
            channels = result.scalars().all()
            not_joined = []

            for channel in channels:
                try:
                    member = await message.bot.get_chat_member(
                        channel.chat_id, message.from_user.id
                    )
                    if member.status in ("left", "kicked") or (
                        member.status == "restricted" and not member.is_member
                    ):
                        not_joined.append(channel)
                except Exception:
                    await message.answer(
                        f"⚠️ {channel.title} kanalini tekshirib bo‘lmadi. "
                        "Admin botning kanal huquqlarini tekshirsin."
                    )
                    return

            if not_joined:
                builder = InlineKeyboardBuilder()
                for channel in not_joined:
                    builder.button(
                        text=f"📢 {channel.title}",
                        url=channel.invite_link
                    )
                builder.adjust(1)
                await message.answer(
                    "🎬 Kinoni olish uchun quyidagi kanallarga a’zo bo‘ling. "
                    "A’zo bo‘lgach, kodni qayta yuboring.",
                    reply_markup=builder.as_markup()
                )
                return

        result = await session.execute(
            select(Movie).where(Movie.code == code)
        )
        movie = result.scalar_one_or_none()

        if movie is None:
            await message.answer("❌ Bunday kino kodi topilmadi.")
            return

        movie.views = (movie.views or 0) + 1
        await session.commit()

        await message.answer_video(
            video=movie.file_id,
            caption=f"🎬 {movie.title}\n👁 Ko‘rishlar soni: {movie.views}"
        )
