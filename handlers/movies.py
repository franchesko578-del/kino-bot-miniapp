from aiogram import F, Router
from aiogram.types import Message

from handlers.user import send_result
from utils.services import deliver_movie, touch_user

router = Router()


@router.message(F.text & ~F.text.startswith("/"))
async def find_movie(message: Message):
    await touch_user(message.from_user)
    res = await deliver_movie(message.bot, message.chat.id, message.from_user.id, message.text)
    await send_result(message.bot, message, res)
