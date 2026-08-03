import logging
from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import CommandStart
from keyboards.reply import main_keyboard, moderator_keyboard, super_admin_keyboard, admin_panel_keyboard
from database.crud import get_or_create_user, is_admin_user, get_admin_permissions, get_stats
from config import settings

logger = logging.getLogger(__name__)
router = Router()


async def _admin_kb(user_id: int = 0):
    stats = await get_stats()
    if user_id in settings.admin_ids:
        return super_admin_keyboard(unread_count=stats["unread"])
    if user_id:
        perms = await get_admin_permissions(user_id)
        if perms:
            rank = perms.get("rank", "moderator")
            if rank == "super_admin":
                return super_admin_keyboard(unread_count=stats["unread"])
            if rank == "admin":
                return super_admin_keyboard(unread_count=stats["unread"], show_admins=False)
            return moderator_keyboard(unread_count=stats["unread"])
    return main_keyboard()


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    try:
        user = message.from_user
        await get_or_create_user(
            user_id=user.id,
            full_name=user.full_name or "بدون اسم",
            username=user.username,
        )

        is_super = user.id in settings.admin_ids

        if is_super:
            welcome_text = (
                f"أهلاً بك {user.full_name} 🙋‍♂️\n\n"
                "🔧 لوحة التحكم الخاصة بك:"
            )
            await message.answer(welcome_text, reply_markup=await _admin_kb(user.id))
            return

        is_admin_db = await is_admin_user(user.id)
        if is_admin_db:
            await message.answer(
                f"أهلاً بك {user.full_name} 🙋‍♂️\n\n"
                "أنت مشرف في البوت.\n"
                "استخدم الأزرار أدناه للتحكم.",
                reply_markup=await _admin_kb(user.id),
            )
            return

        await message.answer(
            f"مرحباً {user.first_name} في نَــافِـذَة | بوت.\n"
            "يمكنكم إرسال الاستفسارات عن طريق نَافِذَةُ التَّوَاصُلِ، أو الحصول على المواد الدراسية عن طريق نَافِذَةُ المَوَادِّ.\n"
            "\n"
            "تابع قناتنا الرسمية ليصلك كل جديد:\n"
            "https://t.me/NafidhaView",
            reply_markup=main_keyboard(),
        )
    except Exception as e:
        logger.exception("Error in start_handler: %s", e)
        await message.answer("⚠️ عذراً، حدث خطأ. يرجى المحاولة لاحقاً.", reply_markup=main_keyboard())
