import asyncio
from aiogram import BaseMiddleware, Bot
from aiogram.types import Message
from typing import Callable, Awaitable, Dict, Any


class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, rate_limit: float = 0.5):
        self.rate_limit = rate_limit
        self.users: Dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        user_id = event.from_user.id
        now = asyncio.get_event_loop().time()

        if user_id in self.users:
            last_time = self.users[user_id]
            if now - last_time < self.rate_limit:
                return

        self.users[user_id] = now
        return await handler(event, data)
