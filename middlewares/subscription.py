import logging
import time as time_module

from aiogram import BaseMiddleware
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import settings
from database.crud import (
    get_all_required_channels,
    is_channel_verified,
    set_channel_verified,
)

logger = logging.getLogger(__name__)

# Cooldown: don't re-prompt the same user more than once per 30 seconds
_last_prompt: dict[int, float] = {}


class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if not isinstance(event, Message):
            return await handler(event, data)

        user = event.from_user

        # Skip super admins
        if user.id in settings.admin_ids:
            return await handler(event, data)

        channels = await get_all_required_channels()
        if not channels:
            return await handler(event, data)

        # Already fully verified (24h cache)
        if await is_channel_verified(user.id):
            return await handler(event, data)

        # Find the first channel the user is NOT a member of
        pending_channel = None
        for ch in channels:
            try:
                member = await event.bot.get_chat_member(ch.chat_id, user.id)
                if member.status in ("member", "creator", "administrator"):
                    continue
            except Exception:
                pass
            pending_channel = ch
            break

        if pending_channel is None:
            # Member of all — mark verified
            await set_channel_verified(user.id)
            return await handler(event, data)

        # Cooldown: don't spam the same user
        now = time_module.time()
        last = _last_prompt.get(user.id, 0)
        if now - last < 30:
            return  # Silently drop until cooldown passes
        _last_prompt[user.id] = now

        # Build prompt
        link_display = pending_channel.invite_link or pending_channel.chat_id
        if pending_channel.custom_message:
            text = pending_channel.custom_message
        else:
            text = (
                f"❗️ يجب الاشتراك في القناة أولاً لاستخدام البوت:\n\n"
                f"{link_display}\n\n"
                "بعد الاشتراك، اضغط على زر التحقق."
            )

        builder = InlineKeyboardBuilder()
        builder.button(text="لقد اشتركت", callback_data="verify_subscription")
        if pending_channel.invite_link and pending_channel.invite_link.startswith("http"):
            builder.button(text="📢 اضغط للاشتراك", url=pending_channel.invite_link)
        builder.adjust(1)

        await event.answer(text, reply_markup=builder.as_markup())
        return  # Do not pass to handlers
