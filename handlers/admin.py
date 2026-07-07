import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from filters import AdminFilter, SuperAdminFilter, PermissionFilter
from database.crud import (
    ban_user, unban_user, get_user, set_admin, get_all_admins,
    unban_all_users, add_autoreply, remove_autoreply, get_all_autoreplies,
    set_permission, get_admin_permissions, get_all_users, get_stats,
    get_unread_messages, get_user_messages, mark_message_read, mark_user_messages_read,
    save_reply_log, save_admin_action,
)
from keyboards.reply import cancel_keyboard, main_keyboard, moderator_keyboard, super_admin_keyboard, admin_panel_keyboard, permission_keyboard, admins_panel_keyboard, replies_panel_keyboard, bans_panel_keyboard, users_panel_keyboard, rank_keyboard, message_review_keyboard, control_panel_keyboard, admins_management_keyboard, users_management_keyboard, replies_management_keyboard, quick_reply_inline_keyboard, quick_reply_keyboard
from handlers.messages import ReplyState
from config import settings

logger = logging.getLogger(__name__)
router = Router()


async def admin_main_keyboard(user_id: int = 0) -> ReplyKeyboardMarkup:
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


class AddAdminState(StatesGroup):
    waiting_for_id = State()


class RemoveAdminState(StatesGroup):
    waiting_for_id = State()


class AddReplyState(StatesGroup):
    waiting_for_trigger = State()
    waiting_for_response = State()


class RemoveReplyState(StatesGroup):
    waiting_for_id = State()


class AddAdminRank(StatesGroup):
    waiting_for_rank = State()


class SendMsgState(StatesGroup):
    waiting_for_id = State()
    waiting_for_msg = State()


class BanUserState(StatesGroup):
    waiting_for_id = State()


class UnbanUserState(StatesGroup):
    waiting_for_id = State()


class EditPermsState(StatesGroup):
    waiting_for_id = State()


class LogsState(StatesGroup):
    waiting_for_id = State()


class UserSearchState(StatesGroup):
    waiting_for_query = State()


# ─── لوحة التحكم الرئيسية ───

@router.message(SuperAdminFilter(), F.text == "/panel")
async def admin_panel(message: Message) -> None:
    await message.answer(
        "🔧 لوحة التحكم - اختر ما تريد إدارته:",
        reply_markup=admin_panel_keyboard(),
    )


@router.callback_query(SuperAdminFilter(), F.data.startswith("panel:"))
async def panel_actions(callback: CallbackQuery) -> None:
    action = callback.data.split(":", 1)[1]

    if action == "admins":
        await show_admins_panel(callback)
    elif action == "replies":
        await show_replies_panel(callback)
    elif action == "bans":
        await show_bans_panel(callback)
    elif action == "users":
        await show_users_panel(callback)

    await callback.answer()


async def show_admins_panel(callback: CallbackQuery) -> None:
    text = "👥 إدارة المشرفين\n\n"
    text += "👑 المشرفون الأساسيون:\n"
    for aid in settings.admin_ids:
        user = await get_user(aid)
        name = user.full_name if user else str(aid)
        text += f"• {name} ({aid})\n"

    text += "\n➕ المشرفون المضافون:\n"
    db_admins = await get_all_admins()
    db_admins = [a for a in db_admins if a.user_id not in settings.admin_ids]
    if db_admins:
        for a in db_admins:
            perms = await get_admin_permissions(a.user_id)
            p = []
            if perms and perms["can_reply"]: p.append("💬")
            if perms and perms["can_ban"]: p.append("🚫")
            if perms and perms["can_manage"]: p.append("⚙️")
            perm_str = " ".join(p) if p else "❌ بدون صلاحيات"
            text += f"• {a.full_name} (@{a.username or 'لا يوجد'}) - {a.user_id}\n  الصلاحيات: {perm_str}\n"
    else:
        text += "• لا يوجد\n"

    await callback.message.answer(text, reply_markup=admins_panel_keyboard())


async def show_replies_panel(callback: CallbackQuery) -> None:
    replies = await get_all_autoreplies()
    if not replies:
        text = "🤖 لا يوجد ردود سريعة بعد."
    else:
        text = "🤖 الردود السريعة:\n\n"
        for ar in replies:
            text += f"• [{ar.id}] 🔑 {ar.trigger}\n  💬 {ar.response}\n\n"
    await callback.message.answer(text, reply_markup=replies_panel_keyboard())


async def show_bans_panel(callback: CallbackQuery) -> None:
    from database.crud import get_all_users
    users = await get_all_users()
    banned = [u for u in users if u.is_banned]
    if not banned:
        text = "🚫 لا يوجد مستخدمين محظورين."
    else:
        text = "🚫 المستخدمين المحظورين:\n\n"
        for u in banned:
            text += f"• {u.full_name} (@{u.username or 'لا يوجد'}) - {u.user_id}\n"
    await callback.message.answer(text, reply_markup=bans_panel_keyboard())


async def show_users_panel(callback: CallbackQuery) -> None:
    from database.crud import get_all_users
    users = await get_all_users()
    stats = await get_stats()
    text = (
        "📊 إحصائيات البوت\n"
        f"👤 المستخدمين: {stats['users']}\n"
        f"💬 الرسائل: {stats['messages']}\n"
        f"📩 غير مقروء: {stats['unread']}\n"
        f"🚫 المحظورين: {stats['banned']}\n"
        f"👑 المشرفين: {stats['admins']}\n"
        f"🤖 الردود: {stats['replies']}\n\n"
        "📋 قائمة المستخدمين:\n"
    )
    if not users:
        text += "لا يوجد مستخدمين بعد."
    else:
        for u in users:
            status = "🚫" if u.is_banned else "✅"
            role = "👑" if u.user_id in settings.admin_ids else "👤"
            text += f"{role} {u.full_name} - {u.user_id} {status}\n"
    await callback.message.answer(text, reply_markup=users_panel_keyboard())


# ─── الرد على المستخدمين مع التحقق من الصلاحية ───

