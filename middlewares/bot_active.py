from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery

from config import settings
from database.crud import is_bot_active, is_bot_stop_notify


class BotActiveMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        user_id = None
        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id

        if user_id and user_id not in settings.admin_ids and not is_bot_active():
            if is_bot_stop_notify():
                msg = "⛔ البوت متوقف حاليًا. يرجى المحاولة لاحقًا."
                if isinstance(event, Message):
                    await event.answer(msg)
                elif isinstance(event, CallbackQuery):
                    await event.answer(msg, show_alert=True)
            return

        return await handler(event, data)
