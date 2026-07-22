import logging

from aiogram import BaseMiddleware
from aiogram.types import Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import settings
from database.crud import get_required_channel, is_channel_verified, set_channel_verified

logger = logging.getLogger(__name__)


class SubscriptionMiddleware(BaseMiddleware):
    async def __call__(self, handler, event, data):
        if not isinstance(event, Message):
            return await handler(event, data)

        user = event.from_user

        # Skip super admins
        if user.id in settings.admin_ids:
            return await handler(event, data)

        chat_id, invite_link = await get_required_channel()
        if not chat_id:
            return await handler(event, data)

        # Already verified recently
        if await is_channel_verified(user.id):
            return await handler(event, data)

        # Check membership
        try:
            member = await event.bot.get_chat_member(chat_id, user.id)
            if member.status in ("member", "creator", "administrator"):
                await set_channel_verified(user.id)
                return await handler(event, data)
        except Exception:
            pass

        # Not subscribed — block and prompt
        link_display = invite_link or chat_id
        builder = InlineKeyboardBuilder()
        builder.button(text="✅ لقد اشتركت", callback_data="verify_subscription")
        if invite_link and invite_link.startswith("http"):
            builder.button(text="📢 اضغط للاشتراك", url=invite_link)
        builder.adjust(1)

        await event.answer(
            f"❗️ يجب الاشتراك في القناة أولاً لاستخدام البوت:\n\n{link_display}\n\n"
            "بعد الاشتراك، اضغط على زر التحقق.",
            reply_markup=builder.as_markup(),
        )
        return  # Do not pass to handlers