@router.callback_query(AdminFilter(), F.data.startswith("reply:"))
async def reply_to_user(callback: CallbackQuery, state: FSMContext) -> None:
    _, user_id, user_name = callback.data.split(":", 2)
    user_id = int(user_id)
    admin_id = callback.from_user.id

    if admin_id not in settings.admin_ids:
        perms = await get_admin_permissions(admin_id)
        if not perms or not perms["can_reply"]:
            await callback.answer("❌ ليس لديك صلاحية الرد على المستخدمين.", show_alert=True)
            return

    await state.set_state(ReplyState.waiting_for_reply)
    await state.update_data(reply_user_id=user_id, reply_user_name=user_name)
    kb = await quick_reply_keyboard()
    await callback.message.answer(
        f"💬 اختر رداً سريعاً للمستخدم {user_name} أو اكتب رداً مخصصاً:",
        reply_markup=kb,
    )
    await callback.answer()


@router.callback_query(AdminFilter(), F.data.startswith("ban:"))
async def ban_user_handler(callback: CallbackQuery) -> None:
    _, user_id = callback.data.split(":", 1)
    user_id = int(user_id)
    admin_id = callback.from_user.id

    if admin_id not in settings.admin_ids:
        perms = await get_admin_permissions(admin_id)
        if not perms or not perms["can_ban"]:
            await callback.answer("❌ ليس لديك صلاحية حظر المستخدمين.", show_alert=True)
            return

    success = await ban_user(user_id)
    user = await get_user(user_id)
    user_name = user.full_name if user else str(user_id)
    if success:
        await save_admin_action(
            admin_id=admin_id,
            admin_name=callback.from_user.full_name or "مشرف",
            action_type="ban",
            details=f"حظر المستخدم {user_name}",
            target_id=user_id,
            target_name=user_name,
        )
        await callback.message.answer(f"✅ تم حظر المستخدم {user_name} بنجاح.")
    else:
        await callback.message.answer("❌ لم يتم العثور على المستخدم.")
    await callback.answer()


@router.callback_query(AdminFilter(), F.data.startswith("ignore:"))
async def ignore_user_handler(callback: CallbackQuery) -> None:
    _, user_id = callback.data.split(":", 1)
    user_id = int(user_id)
    user = await get_user(user_id)
    user_name = user.full_name if user else str(user_id)
    await mark_user_messages_read(user_id)
    await save_admin_action(
        admin_id=callback.from_user.id,
        admin_name=callback.from_user.full_name or "مشرف",
        action_type="ignore",
        details=f"تجاهل رسالة المستخدم {user_name}",
        target_id=user_id,
        target_name=user_name,
    )
    await callback.message.answer(f"⏭ تم تجاهل رسالة المستخدم {user_name}.")
    await callback.answer()


@router.callback_query(AdminFilter(), F.data.startswith("forward:"))
async def forward_to_channel_handler(callback: CallbackQuery) -> None:
    from database.crud import get_user_messages
    _, user_id, user_name = callback.data.split(":", 2)
    user_id = int(user_id)

    user_messages = await get_user_messages(user_id)
    if not user_messages:
        await callback.message.answer("❌ لا توجد رسائل لهذا المستخدم.")
        await callback.answer()
        return

    last_msg = user_messages[0]
    channel = settings.CHANNEL_USERNAME
    header = f"📨 رسالة مستخدم\n👤 {user_name}\n🆔 {user_id}"

    try:
        if last_msg.message_type == "text":
            await callback.bot.send_message(
                chat_id=channel,
                text=f"{header}\n\n{last_msg.content}",
            )
        elif last_msg.message_type == "photo" and last_msg.file_id:
            await callback.bot.send_photo(
                chat_id=channel, photo=last_msg.file_id,
                caption=f"{header}\n\n{last_msg.caption or ''}",
            )
        elif last_msg.message_type == "video" and last_msg.file_id:
            await callback.bot.send_video(
                chat_id=channel, video=last_msg.file_id,
                caption=f"{header}\n\n{last_msg.caption or ''}",
            )
        elif last_msg.message_type == "document" and last_msg.file_id:
            await callback.bot.send_document(
                chat_id=channel, document=last_msg.file_id,
                caption=f"{header}\n\n{last_msg.caption or ''}",
            )
        elif last_msg.message_type == "audio" and last_msg.file_id:
            await callback.bot.send_audio(
                chat_id=channel, audio=last_msg.file_id,
                caption=f"{header}\n\n{last_msg.caption or ''}",
            )
        elif last_msg.message_type == "voice" and last_msg.file_id:
            await callback.bot.send_voice(
                chat_id=channel, voice=last_msg.file_id,
            )
            await callback.bot.send_message(chat_id=channel, text=header)
        elif last_msg.message_type == "sticker" and last_msg.file_id:
            await callback.bot.send_sticker(chat_id=channel, sticker=last_msg.file_id)
            await callback.bot.send_message(chat_id=channel, text=header)
        elif last_msg.message_type == "animation" and last_msg.file_id:
            await callback.bot.send_animation(
                chat_id=channel, animation=last_msg.file_id,
                caption=f"{header}\n\n{last_msg.caption or ''}",
            )
        elif last_msg.message_type == "video_note" and last_msg.file_id:
            await callback.bot.send_video_note(chat_id=channel, video_note=last_msg.file_id)
            await callback.bot.send_message(chat_id=channel, text=header)
        else:
            await callback.bot.send_message(chat_id=channel, text=header)

        await save_admin_action(
            admin_id=callback.from_user.id,
            admin_name=callback.from_user.full_name or "مشرف",
            action_type="forward",
            details=f"تحويل رسالة المستخدم {user_name} إلى القناة",
            target_id=user_id,
            target_name=user_name,
        )
        await callback.message.answer(f"✅ تم تحويل رسالة {user_name} إلى القناة بنجاح.")
    except Exception as e:
        logger.error(f"Failed to forward to channel: {e}")
        await callback.message.answer(
            "❌ فشل التحويل إلى القناة.\n"
            "تأكد أن البوت مشرف في القناة لديه صلاحية الإرسال.",
        )
    await callback.answer()


