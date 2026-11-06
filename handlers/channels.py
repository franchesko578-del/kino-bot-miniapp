from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

from config import ADMIN_IDS
from database.db import SessionLocal, SubscriptionChannel

router = Router()


def is_admin(message: Message):
    return message.from_user.id in ADMIN_IDS


@router.message(Command("addchannel"))
async def add_channel(message: Message):
    if not is_admin(message):
        return

    try:
        data = message.text.split(maxsplit=1)[1]
        chat_id, title, invite_link = [
            x.strip() for x in data.split("|", 2)
        ]
        chat_id = int(chat_id)

        async with SessionLocal() as session:
            result = await session.execute(
                select(SubscriptionChannel).where(
                    SubscriptionChannel.chat_id == chat_id
                )
            )
            channel = result.scalar_one_or_none()

            if channel:
                channel.title = title
                channel.invite_link = invite_link
                channel.is_active = True
            else:
                session.add(
                    SubscriptionChannel(
                        chat_id=chat_id,
                        title=title,
                        invite_link=invite_link,
                        is_active=True
                    )
                )

            await session.commit()

        await message.answer("✅ Kanal muvaffaqiyatli qo‘shildi!")

    except (IndexError, ValueError):
        await message.answer(
            "Format noto‘g‘ri.\n\n"
            "Namuna:\n"
            "/addchannel -1001234567890 | Kino kanal | https://t.me/kanal"
        )


@router.message(Command("channels"))
async def list_channels(message: Message):
    if not is_admin(message):
        return

    async with SessionLocal() as session:
        result = await session.execute(
            select(SubscriptionChannel).where(
                SubscriptionChannel.is_active == True
            )
        )
        channels = result.scalars().all()

    if not channels:
        await message.answer("Hozircha kanallar qo‘shilmagan.")
        return

    text = "📢 Majburiy obuna kanallari:\n\n"

    for channel in channels:
        text += (
            f"🆔 ID: {channel.id}\n"
            f"📛 Nomi: {channel.title}\n"
            f"🔗 Havola: {channel.invite_link}\n\n"
        )

    await message.answer(text)


@router.message(Command("delchannel"))
async def delete_channel(message: Message):
    if not is_admin(message):
        return

    try:
        channel_id = int(message.text.split(maxsplit=1)[1])

        async with SessionLocal() as session:
            result = await session.execute(
                select(SubscriptionChannel).where(
                    SubscriptionChannel.id == channel_id
                )
            )
            channel = result.scalar_one_or_none()

            if not channel:
                await message.answer("❌ Bunday kanal topilmadi.")
                return

            await session.delete(channel)
            await session.commit()

        await message.answer("✅ Kanal o‘chirildi!")

    except (IndexError, ValueError):
        await message.answer(
            "Foydalanish: /delchannel ID"
        )
