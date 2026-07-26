from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery


class CallbackAnswerMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if isinstance(event, CallbackQuery):
            await event.answer()
        return await handler(event, data)