@router.callback_query(AdminFilter(), F.data.startswith("quick_reply:"))
async def quick_reply_handler(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    reply_id = int(parts[1])
    user_id = int(parts[2])
    user_name = ":".join(parts[3:])

    replies = await get_all_autoreplies()
    ar = next((r for r in replies if r.id == reply_id), None)
    if not ar:
        await callback.answer("❌ الرد السريع غير موجود.", show_alert=True)
        return

    try:
        await callback.bot.send_message(chat_id=user_id, text=ar.response)
        await save_reply_log(
            user_id=user_id,
            user_name=user_name,
            admin_id=callback.from_user.id,
            admin_name=callback.from_user.full_name or "مشرف",
            user_message_id=0,
            user_message=None,
            user_message_type="text",
            admin_reply=ar.response,
            action_type="quick_reply",
            details=f"رد سريع: {ar.trigger}",
        )
        await callback.message.answer(f"✅ تم إرسال الرد السريع إلى {user_name}.")

        data = await state.get_data()
        after_action = data.get("after_reply_action")
        await state.clear()
        if after_action == "next_unread":
            await show_next_unread(callback.message, state)
    except Exception:
        await callback.message.answer("❌ فشل الإرسال. قد يكون المستخدم أوقف البوت.")
    await callback.answer()


@router.callback_query(AdminFilter(), F.data.startswith("custom_reply:"))
async def custom_reply_handler(callback: CallbackQuery, state: FSMContext) -> None:
    _, user_id, user_name = callback.data.split(":", 2)
    user_id = int(user_id)
    data = await state.get_data()
    after_action = data.get("after_reply_action")
    await state.set_state(ReplyState.waiting_for_reply)
    await state.update_data(
        reply_user_id=user_id,
        reply_user_name=user_name,
        after_reply_action=after_action,
    )
    await callback.message.answer(
        f"✏️ أرسل ردك الآن للمستخدم {user_name}:",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "cancel_reply")
async def cancel_action(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    kb = await admin_main_keyboard(callback.from_user.id)
    await callback.message.answer("✅ تم الإلغاء.", reply_markup=kb)
    await callback.answer()


@router.message(ReplyState.waiting_for_reply, AdminFilter())
async def send_reply_to_user(message: Message, state: FSMContext) -> None:
    from database.crud import get_user_messages
    data = await state.get_data()
    reply_user_id = data["reply_user_id"]
    reply_user_name = data["reply_user_name"]

    # Handle special buttons
    if message.text == "✏️ رد مخصص":
        kb = await quick_reply_keyboard()
        await message.answer("✏️ اكتب ردك المخصص الآن:", reply_markup=cancel_keyboard())
        return

    if message.text == "❌ إلغاء":
        kb = await admin_main_keyboard(message.from_user.id)
        await message.answer("✅ تم الإلغاء.", reply_markup=kb)
        await state.clear()
        return

    # Check if text matches a quick reply trigger
    reply_text = message.text
    if message.text:
        all_replies = await get_all_autoreplies()
        for ar in all_replies:
            if ar.trigger == message.text.strip():
                reply_text = ar.response
                break

    try:
        if message.text:
            await message.bot.send_message(chat_id=reply_user_id, text=reply_text)
        elif message.photo:
            await message.bot.send_photo(
                chat_id=reply_user_id, photo=message.photo[-1].file_id,
                caption=message.caption or "",
            )
        elif message.video:
            await message.bot.send_video(
                chat_id=reply_user_id, video=message.video.file_id,
                caption=message.caption or "",
            )
        elif message.document:
            await message.bot.send_document(
                chat_id=reply_user_id, document=message.document.file_id,
                caption=message.caption or "",
            )
        elif message.voice:
            await message.bot.send_voice(chat_id=reply_user_id, voice=message.voice.file_id)
        else:
            await message.bot.send_message(chat_id=reply_user_id, text=reply_text or " ")

        await message.answer(f"✅ تم إرسال ردك إلى {reply_user_name} بنجاح.", reply_markup=await admin_main_keyboard(message.from_user.id))

        # Save reply log
        user_msgs = await get_user_messages(reply_user_id)
        last_msg = user_msgs[0] if user_msgs else None
        await save_reply_log(
            user_id=reply_user_id,
            user_name=reply_user_name,
            admin_id=message.from_user.id,
            admin_name=message.from_user.full_name or "مشرف",
            user_message_id=last_msg.id if last_msg else 0,
            user_message=last_msg.content or last_msg.caption if last_msg else None,
            user_message_type=last_msg.message_type if last_msg else "text",
            admin_reply=reply_text or message.caption or "رسالة وسائط",
            action_type="quick_reply" if message.text and reply_text != message.text else "reply",
            details=f"رد سريع: {message.text.strip()}" if message.text and reply_text != message.text else None,
        )
    except Exception as e:
        logger.error(f"Failed to send reply to user {reply_user_id}: {e}")
        await message.answer("❌ فشل إرسال الرد. قد يكون المستخدم أوقف البوت.", reply_markup=await admin_main_keyboard(message.from_user.id))

    after_action = data.get("after_reply_action")
    await state.clear()
    if after_action == "next_unread":
        await show_next_unread(message, state)
    elif after_action:
        await message.answer("🔧 اختر من الأزرار:", reply_markup=admin_panel_keyboard())


# ─── إدارة المشرفين مع صلاحيات ───

@router.message(PermissionFilter("can_manage"), F.text == "/addadmin")
async def add_admin_start(message: Message, state: FSMContext) -> None:
    await state.set_state(AddAdminState.waiting_for_id)
    await message.answer(
        "👤 أرسل معرف المستخدم (User ID) الذي تريد إضافته كمشرف:",
        reply_markup=cancel_keyboard(),
    )


@router.message(AddAdminState.waiting_for_id, SuperAdminFilter())
async def add_admin_confirm(message: Message, state: FSMContext) -> None:
    try:
        target_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ معرف غير صالح. أرسل رقم صحيح.")
        return

    if target_id in settings.admin_ids:
        await message.answer("❌ هذا المستخدم مشرف أساسي في الإعدادات ولا يمكن تعديله من هنا.")
        await state.clear()
        return

    user = await get_user(target_id)
    if not user:
        await message.answer("❌ المستخدم غير موجود في قاعدة البيانات. يجب أن يستخدم البوت أولاً.")
        await state.clear()
        return

    if user.is_admin:
        await message.answer("ℹ️ هذا المستخدم مشرف بالفعل.")
        await state.clear()
        return

    await state.update_data(target_id=target_id, target_name=user.full_name)
    await state.set_state(AddAdminRank.waiting_for_rank)
    await message.answer(
        f"اختر رتبة المشرف لـ {user.full_name}:",
        reply_markup=rank_keyboard(),
    )


@router.callback_query(SuperAdminFilter(), F.data.startswith("rank:"))
async def select_rank(callback: CallbackQuery, state: FSMContext) -> None:
    rank = callback.data.split(":", 1)[1]
    data = await state.get_data()
    target_id = data["target_id"]
    target_name = data.get("target_name", str(target_id))

    rank_names = {"super_admin": "🚀 سوبر", "admin": "👑 مشرف", "moderator": "🔰 مراقب"}
    await set_admin(target_id, True, rank=rank)

    user = await get_user(target_id)
    is_edit = user and user.is_admin

    action_type = "edit_admin" if is_edit else "add_admin"
    action_details = f"تعديل صلاحيات {target_name} إلى {rank_names.get(rank, rank)}" if is_edit else f"إضافة {target_name} كـ {rank_names.get(rank, rank)}"
    await save_admin_action(
        admin_id=callback.from_user.id,
        admin_name=callback.from_user.full_name or "مشرف",
        action_type=action_type,
        details=action_details,
        target_id=target_id,
        target_name=target_name,
    )

    msg = f"✅ تم تحديث صلاحيات {target_name} إلى {rank_names.get(rank, rank)}!" if is_edit else f"✅ تمت إضافة {target_name} كـ {rank_names.get(rank, rank)} بنجاح!"
    await callback.message.answer(msg, reply_markup=await admin_main_keyboard(callback.from_user.id))
    await state.clear()
    await callback.answer()



@router.message(PermissionFilter("can_manage"), F.text == "/removeadmin")
async def remove_admin_start(message: Message, state: FSMContext) -> None:
    await state.set_state(RemoveAdminState.waiting_for_id)
    await message.answer(
        "👤 أرسل معرف المستخدم (User ID) الذي تريد إزالته من المشرفين:",
        reply_markup=cancel_keyboard(),
    )


@router.message(RemoveAdminState.waiting_for_id, SuperAdminFilter())
async def remove_admin_confirm(message: Message, state: FSMContext) -> None:
    try:
        target_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ معرف غير صالح. أرسل رقم صحيح.")
        return

    if target_id in settings.admin_ids:
        await message.answer("❌ هذا المستخدم مشرف أساسي ولا يمكن إزالته.")
        await state.clear()
        return

    success = await set_admin(target_id, False)
    if success:
        user = await get_user(target_id)
        user_name = user.full_name if user else str(target_id)
        await save_admin_action(
            admin_id=message.from_user.id,
            admin_name=message.from_user.full_name or "مشرف",
            action_type="remove_admin",
            details=f"إزالة {user_name} من المشرفين",
            target_id=target_id,
            target_name=user_name,
        )
        await message.answer(f"✅ تمت إزالة المستخدم {user_name} من المشرفين.")
    else:
        await message.answer("❌ المستخدم غير موجود.")
    await state.clear()


@router.callback_query(SuperAdminFilter(), F.data.startswith("perm:"))
async def toggle_permission(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    target_id = int(parts[1])
    action = parts[2]

    if action == "done":
        perms = await get_admin_permissions(target_id)
        p = []
        if perms["can_reply"]: p.append("💬 الرد")
        if perms["can_ban"]: p.append("🚫 الحظر")
        if perms["can_manage"]: p.append("⚙️ الإدارة")
        await callback.message.answer(
            f"✅ تم حفظ صلاحيات المستخدم {target_id}:\n" + "\n".join(p),
        )
        await callback.answer()
        return

    user = await get_user(target_id)
    current = getattr(user, action, False) if user else False
    new_val = not current
    await set_permission(target_id, action, new_val)
    status = "✅" if new_val else "❌"
    await callback.answer(f"تم تغيير الصلاحية: {status}", show_alert=True)

    # Refresh the keyboard
    await callback.message.edit_reply_markup(
        reply_markup=permission_keyboard(target_id),
    )


# ─── قائمة المشرفين (لجميع المشرفين) ───

@router.message(AdminFilter(), F.text == "/admins")
async def list_admins(message: Message) -> None:
    text = "👑 المشرفون الأساسيون:\n"
    for aid in settings.admin_ids:
        user = await get_user(aid)
        name = user.full_name if user else str(aid)
        text += f"• {name} ({aid})\n"
    text += "\n➕ المشرفون المضافون:\n"
    db_admins = await get_all_admins()
    db_admins = [a for a in db_admins if a.user_id not in settings.admin_ids]
    if db_admins:
        rank_names = {"super_admin": "🚀 سوبر", "admin": "👑 مشرف", "moderator": "🔰 مراقب"}
        for a in db_admins:
            perms = await get_admin_permissions(a.user_id)
            rank_str = rank_names.get(a.rank or "moderator", a.rank or "مراقب")
            p = []
            if perms:
                if perms["can_reply"]: p.append("💬 رد")
                if perms["can_ban"]: p.append("🚫 حظر")
                if perms["can_manage"]: p.append("⚙️ إدارة")
            perm_str = " | ".join(p) if p else "❌ بدون صلاحيات"
            text += f"• {a.full_name} - {a.user_id} ({rank_str})\n  {perm_str}\n"
    else:
        text += "• لا يوجد\n"
    await message.answer(text)


@router.message(AdminFilter(), F.text == "/users")
async def list_users(message: Message) -> None:
    await show_users_list(message)


async def show_users_list(target, search: str = "") -> None:
    from database.crud import get_all_users
    all_users = await get_all_users()
    if search:
        users = [u for u in all_users if search.lower() in u.full_name.lower() or str(u.user_id) == search or (u.username and search.lower() in u.username.lower())]
    else:
        users = all_users
    out = "📋 قائمة المستخدمين:\n"
    if not users:
        out += "لا يوجد مستخدمين."
    else:
        for u in users:
            status = "🚫" if u.is_banned else "✅"
            role = "👑" if u.user_id in settings.admin_ids else "👤"
            username_part = f" (@{u.username})" if u.username else ""
            out += f"{role} {u.full_name}{username_part} - {u.user_id} {status}\n"
    await target.answer(out)


# ─── الردود السريعة ───

@router.message(PermissionFilter("can_manage"), F.text == "/addreply")
async def add_reply_trigger(message: Message, state: FSMContext) -> None:
    await state.set_state(AddReplyState.waiting_for_trigger)
    await message.answer(
        "✏️ أرسل الكلمة المفتاحية (الtrigger):\nمثال: السلام عليكم",
        reply_markup=cancel_keyboard(),
    )


@router.message(AddReplyState.waiting_for_trigger, PermissionFilter("can_manage"))
async def add_reply_response(message: Message, state: FSMContext) -> None:
    await state.update_data(trigger=message.text.strip())
    await state.set_state(AddReplyState.waiting_for_response)
    await message.answer(
        "✏️ أرسل الرد الذي تريده:\nمثال: وعليكم السلام ورحمة الله وبركاته",
        reply_markup=cancel_keyboard(),
    )


@router.message(AddReplyState.waiting_for_response, PermissionFilter("can_manage"))
async def add_reply_save(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    ar = await add_autoreply(data["trigger"], message.text.strip())
    await message.answer(
        f"✅ تمت إضافة الرد السريع!\n🔑 {ar.trigger}\n💬 {ar.response}",
        reply_markup=await admin_main_keyboard(message.from_user.id),
    )
    await state.clear()


@router.message(PermissionFilter("can_manage"), F.text == "/removereply")
async def remove_reply_start(message: Message, state: FSMContext) -> None:
    await state.set_state(RemoveReplyState.waiting_for_id)
    await message.answer(
        "✏️ أرسل رقم (ID) الرد السريع الذي تريد حذفه:\nلعرض الأرقام: /replies",
        reply_markup=cancel_keyboard(),
    )


@router.message(RemoveReplyState.waiting_for_id, PermissionFilter("can_manage"))
async def remove_reply_confirm(message: Message, state: FSMContext) -> None:
    try:
        reply_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ رقم غير صالح.")
        return
    success = await remove_autoreply(reply_id)
    await message.answer(f"✅ تم الحذف." if success else "❌ غير موجود.")
    await state.clear()


@router.message(AdminFilter(), F.text == "/replies")
async def list_replies(message: Message) -> None:
    replies = await get_all_autoreplies()
    if not replies:
        await message.answer("❌ لا يوجد ردود سريعة.\n/addreply للإضافة")
        return
    text = "📋 الردود السريعة:\n\n"
    for ar in replies:
        text += f"• [{ar.id}] 🔑 {ar.trigger}\n  💬 {ar.response}\n\n"
    await message.answer(text)


@router.message(PermissionFilter("can_ban"), F.text == "/unbanall")
async def unban_all_handler(message: Message) -> None:
    count = await unban_all_users()
    await message.answer(f"✅ تم إلغاء حظر {count} مستخدمين.")


# ─── أزرار الكيبورد الرئيسي للمسؤول ───

@router.message(PermissionFilter("can_manage"), F.text == "🔧 لوحة التحكم")
async def panel_button(message: Message) -> None:
    from database.crud import is_bot_active
    active = is_bot_active()
    is_super = message.from_user.id in settings.admin_ids
    status = "✅ البوت شغال" if active else "⛔ البوت متوقف"
    await message.answer(f"🔧 لوحة التحكم\n{status}", reply_markup=control_panel_keyboard(active, is_super))


@router.message(AdminFilter(), F.text.startswith("📩 الطلبات المرسلة"))
async def messages_queue_button(message: Message, state: FSMContext) -> None:
    await show_next_unread(message, state)


@router.message(SuperAdminFilter(), F.text == "👥 المشرفين")
async def admins_button(message: Message) -> None:
    await list_admins(message)
    await message.answer("👥 إدارة المشرفين:", reply_markup=admins_management_keyboard())


@router.message(PermissionFilter("can_ban"), F.text == "📋 المستخدمين")
async def users_button(message: Message) -> None:
    await list_users(message)
    await message.answer("📋 إدارة المستخدمين:", reply_markup=users_management_keyboard())


@router.message(AdminFilter(), F.text == "🤖 الردود السريعة")
async def replies_button(message: Message) -> None:
    await list_replies(message)
    if message.from_user.id in settings.admin_ids:
        await message.answer("🤖 الردود السريعة:", reply_markup=replies_management_keyboard())
    else:
        perms = await get_admin_permissions(message.from_user.id)
        if perms and perms.get("can_manage", False):
            await message.answer("🤖 الردود السريعة:", reply_markup=replies_management_keyboard())
        else:
            await message.answer("🔙 ارجع للخلف متى شئت.", reply_markup=await admin_main_keyboard(message.from_user.id))


@router.message(AdminFilter(), F.text == "🔄 تحديث")
async def refresh_button(message: Message) -> None:
    await message.answer("✅ تم التحديث", reply_markup=await admin_main_keyboard(message.from_user.id))


# ─── أزرار القوائم الفرعية (ReplyKeyboard) ───

@router.message(AdminFilter(), F.text == "🔙 رجوع")
async def back_to_main(message: Message) -> None:
    await message.answer("🔧 القائمة الرئيسية:", reply_markup=await admin_main_keyboard(message.from_user.id))


@router.message(PermissionFilter("can_manage"), F.text == "📩 إرسال رسالة")
async def sendmsg_from_kb(message: Message, state: FSMContext) -> None:
    await state.set_state(SendMsgState.waiting_for_id)
    await message.answer(
        "📩 أرسل معرف المستخدم (User ID) أو اسم المستخدم (@username):",
        reply_markup=cancel_keyboard(),
    )


@router.message(SuperAdminFilter(), F.text == "⏹ إيقاف البوت")
async def stop_bot_kb(message: Message) -> None:
    from database.crud import set_bot_active
    set_bot_active(False)
    await message.answer("⛔ تم إيقاف البوت.\nلن يتم استقبال رسائل جديدة.", reply_markup=await admin_main_keyboard(message.from_user.id))


@router.message(SuperAdminFilter(), F.text == "▶️ تشغيل البوت")
async def start_bot_kb(message: Message) -> None:
    from database.crud import set_bot_active
    set_bot_active(True)
    await message.answer("✅ تم تشغيل البوت.\nيمكن للمستخدمين إرسال الرسائل الآن.", reply_markup=await admin_main_keyboard(message.from_user.id))


@router.message(PermissionFilter("can_view_logs"), F.text == "📋 السجلات")
async def logs_prompt(message: Message, state: FSMContext) -> None:
    await state.set_state(LogsState.waiting_for_id)
    await message.answer(
        "📋 أرسل معرف المشرف (ID) أو اسم المستخدم (@username) لعرض سجل نشاطه:",
        reply_markup=cancel_keyboard(),
    )


@router.message(SuperAdminFilter(), F.text == "🔄 تحديث البوت")
async def restart_bot_kb(message: Message) -> None:
    await message.answer("♻️ جاري إعادة تشغيل البوت...")
    import subprocess, sys
    subprocess.Popen(["systemctl", "--user", "restart", "botkey"])
    sys.exit(0)


@router.message(SuperAdminFilter(), F.text == "➕ إضافة مشرف")
async def add_admin_kb(message: Message, state: FSMContext) -> None:
    await state.set_state(AddAdminState.waiting_for_id)
    await message.answer(
        "👤 أرسل معرف المستخدم (User ID) الذي تريد إضافته كمشرف:",
        reply_markup=cancel_keyboard(),
    )


@router.message(SuperAdminFilter(), F.text == "➖ إزالة مشرف")
async def remove_admin_kb(message: Message, state: FSMContext) -> None:
    await state.set_state(RemoveAdminState.waiting_for_id)
    await message.answer(
        "👤 أرسل معرف المستخدم (User ID) الذي تريد إزالته من المشرفين:",
        reply_markup=cancel_keyboard(),
    )


@router.message(SuperAdminFilter(), F.text == "🔑 تعديل الصلاحيات")
async def edit_permissions_kb(message: Message, state: FSMContext) -> None:
    await state.set_state(EditPermsState.waiting_for_id)
    await message.answer(
        "🔑 أرسل معرف المستخدم (User ID) الذي تريد تعديل صلاحياته:",
        reply_markup=cancel_keyboard(),
    )


@router.message(EditPermsState.waiting_for_id, SuperAdminFilter())
async def edit_permissions_show(message: Message, state: FSMContext) -> None:
    try:
        target_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ معرف غير صالح. أرسل رقم صحيح.")
        return
    user = await get_user(target_id)
    if not user or not user.is_admin:
        await message.answer("❌ هذا المستخدم ليس مشرفاً.")
        await state.clear()
        return
    if target_id in settings.admin_ids:
        await message.answer("❌ لا يمكن تعديل صلاحيات المشرف الأساسي.")
        await state.clear()
        return
    await state.set_state(AddAdminRank.waiting_for_rank)
    await state.update_data(target_id=target_id, target_name=user.full_name)
    await message.answer(
        f"🔑 اختر الرتبة الجديدة لـ {user.full_name}:",
        reply_markup=rank_keyboard(),
    )


@router.message(AdminFilter(), F.text == "📊 الإحصائيات")
async def stats_kb(message: Message) -> None:
    await show_stats(message)


@router.message(PermissionFilter("can_ban"), F.text == "🔒 حظر مستخدم")
async def ban_user_kb(message: Message, state: FSMContext) -> None:
    await state.set_state(BanUserState.waiting_for_id)
    await message.answer(
        "🔒 أرسل معرف المستخدم (User ID) الذي تريد حظره:",
        reply_markup=cancel_keyboard(),
    )


@router.message(PermissionFilter("can_ban"), F.text == "🔓 إلغاء حظر")
async def unban_user_kb(message: Message, state: FSMContext) -> None:
    await state.set_state(UnbanUserState.waiting_for_id)
    await message.answer(
        "🔓 أرسل معرف المستخدم (User ID) الذي تريد إلغاء حظره:",
        reply_markup=cancel_keyboard(),
    )


@router.message(PermissionFilter("can_ban"), F.text == "🔄 إلغاء حظر الجميع")
async def unban_all_kb(message: Message) -> None:
    count = await unban_all_users()
    await message.answer(f"✅ تم إلغاء حظر {count} مستخدمين.")


@router.message(PermissionFilter("can_ban"), F.text == "🔍 بحث عن مستخدم")
async def search_user_kb(message: Message, state: FSMContext) -> None:
    await state.set_state(UserSearchState.waiting_for_query)
    await message.answer(
        "🔍 أرسل معرف المستخدم (ID) أو اسم المستخدم (@username) أو جزء من الاسم للبحث:",
        reply_markup=cancel_keyboard(),
    )


@router.message(UserSearchState.waiting_for_query, PermissionFilter("can_ban"))
async def search_user_show(message: Message, state: FSMContext) -> None:
    query = message.text.strip()
    if query.startswith("@"):
        query = query[1:]
    await show_users_list(message, search=query)
    await state.clear()


@router.message(PermissionFilter("can_manage"), F.text == "➕ إضافة رد")
async def add_reply_kb(message: Message, state: FSMContext) -> None:
    await state.set_state(AddReplyState.waiting_for_trigger)
    await message.answer(
        "✏️ أرسل الكلمة المفتاحية (الtrigger):\nمثال: السلام عليكم",
        reply_markup=cancel_keyboard(),
    )


@router.message(PermissionFilter("can_manage"), F.text == "➖ حذف رد")
async def remove_reply_kb(message: Message, state: FSMContext) -> None:
    await state.set_state(RemoveReplyState.waiting_for_id)
    await message.answer(
        "✏️ أرسل رقم (ID) الرد السريع الذي تريد حذفه:\nلعرض الأرقام: /replies",
        reply_markup=cancel_keyboard(),
    )


@router.message(AdminFilter(), F.text == "📋 عرض الردود")
async def show_replies_kb(message: Message) -> None:
    await list_replies(message)


# ─── الإحصائيات ───

@router.message(AdminFilter(), F.text == "/stats")
async def stats_command(message: Message) -> None:
    await show_stats(message)


async def show_stats(message: Message) -> None:
    stats = await get_stats()
    text = (
        "📊 إحصائيات البوت\n\n"
        f"👤 عدد المستخدمين: {stats['users']}\n"
        f"👑 عدد المشرفين: {stats['admins']}\n"
        f"🚫 المحظورين: {stats['banned']}\n"
        f"💬 إجمالي الرسائل: {stats['messages']}\n"
        f"🤖 الردود السريعة: {stats['replies']}"
    )
    await message.answer(text)


# ─── تحديث لوحة التحكم ───

@router.callback_query(AdminFilter(), F.data == "panel:refresh")
async def refresh_panel(callback: CallbackQuery) -> None:
    await callback.message.edit_reply_markup(reply_markup=admin_panel_keyboard())
    await callback.answer("✅ تم التحديث")


@router.callback_query(SuperAdminFilter(), F.data == "panel:restart")
async def restart_bot_cb(callback: CallbackQuery) -> None:
    await callback.message.answer("♻️ جاري إعادة تشغيل البوت...")
    await callback.answer()
    import subprocess, sys
    subprocess.Popen(["systemctl", "--user", "restart", "botkey"])
    sys.exit(0)


@router.callback_query(AdminFilter(), F.data == "panel:stats")
async def panel_stats(callback: CallbackQuery) -> None:
    await show_stats(callback.message)
    await callback.answer()


# ─── أزرار اللوحات الفرعية ───

@router.callback_query(AdminFilter(), F.data == "panel:back")
async def panel_back(callback: CallbackQuery) -> None:
    await callback.message.answer("🔧 لوحة التحكم:", reply_markup=admin_panel_keyboard())
    await callback.answer()


@router.callback_query(SuperAdminFilter(), F.data == "addadmin:start")
async def addadmin_from_panel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddAdminState.waiting_for_id)
    await callback.message.answer(
        "👤 أرسل معرف المستخدم (User ID) الذي تريد إضافته كمشرف:",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.callback_query(SuperAdminFilter(), F.data == "removeadmin:start")
async def removeadmin_from_panel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(RemoveAdminState.waiting_for_id)
    await callback.message.answer(
        "👤 أرسل معرف المستخدم (User ID) الذي تريد إزالته من المشرفين:",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.callback_query(PermissionFilter("can_manage"), F.data == "addreply:start")
async def addreply_from_panel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AddReplyState.waiting_for_trigger)
    await callback.message.answer(
        "✏️ أرسل الكلمة المفتاحية:\nمثال: السلام عليكم",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.callback_query(PermissionFilter("can_manage"), F.data == "removereply:start")
async def removereply_from_panel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(RemoveReplyState.waiting_for_id)
    await callback.message.answer(
        "✏️ أرسل رقم (ID) الرد السريع الذي تريد حذفه:",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.callback_query(PermissionFilter("can_ban"), F.data == "unbanall:start")
async def unbanall_from_panel(callback: CallbackQuery) -> None:
    count = await unban_all_users()
    await callback.message.answer(f"✅ تم إلغاء حظر {count} مستخدمين.")
    await callback.answer()


@router.callback_query(PermissionFilter("can_ban"), F.data == "ban_user:start")
async def ban_user_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BanUserState.waiting_for_id)
    await callback.message.answer(
        "🔒 أرسل معرف المستخدم (User ID) الذي تريد حظره:",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(BanUserState.waiting_for_id, PermissionFilter("can_ban"))
async def ban_user_confirm(message: Message, state: FSMContext) -> None:
    try:
        target_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ معرف غير صالح.")
        return
    success = await ban_user(target_id)
    await message.answer(f"✅ تم حظر المستخدم {target_id}." if success else "❌ المستخدم غير موجود.")
    await state.clear()


@router.callback_query(PermissionFilter("can_ban"), F.data == "unban_user:start")
async def unban_user_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(UnbanUserState.waiting_for_id)
    await callback.message.answer(
        "🔓 أرسل معرف المستخدم (User ID) الذي تريد إلغاء حظره:",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(UnbanUserState.waiting_for_id, PermissionFilter("can_ban"))
async def unban_user_confirm(message: Message, state: FSMContext) -> None:
    try:
        target_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ معرف غير صالح.")
        return
    success = await unban_user(target_id)
    if success:
        user = await get_user(target_id)
        user_name = user.full_name if user else str(target_id)
        await save_admin_action(
            admin_id=message.from_user.id,
            admin_name=message.from_user.full_name or "مشرف",
            action_type="unban",
            details=f"إلغاء حظر المستخدم {user_name}",
            target_id=target_id,
            target_name=user_name,
        )
        await message.answer(f"✅ تم إلغاء حظر المستخدم {user_name}.")
    else:
        await message.answer("❌ المستخدم غير موجود.")
    await state.clear()


# ─── إرسال رسالة مباشرة للمستخدم ───

@router.callback_query(PermissionFilter("can_manage"), F.data == "panel:sendmsg")
async def sendmsg_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(SendMsgState.waiting_for_id)
    await callback.message.answer(
        "📩 أرسل معرف المستخدم (User ID) الذي تريد مراسلته:",
        reply_markup=cancel_keyboard(),
    )
    await callback.answer()


@router.message(SendMsgState.waiting_for_id, PermissionFilter("can_manage"))
async def sendmsg_get_id(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    target_id = None
    target_name = None

    if text.startswith("@"):
        username = text[1:]
        all_users = await get_all_users()
        for u in all_users:
            if u.username and u.username.lower() == username.lower():
                target_id = u.user_id
                target_name = u.full_name
                break
    else:
        try:
            target_id = int(text)
        except ValueError:
            await message.answer("❌ معرف غير صالح. أرسل ID رقمي أو @username.")
            return
        user = await get_user(target_id)
        if user:
            target_name = user.full_name

    if not target_id:
        await message.answer("❌ المستخدم غير موجود في قاعدة البيانات.")
        await state.clear()
        return

    await state.update_data(target_id=target_id, target_name=target_name or str(target_id))
    await state.set_state(SendMsgState.waiting_for_msg)
    await message.answer(
        f"✏️ أرسل الرسالة التي تريد إرسالها إلى {target_name}:\n"
        "(نص، صورة، فيديو، ملف...)",
        reply_markup=cancel_keyboard(),
    )


@router.message(SendMsgState.waiting_for_msg, PermissionFilter("can_manage"))
async def sendmsg_send(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    target_id = data["target_id"]
    target_name = data["target_name"]

    try:
        if message.text:
            await message.bot.send_message(chat_id=target_id, text=message.text)
        elif message.photo:
            await message.bot.send_photo(
                chat_id=target_id, photo=message.photo[-1].file_id,
                caption=message.caption or "",
            )
        elif message.video:
            await message.bot.send_video(
                chat_id=target_id, video=message.video.file_id,
                caption=message.caption or "",
            )
        elif message.document:
            await message.bot.send_document(
                chat_id=target_id, document=message.document.file_id,
                caption=message.caption or "",
            )
        elif message.voice:
            await message.bot.send_voice(chat_id=target_id, voice=message.voice.file_id)
        else:
            await message.bot.send_message(chat_id=target_id, text="📩 رسالة من الإدارة.")

        await message.answer(f"✅ تم إرسال الرسالة إلى {target_name} بنجاح.", reply_markup=await admin_main_keyboard(message.from_user.id))
    except Exception as e:
        logger.error(f"Failed to send message to {target_id}: {e}")
        await message.answer("❌ فشل الإرسال. قد يكون المستخدم أوقف البوت.", reply_markup=await admin_main_keyboard(message.from_user.id))

    await state.clear()


# ─── عرض سجلات الردود ───

@router.message(LogsState.waiting_for_id, PermissionFilter("can_view_logs"))
async def logs_show(message: Message, state: FSMContext) -> None:
    from database.crud import get_reply_logs, get_all_users
    text = message.text.strip()
    admin_id = None

    if text.startswith("@"):
        username = text[1:]
        all_users = await get_all_users()
        for u in all_users:
            if u.username and u.username.lower() == username.lower():
                admin_id = u.user_id
                break
    else:
        try:
            admin_id = int(text)
        except ValueError:
            await message.answer("❌ معرف غير صالح. أرسل ID رقمي أو @username.")
            return

    if not admin_id:
        await message.answer("❌ المستخدم غير موجود.")
        await state.clear()
        return

    logs = await get_reply_logs(admin_id=admin_id, limit=30)
    if not logs:
        await message.answer("📋 لا توجد سجلات نشاط لهذا المشرف.")
        await state.clear()
        return

    admin_info = await get_user(admin_id)
    admin_name = admin_info.full_name if admin_info else str(admin_id)
    action_labels = {
        "reply": "💬 رد",
        "quick_reply": "⚡ رد سريع",
        "ban": "🚫 حظر",
        "ignore": "⏭ تجاهل",
        "unban": "🔓 إلغاء حظر",
        "add_admin": "➕ إضافة مشرف",
        "remove_admin": "➖ إزالة مشرف",
    }
    out = f"📋 سجل نشاط المشرف {admin_name}:\n\n"
    for log in logs[:15]:
        action = action_labels.get(log.action_type, log.action_type)
        out += f"{action} "
        if log.action_type == "reply":
            out += f"للمستخدم {log.user_name or log.user_id}\n"
            out += f"💬 {log.admin_reply or 'رسالة وسائط'}\n"
        elif log.action_type in ("quick_reply",):
            out += f"للمستخدم {log.user_name or log.user_id}: {log.details or ''}\n"
            out += f"💬 {log.admin_reply}\n"
        else:
            out += f"{log.details or ''}\n"
        out += f"🕐 {log.replied_at.strftime('%Y-%m-%d %H:%M')}\n\n"
    if len(logs) > 15:
        out += f"...و {len(logs) - 15} سجل آخر"
    await message.answer(out)
    await state.clear()


# ─── مراجعة الطلبات المرسلة (Messages Queue) ───

async def show_next_unread(target, state: FSMContext) -> None:
    messages = await get_unread_messages()
    if not messages:
        await target.answer("✅ لا يوجد مرسلات.")
        return

    data = await state.get_data()
    current_idx = data.get("queue_index", 0)

    if current_idx >= len(messages):
        await target.answer("✅ انتهت المراجعة!\nلا يوجد مرسلات جدد.")
        await state.clear()
        return

    msg = messages[current_idx]
    user = await get_user(msg.user_id)
    user_name = user.full_name if user else "غير معروف"
    username_part = f"@{user.username}" if user and user.username else "لا يوجد"
    content = msg.content or msg.caption or "بدون محتوى"
    type_map = {"text": "📝", "photo": "🖼", "video": "🎥", "document": "📄",
                "audio": "🎵", "voice": "🎤", "sticker": "😊"}
    msg_type_icon = type_map.get(msg.message_type, "📎")

    text = (
        f"📩 الرسالة {current_idx + 1}/{len(messages)}\n"
        f"{'═' * 15}\n"
        f"👤 {user_name}\n"
        f"🆔 {msg.user_id}\n"
        f"🔗 {username_part}\n"
        f"{msg_type_icon} {msg.message_type}\n"
        f"{'─' * 10}\n"
        f"{content}\n"
        f"{'═' * 15}"
    )

    await state.update_data(queue_index=current_idx, queue_total=len(messages))
    reply_markup = message_review_keyboard(msg.id, msg.user_id, user_name, current_idx, len(messages))
    await target.answer(text, reply_markup=reply_markup)


@router.callback_query(AdminFilter(), F.data == "review_prev")
async def review_prev_cb(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    current_idx = data.get("queue_index", 0)
    if current_idx > 0:
        current_idx -= 1
        await state.update_data(queue_index=current_idx)
    await callback.message.delete()
    await show_next_unread(callback.message, state)
    await callback.answer()


@router.callback_query(AdminFilter(), F.data == "review_next")
async def review_next_cb(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    current_idx = data.get("queue_index", 0)
    current_idx += 1
    await state.update_data(queue_index=current_idx)
    await callback.message.delete()
    await show_next_unread(callback.message, state)
    await callback.answer()


@router.callback_query(AdminFilter(), F.data.startswith("review_reply:"))
async def review_reply_cb(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    msg_id = int(parts[1])
    user_id = int(parts[2])
    user_name = ":".join(parts[3:])

    await mark_message_read(msg_id)
    await state.set_state(ReplyState.waiting_for_reply)
    await state.update_data(
        reply_user_id=user_id,
        reply_user_name=user_name,
        after_reply_action="next_unread",
    )
    kb = await quick_reply_keyboard()
    await callback.message.answer(
        f"💬 اختر رداً سريعاً للمستخدم {user_name} أو اكتب رداً مخصصاً:",
        reply_markup=kb,
    )
    await callback.answer()


@router.message(SuperAdminFilter(), F.text == "/resetdata")
async def reset_data_command(message: Message) -> None:
    from database.crud import reset_all_data
    await message.answer("♻️ جاري حذف جميع البيانات...")
    counts = await reset_all_data()
    await message.answer(
        "✅ تم حذف جميع البيانات بنجاح!\n\n"
        f"• الرسائل: {counts['messages']}\n"
        f"• المرفقات: {counts['attachments']}\n"
        f"• الردود السريعة: {counts['replies']}\n"
        f"• السجلات: {counts['logs']}\n"
        f"• المستخدمين المحذوفين: {counts['users_deleted']}\n"
        f"• المشرفين الأساسيين المحتفظ بهم: {counts['users_kept']}",
        reply_markup=await admin_main_keyboard(message.from_user.id),
    )


@router.callback_query(AdminFilter(), F.data == "review_done")
async def review_done_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.answer("✅ تم إنهاء المراجعة.", reply_markup=await admin_main_keyboard(callback.from_user.id))
    await callback.answer()
