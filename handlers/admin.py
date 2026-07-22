import logging
import html as html_mod
import re
import traceback
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from filters import AdminFilter, SuperAdminFilter, PermissionFilter
from database.crud import (
    ban_user, unban_user, get_user, set_admin, get_all_admins,
    unban_all_users, add_autoreply, remove_autoreply, get_all_autoreplies,
    set_permission, get_admin_permissions, get_all_users, get_stats,
    get_unread_messages, get_user_messages, mark_message_read,
    save_reply_log, save_admin_action,
    cleanup_old_data, get_db_table_stats, _fmt_size,
    is_ai_active, set_ai_active, is_ai_hidden, set_ai_hidden,
)
from keyboards.reply import cancel_keyboard, main_keyboard, moderator_keyboard, admin_keyboard, super_admin_keyboard, admin_panel_keyboard, permission_keyboard, admins_panel_keyboard, replies_panel_keyboard, bans_panel_keyboard, users_panel_keyboard, rank_keyboard, message_review_keyboard, admin_management_keyboard, communication_keyboard, settings_keyboard, stop_choice_keyboard, admins_management_keyboard, users_management_keyboard, replies_management_keyboard, quick_reply_inline_keyboard, quick_reply_keyboard, news_keyboard, customize_news_keyboard, logs_type_keyboard, confirm_cleanup_keyboard, review_reply_keyboard, ai_settings_keyboard, main_keyboard
from handlers.messages import ReplyState
from services.news import load_templates, add_template, remove_template
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
                return admin_keyboard(unread_count=stats["unread"])
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


class BroadcastState(StatesGroup):
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


class NewsState(StatesGroup):
    waiting_template = State()
    waiting_content = State()


class AddNewsTemplateState(StatesGroup):
    waiting_name = State()


class RemoveNewsTemplateState(StatesGroup):
    waiting_name = State()


class QuickNewsState(StatesGroup):
    waiting_content = State()


class ReviewState(StatesGroup):
    browsing = State()


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
        await callback.message.answer(text, reply_markup=users_panel_keyboard())
        return
    lines = []
    for u in users:
        status = "🚫" if u.is_banned else "✅"
        role = "👑" if u.user_id in settings.admin_ids else "👤"
        safe_name = html_mod.escape(u.full_name)
        lines.append(f"{role} {safe_name} - {u.user_id} {status}")
    total = len(lines)
    chunk = text + f"({total} مستخدم)\n"
    for line in lines:
        if len(chunk) + len(line) + 1 > 4000:
            await callback.message.answer(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk:
        await callback.message.answer(chunk)
    await callback.message.answer("👥 اختر:", reply_markup=users_panel_keyboard())


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
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer()


@router.callback_query(AdminFilter(), F.data.startswith("mute:"))
async def mute_user_notifications_handler(callback: CallbackQuery) -> None:
    from database.crud import mute_user_notifications as mute_fn
    _, user_id = callback.data.split(":", 1)
    user_id = int(user_id)
    await mute_fn(user_id, muted=True)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.answer("✅ تم كتم إشعارات هذا المستخدم.", show_alert=True)


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
            await show_next_unread(callback, state)
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
        # Release lock and re-notify other admins
        data2 = await state.get_data()
        rmid = data2.get("reply_msg_id")
        if rmid:
            from handlers.messages import _release_message_lock
            await _release_message_lock(rmid)
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
        elif message.audio:
            await message.bot.send_audio(chat_id=reply_user_id, audio=message.audio.file_id, caption=message.caption or "")
        elif message.animation:
            await message.bot.send_animation(chat_id=reply_user_id, animation=message.animation.file_id, caption=message.caption or "")
        elif message.video_note:
            await message.bot.send_video_note(chat_id=reply_user_id, video_note=message.video_note.file_id)
        elif message.sticker:
            await message.bot.send_sticker(chat_id=reply_user_id, sticker=message.sticker.file_id)
        else:
            await message.bot.send_message(chat_id=reply_user_id, text=reply_text or " ")

        await message.answer(f"✅ تم إرسال ردك إلى {reply_user_name} بنجاح.", reply_markup=await admin_main_keyboard(message.from_user.id))

        # Release lock
        rmid = data.get("reply_msg_id")
        if rmid:
            from handlers.messages import _release_message_lock
            await _release_message_lock(rmid)

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
        rmid = data.get("reply_msg_id")
        if rmid:
            from handlers.messages import _release_message_lock
            await _release_message_lock(rmid)

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
    if not users:
        await target.answer("📋 لا يوجد مستخدمين.")
        return
    lines = []
    for u in users:
        status = "🚫" if u.is_banned else "✅"
        role = "👑" if u.user_id in settings.admin_ids else "👤"
        safe_name = html_mod.escape(u.full_name or "غير معروف")
        username_part = f" (@{html_mod.escape(u.username)})" if u.username else ""
        lines.append(f"{role} {safe_name}{username_part} - {u.user_id} {status}")
    total = len(lines)
    header = f"📋 قائمة المستخدمين ({total}):\n"
    chunk = header
    for line in lines:
        if len(chunk) + len(line) + 1 > 4000:
            await target.answer(chunk)
            chunk = ""
        chunk += line + "\n"
    if chunk:
        await target.answer(chunk)


# ─── رجوع للقائمة الرئيسية ───

@router.message(AdminFilter(), F.text == "🔙 رجوع")
async def back_to_main(message: Message, state: FSMContext) -> None:
    cur = await state.get_state()
    if cur and (cur.startswith("MState") or cur.startswith("EditContentState")):
        from handlers.materials import handle_back
        await handle_back(message, state)
        return
    await state.clear()
    await message.answer("🔧 القائمة الرئيسية:", reply_markup=await admin_main_keyboard(message.from_user.id))


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

@router.message(SuperAdminFilter(), F.text == "📚 إدارة المواد")
async def panel_button(message: Message, state: FSMContext) -> None:
    try:
        from handlers.materials import materials_entry
        await materials_entry(message, state)
    except Exception as e:
        import traceback
        await message.answer(f"❌ خطأ: {e}\n\n{traceback.format_exc()[:500]}")


@router.message(SuperAdminFilter(), F.text == "⏹ إيقاف البوت")
async def stop_bot_prompt(message: Message) -> None:
    from database.crud import is_bot_active
    if not is_bot_active():
        return
    await message.answer("اختر نوع الإيقاف:", reply_markup=stop_choice_keyboard())


@router.message(SuperAdminFilter(), F.text == "🔇 إيقاف صامت")
async def stop_bot_silent(message: Message) -> None:
    from database.crud import set_bot_active
    set_bot_active(False)
    await message.answer("⛔ تم إيقاف البوت.", reply_markup=settings_keyboard(bot_active=False))


@router.message(SuperAdminFilter(), F.text == "📢 إيقاف مع إعلام")
async def stop_bot_with_notify(message: Message) -> None:
    from database.crud import set_bot_active, get_all_users
    from config import settings
    set_bot_active(False)
    users = await get_all_users()
    sent = 0
    for u in users:
        if u.user_id in settings.admin_ids:
            continue
        try:
            await message.bot.send_message(
                u.user_id,
                "⛔ البوت متوقف حاليًا. يرجى المحاولة لاحقًا.",
            )
            sent += 1
        except Exception:
            pass
    await message.answer(
        f"⛔ تم إيقاف البوت وإعلام {sent} مستخدم.",
        reply_markup=settings_keyboard(bot_active=False),
    )


@router.message(SuperAdminFilter(), F.text == "▶️ تشغيل البوت")
async def start_bot_kb(message: Message) -> None:
    from database.crud import set_bot_active
    set_bot_active(True)
    await message.answer("✅ تم تشغيل البوت.", reply_markup=settings_keyboard(bot_active=True))


@router.message(AdminFilter(), F.text.startswith("📩 الطلبات المرسلة"))
async def messages_queue_button(message: Message, state: FSMContext) -> None:
    try:
        await show_next_unread(message, state)
    except Exception as e:
        tb = traceback.format_exc()
        logger.exception("Error in messages_queue_button")
        from database.crud import save_error
        save_error("messages_queue_button", tb[-1000:])
        try:
            from aiogram.enums import ParseMode
            await message.answer(
                f"⚠️ خطأ:\n<code>{html_mod.escape(tb[-1500:])}</code>",
                parse_mode=ParseMode.HTML,
                reply_markup=await admin_main_keyboard(message.from_user.id),
            )
        except Exception:
            await message.answer(f"⚠️ خطأ: {e}", parse_mode=None)


@router.message(SuperAdminFilter(), F.text == "👥 المشرفين")
async def admins_button(message: Message) -> None:
    await list_admins(message)
    await message.answer("👥 إدارة المشرفين:", reply_markup=admins_management_keyboard())


@router.message(SuperAdminFilter(), F.text == "📋 المستخدمين")
async def users_button(message: Message) -> None:
    try:
        from database.crud import get_all_users
        users = await get_all_users()
        await show_users_list(message)
    except Exception as e:
        logger.exception("users_button error")
        await message.answer(f"❌ حدث خطأ: {e}")
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


@router.message(SuperAdminFilter(), F.text == "👥 الإدارة")
async def admin_management_button(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("👥 اختر ما تريد:", reply_markup=admin_management_keyboard())


@router.message(AdminFilter(), F.text == "💬 التواصل")
async def communication_button(message: Message) -> None:
    await message.answer("💬 اختر ما تريد:", reply_markup=communication_keyboard())


# ─── إدارة قوالب الأخبار ───

@router.message(SuperAdminFilter(), F.text == "➕ إضافة قالب")
async def add_news_template_start(message: Message, state: FSMContext) -> None:
    cur = await state.get_state()
    if cur == AddNewsTemplateState.waiting_name.state:
        name = message.text.strip()
        ok = await add_template(name)
        if ok:
            await message.answer(f"✅ تم إضافة القالب: {name}", reply_markup=customize_news_keyboard())
        else:
            await message.answer("❌ هذا القالب موجود بالفعل.")
        await state.clear()
        return
    await state.set_state(AddNewsTemplateState.waiting_name)
    await message.answer("✏️ أرسل اسم القالب الجديد:", reply_markup=cancel_keyboard())


@router.message(AddNewsTemplateState.waiting_name, SuperAdminFilter())
async def add_news_template_save(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    ok = await add_template(name)
    if ok:
        await message.answer(f"✅ تم إضافة القالب: {name}", reply_markup=customize_news_keyboard())
    else:
        await message.answer("❌ هذا القالب موجود بالفعل.")
    await state.clear()


@router.message(SuperAdminFilter(), F.text == "➖ حذف قالب")
async def remove_news_template_start(message: Message, state: FSMContext) -> None:
    cur = await state.get_state()
    if cur == RemoveNewsTemplateState.waiting_name.state:
        name = message.text.strip()
        ok = await remove_template(name)
        if ok:
            await message.answer(f"✅ تم حذف القالب: {name}", reply_markup=customize_news_keyboard())
        else:
            await message.answer("❌ هذا القالب غير موجود.")
        await state.clear()
        return
    await state.set_state(RemoveNewsTemplateState.waiting_name)
    await message.answer("✏️ أرسل اسم القالب الذي تريد حذفه:", reply_markup=cancel_keyboard())


@router.message(RemoveNewsTemplateState.waiting_name, SuperAdminFilter())
async def remove_news_template_save(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    ok = await remove_template(name)
    if ok:
        await message.answer(f"✅ تم حذف القالب: {name}", reply_markup=customize_news_keyboard())
    else:
        await message.answer("❌ هذا القالب غير موجود.")
    await state.clear()


@router.message(SuperAdminFilter(), F.text == "📋 عرض القوالب")
async def show_news_templates(message: Message) -> None:
    templates = await load_templates()
    text = "📋 قوالب الأخبار:\n\n"
    for i, t in enumerate(templates, 1):
        text += f"{i}. {t}\n"
    await message.answer(text, reply_markup=customize_news_keyboard())


# ─── الأخبار ───

@router.message(AdminFilter(), F.text == "📰 الأخبار")
async def news_button(message: Message, state: FSMContext) -> None:
    from config import settings
    if not settings.NEWS_CHANNEL_ID:
        await message.answer("❌ لم يتم تعيين قناة الأخبار.\nتواصل مع السوبر administrator لإعدادها.")
        return
    await state.set_state(NewsState.waiting_template)
    await message.answer("📰 اختر قالب الخبر:", reply_markup=await news_keyboard())


@router.message(AdminFilter(), F.text == "📝 خبر مباشر")
async def quick_news_start(message: Message, state: FSMContext) -> None:
    await message.answer("✏️ أرسل محتوى الخبر مباشرة:", reply_markup=cancel_keyboard())
    await state.set_state(QuickNewsState.waiting_content)


@router.message(QuickNewsState.waiting_content, AdminFilter())
async def quick_news_send(message: Message, state: FSMContext) -> None:
    from database.crud import save_sent_news
    text = message.text.strip()
    if not text:
        await message.answer("❌ المحتوى لا يمكن أن يكون فارغًا.")
        return
    if not settings.NEWS_CHANNEL_ID:
        await message.answer("❌ لم يتم تعيين قناة الأخبار.")
        await state.clear()
        return
    try:
        sent = await message.bot.send_message(settings.NEWS_CHANNEL_ID, f"📰 {text}")
        await save_sent_news(channel_message_id=sent.message_id, content=f"📰 {text}")
        await message.answer("✅ تم نشر الخبر في القناة.", reply_markup=await news_keyboard())
    except Exception as e:
        logging.exception("quick_news_send")
        await message.answer(f"❌ فشل النشر: {e}")
    await state.clear()


@router.message(NewsState.waiting_template, AdminFilter())
async def news_template_chosen(message: Message, state: FSMContext) -> None:
    templates = await load_templates()
    if message.text not in templates:
        await message.answer("❌ هذا القالب غير موجود. اختر من القائمة:", reply_markup=await news_keyboard())
        return
    await state.set_state(NewsState.waiting_content)
    await state.update_data(news_template=message.text)
    await message.answer(
        "✏️ أرسل محتوى الخبر الآن:",
        reply_markup=cancel_keyboard(),
    )


@router.message(NewsState.waiting_content, AdminFilter())
async def news_content_sent(message: Message, state: FSMContext) -> None:
    from aiogram.enums import ParseMode
    from config import settings
    from database.crud import save_sent_news
    data = await state.get_data()
    template = data.get("news_template", "")
    channel = settings.NEWS_CHANNEL_ID
    content = message.text or message.caption or ""

    full_text = f"<b>{template}</b>\n\n{content}"

    try:
        channel_id = int(channel) if channel.lstrip("-").isdigit() else channel
        if message.text:
            sent = await message.bot.send_message(chat_id=channel_id, text=full_text, parse_mode=ParseMode.HTML)
        elif message.photo:
            sent = await message.bot.send_photo(
                chat_id=channel_id, photo=message.photo[-1].file_id,
                caption=full_text, parse_mode=ParseMode.HTML,
            )
        elif message.video:
            sent = await message.bot.send_video(
                chat_id=channel_id, video=message.video.file_id,
                caption=full_text, parse_mode=ParseMode.HTML,
            )
        elif message.document:
            sent = await message.bot.send_document(
                chat_id=channel_id, document=message.document.file_id,
                caption=full_text, parse_mode=ParseMode.HTML,
            )
        else:
            sent = await message.bot.send_message(chat_id=channel_id, text=full_text)
        await save_sent_news(channel_message_id=sent.message_id, template=template, content=content)
        await message.answer("✅ تم نشر الخبر في القناة!", reply_markup=await news_keyboard())
    except Exception as e:
        logger.error(f"Failed to send news to channel: {e}")
        await message.answer(
            "❌ فشل النشر. تأكد من:\n"
            "• صحة معرف القناة\n"
            "• أن البوت مشرف في القناة",
            reply_markup=await news_keyboard(),
        )
    await state.clear()


# ─── تخصيص قوالب الأخبار ───

@router.message(SuperAdminFilter(), F.text == "📡 إدارة القنوات")
async def channels_menu_admin(message: Message, state: FSMContext) -> None:
    from handlers.channels import channels_menu
    await channels_menu(message, state)


@router.message(SuperAdminFilter(), F.text == "📡 تخصيص الأخبار")
async def customize_news_button(message: Message, state: FSMContext) -> None:
    await state.clear()
    templates = await load_templates()
    text = "📡 قوالب الأخبار الحالية:\n\n"
    for i, t in enumerate(templates, 1):
        text += f"{i}. {t}\n"
    await message.answer(text, reply_markup=customize_news_keyboard())


@router.message(SuperAdminFilter(), F.text == "🗑 آخر الأخبار")
async def delete_news_list(message: Message, state: FSMContext) -> None:
    from database.crud import get_recent_sent_news
    news_list = await get_recent_sent_news(limit=10)
    if not news_list:
        await message.answer("📋 لا توجد أخبار منشورة.", reply_markup=customize_news_keyboard())
        return
    kb = InlineKeyboardBuilder()
    for n in news_list:
        preview = (n.template or "") + ": " + (n.content or "")[:30]
        kb.button(text=preview, callback_data=f"delnews:{n.id}")
    kb.adjust(1)
    await message.answer("📋 آخر الأخبار المنشورة (اختر لحذف):", reply_markup=kb.as_markup())


@router.callback_query(SuperAdminFilter(), F.data.startswith("delnews:"))
async def delete_news_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    from config import settings
    from database.crud import get_recent_sent_news, delete_sent_news
    news_id = int(callback.data.split(":")[1])
    news_list = await get_recent_sent_news(limit=10)
    news = next((n for n in news_list if n.id == news_id), None)
    if not news:
        await callback.answer("❌ الخبر غير موجود.", show_alert=True)
        return
    confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تأكيد الحذف", callback_data=f"confirm_delnews:{news_id}"),
         InlineKeyboardButton(text="❌ إلغاء", callback_data="cancel_delnews")]
    ])
    await callback.message.edit_text(
        f"🗑 هل أنت متأكد من حذف هذا الخبر من القناة؟\n\n{news.template or ''}: {news.content or ''}",
        reply_markup=confirm_kb,
    )
    await callback.answer()


@router.callback_query(SuperAdminFilter(), F.data.startswith("confirm_delnews:"))
async def delete_news_execute(callback: CallbackQuery, state: FSMContext) -> None:
    from config import settings
    from database.crud import get_recent_sent_news, delete_sent_news
    news_id = int(callback.data.split(":")[1])
    news_list = await get_recent_sent_news(limit=10)
    news = next((n for n in news_list if n.id == news_id), None)
    if not news:
        await callback.answer("❌ الخبر غير موجود.", show_alert=True)
        return
    try:
        channel_id = int(settings.NEWS_CHANNEL_ID) if settings.NEWS_CHANNEL_ID.lstrip("-").isdigit() else settings.NEWS_CHANNEL_ID
        await callback.bot.delete_message(chat_id=channel_id, message_id=news.channel_message_id)
        await delete_sent_news(news_id)
        await callback.message.edit_text("✅ تم حذف الخبر من القناة.")
    except Exception as e:
        logger.error(f"Failed to delete news message: {e}")
        await callback.message.edit_text("❌ فشل حذف الخبر. تأكد من صلاحيات البوت في القناة.")
    await callback.answer()


@router.callback_query(SuperAdminFilter(), F.data == "cancel_delnews")
async def delete_news_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("✅ تم الإلغاء.")
    await callback.answer()


@router.message(SuperAdminFilter(), F.text == "⚙️ الإعدادات")
async def settings_button(message: Message) -> None:
    from database.crud import is_bot_active
    bot_active = is_bot_active()
    await message.answer("⚙️ الإعدادات", reply_markup=settings_keyboard(bot_active=bot_active))


@router.message(AdminFilter(), F.text == "🔄 تحديث")
async def refresh_button(message: Message) -> None:
    await message.answer("✅ تم التحديث", reply_markup=await admin_main_keyboard(message.from_user.id))


# ─── أزرار القوائم الفرعية (ReplyKeyboard) ───

@router.message(PermissionFilter("can_manage"), F.text == "📩 إرسال رسالة")
async def sendmsg_from_kb(message: Message, state: FSMContext) -> None:
    await state.set_state(SendMsgState.waiting_for_id)
    await message.answer(
        "📩 أرسل معرف المستخدم (User ID) أو اسم المستخدم (@username):",
        reply_markup=cancel_keyboard(),
    )





@router.message(PermissionFilter("can_view_logs"), F.text == "📋 السجلات")
async def logs_prompt(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "📋 اختر نوع السجلات:",
        reply_markup=logs_type_keyboard(),
    )


@router.message(PermissionFilter("can_view_logs"), F.text == "📦 سجلات المواد")
async def logs_materials_start(message: Message, state: FSMContext) -> None:
    await state.set_state(LogsState.waiting_for_id)
    await state.update_data(log_type="materials")
    await message.answer(
        "📋 أرسل معرف المشرف (ID) أو اسم المستخدم (@username):",
        reply_markup=cancel_keyboard(),
    )


@router.message(PermissionFilter("can_view_logs"), F.text == "💬 سجلات الطلبات")
async def logs_messages_start(message: Message, state: FSMContext) -> None:
    await state.set_state(LogsState.waiting_for_id)
    await state.update_data(log_type="messages")
    await message.answer(
        "📋 أرسل معرف المشرف (ID) أو اسم المستخدم (@username):",
        reply_markup=cancel_keyboard(),
    )


@router.message(PermissionFilter("can_view_logs"), F.text == "📋 سجلات المستخدمين")
async def logs_users(message: Message) -> None:
    from database.crud import get_all_user_messages
    msgs = await get_all_user_messages(limit=20)
    if not msgs:
        await message.answer("📋 لا توجد رسائل من المستخدمين بعد.")
        return
    lines = []
    for m in msgs:
        user = await get_user(m.user_id)
        user_name = user.full_name if user else "غير معروف"
        content = (m.content or m.caption or "")[:100]
        time = m.created_at.strftime("%m-%d %H:%M")
        lines.append(f"👤 {user_name} (🆔 {m.user_id})\n💬 {content}\n🕐 {time}")
    out = "📋 **آخر 20 رسالة من المستخدمين:**\n\n" + "\n─────\n".join(lines)
    await message.answer(out)


@router.message(SuperAdminFilter(), F.text == "🤖 إعدادات AI")
async def ai_settings_panel(message: Message) -> None:
    active = is_ai_active()
    hidden = is_ai_hidden()
    status = "🟢 يعمل" if active else "🔴 متوقف"
    hidden_status = "مخفي 🙈" if hidden else "ظاهر 👁"
    await message.answer(
        f"🤖 إعدادات AI\nالحالة: {status}\nالزر: {hidden_status}",
        reply_markup=ai_settings_keyboard(),
    )


@router.message(SuperAdminFilter(), F.text == "⏹ إيقاف AI مع إعلام")
async def ai_stop_with_notify(message: Message) -> None:
    set_ai_active(False)
    await message.answer("🔴 تم إيقاف AI. المستخدمون سيرون الإعلام عند ضغط زر AI.", reply_markup=ai_settings_keyboard())


@router.message(SuperAdminFilter(), F.text == "🔇 إيقاف AI صامت")
async def ai_stop_silent(message: Message) -> None:
    from database.crud import set_ai_silent
    set_ai_silent()
    await message.answer("🔴 تم إيقاف AI بصمت.", reply_markup=ai_settings_keyboard())


@router.message(SuperAdminFilter(), F.text == "▶️ تشغيل AI")
async def ai_start(message: Message) -> None:
    set_ai_active(True)
    await message.answer("🟢 تم تشغيل AI.", reply_markup=ai_settings_keyboard())


@router.message(SuperAdminFilter(), F.text == "🙈 إخفاء الزر")
async def ai_hide_button(message: Message) -> None:
    set_ai_hidden(True)
    await message.answer("🙈 تم إخفاء زر نَافِذَة الـ AI من المستخدمين.", reply_markup=ai_settings_keyboard())


@router.message(SuperAdminFilter(), F.text == "👁 إظهار الزر")
async def ai_show_button(message: Message) -> None:
    set_ai_hidden(False)
    await message.answer("👁 تم إظهار زر نَافِذَة الـ AI للمستخدمين.", reply_markup=ai_settings_keyboard())


@router.message(SuperAdminFilter(), F.text == "📋 سجل الأخطاء")
async def ai_errors_button(message: Message) -> None:
    from database.crud import get_errors
    from aiogram.enums import ParseMode
    errors = get_errors(15)
    await message.answer(f"📋 آخر الأخطاء:\n\n<code>{errors}</code>", parse_mode=ParseMode.HTML)


@router.message(SuperAdminFilter(), F.text == "📋 سجل AI")
async def ai_log_button(message: Message) -> None:
    from database.crud import get_ai_log
    log = get_ai_log(30)
    await message.answer(f"📋 سجل AI (آخر 30):\n\n<code>{log}</code>")


@router.message(SuperAdminFilter(), F.text == "🧹 تنظيف قاعدة البيانات")
async def cleanup_db_prompt(message: Message) -> None:
    stats = await get_db_table_stats()
    total_bytes = stats["db_total_bytes"]
    total = _fmt_size(total_bytes)
    rows, sizes = stats["rows"], stats["sizes"]

    MAX_DB_BYTES = 1073741824  # 1 GB
    pct = total_bytes / MAX_DB_BYTES * 100
    bar_len = 10
    filled = int(pct / 100 * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)

    msg_parts = [
        f"📊 **حجم قاعدة البيانات: {total}**",
        f"⚡ السعة القصوى: **1.0 GB**",
        f"📈 الاستخدام: {pct:.1f}%",
        f"`{bar}`",
    ]

    if pct >= 90:
        msg_parts.append("⚠️ **تحذير: قاعدة البيانات أوشكت على الامتلاء! نظف فورًا.**")
    elif pct >= 75:
        msg_parts.append("⚡ تنبيه: اقتربت من الحد الأقصى، يُنصح بالتنظيف قريبًا.")

    msg_parts.append("")
    for label, key in [("الرسائل", "messages"), ("المرفقات", "attachments"), ("سجلات الردود", "reply_logs"), ("الإشعارات", "admin_notifications"), ("المستخدمين", "users")]:
        row_count = rows.get(key, 0)
        size = _fmt_size(sizes.get(key, 0))
        msg_parts.append(f"• {label}: {row_count} ({size})")

    msg_parts.append(f"\n🧹 سيتم حذف الرسائل وسجلات الردود الأقدم من 60 يومًا.\nهل تريد المتابعة؟")
    await message.answer("\n".join(msg_parts), reply_markup=confirm_cleanup_keyboard())


@router.callback_query(F.data == "confirm_cleanup")
async def confirm_cleanup_cb(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text("🧹 جاري تنظيف قاعدة البيانات...")
    counts = await cleanup_old_data(days=60)
    stats = await get_db_table_stats()
    total = _fmt_size(stats["db_total_bytes"])
    rows = stats["rows"]
    sizes = stats["sizes"]
    detail = " | ".join(
        f"{k}: {rows[k]} ({_fmt_size(sizes[k])})" if sizes.get(k) else f"{k}: {rows[k]}"
        for k in ["messages", "attachments", "reply_logs", "users"]
    )
    await callback.message.edit_text(
        f"✅ تم التنظيف بنجاح!\n"
        f"• تم حذف: {counts.get('messages', 0)} رسالة, {counts.get('reply_logs', 0)} سجل\n"
        f"• الحجم الآن: {total}\n"
        f"• {detail}"
    )


@router.callback_query(F.data == "cancel_cleanup")
async def cancel_cleanup_cb(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text("❌ تم إلغاء التنظيف.")


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
        elif message.audio:
            await message.bot.send_audio(chat_id=target_id, audio=message.audio.file_id, caption=message.caption or "")
        elif message.animation:
            await message.bot.send_animation(chat_id=target_id, animation=message.animation.file_id, caption=message.caption or "")
        elif message.video_note:
            await message.bot.send_video_note(chat_id=target_id, video_note=message.video_note.file_id)
        elif message.sticker:
            await message.bot.send_sticker(chat_id=target_id, sticker=message.sticker.file_id)
        else:
            await message.bot.send_message(chat_id=target_id, text="📩 رسالة من الإدارة.")

        await message.answer(f"✅ تم إرسال الرسالة إلى {target_name} بنجاح.", reply_markup=await admin_main_keyboard(message.from_user.id))
    except Exception as e:
        logger.error(f"Failed to send message to {target_id}: {e}")
        await message.answer("❌ فشل الإرسال. قد يكون المستخدم أوقف البوت.", reply_markup=await admin_main_keyboard(message.from_user.id))

    await state.clear()


@router.message(PermissionFilter("can_manage"), F.text == "📢 إرسال للكل")
async def broadcast_start(message: Message, state: FSMContext) -> None:
    await state.set_state(BroadcastState.waiting_for_msg)
    await message.answer(
        "📢 أرسل الرسالة التي تريد إرسالها لكل المستخدمين:\n"
        "(نص، صورة، فيديو، ملف...)",
        reply_markup=cancel_keyboard(),
    )


@router.message(BroadcastState.waiting_for_msg, PermissionFilter("can_manage"))
async def broadcast_preview(message: Message, state: FSMContext) -> None:
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    preview_text = message.text or message.caption or "📢 رسالة"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تأكيد الإرسال", callback_data="broadcast:confirm"),
         InlineKeyboardButton(text="❌ إلغاء", callback_data="broadcast:cancel")]
    ])
    content_data = {
        "type": "text",
        "text": message.text,
        "caption": message.caption,
        "photo": message.photo[-1].file_id if message.photo else None,
        "video": message.video.file_id if message.video else None,
        "document": message.document.file_id if message.document else None,
        "voice": message.voice.file_id if message.voice else None,
    }
    await state.update_data(broadcast_content=content_data)
    await message.answer(
        f"📢 معاينة الرسالة:\n\n{preview_text[:200]}\n\nهل أنت متأكد من إرسالها لكل المستخدمين؟",
        reply_markup=kb,
    )
    await state.set_state(BroadcastState.waiting_for_msg)


@router.callback_query(PermissionFilter("can_manage"), F.data == "broadcast:confirm")
async def broadcast_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    content = data.get("broadcast_content", {})
    from database.crud import get_all_users
    users = await get_all_users()
    sent = 0
    failed = 0
    await callback.message.edit_reply_markup(reply_markup=None)
    status_msg = await callback.message.answer("📢 جاري الإرسال...")
    for u in users:
        try:
            if content.get("text"):
                await callback.bot.send_message(chat_id=u.user_id, text=content["text"])
            elif content.get("photo"):
                await callback.bot.send_photo(chat_id=u.user_id, photo=content["photo"], caption=content.get("caption") or "")
            elif content.get("video"):
                await callback.bot.send_video(chat_id=u.user_id, video=content["video"], caption=content.get("caption") or "")
            elif content.get("document"):
                await callback.bot.send_document(chat_id=u.user_id, document=content["document"], caption=content.get("caption") or "")
            elif content.get("voice"):
                await callback.bot.send_voice(chat_id=u.user_id, voice=content["voice"])
            else:
                await callback.bot.send_message(chat_id=u.user_id, text="📢 رسالة إدارية.")
            sent += 1
        except Exception:
            failed += 1
    await status_msg.delete()
    await callback.message.answer(
        f"📢 تم الإرسال!\n✅ نجح: {sent}\n❌ فشل: {failed}",
        reply_markup=await admin_main_keyboard(callback.from_user.id),
    )
    await state.clear()
    await callback.answer()


@router.callback_query(PermissionFilter("can_manage"), F.data == "broadcast:cancel")
async def broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("❌ تم إلغاء الإرسال.", reply_markup=await admin_main_keyboard(callback.from_user.id))
    await state.clear()
    await callback.answer()


# ─── عرض سجلات الردود ───

@router.message(LogsState.waiting_for_id, PermissionFilter("can_view_logs"))
async def logs_show(message: Message, state: FSMContext) -> None:
    from database.crud import get_reply_logs, get_all_users
    data = await state.get_data()
    log_type = data.get("log_type", "messages")

    materials_actions = {
        "add_folder": "➕ إضافة مجلد",
        "remove_folder": "➖ حذف مجلد",
        "add_content": "📄 إضافة محتوى",
        "remove_content": "🗑 حذف محتوى",
        "edit_content_title": "✏️ تعديل اسم محتوى",
        "add_link_content": "🔗 إضافة رابط",
        "remove_link_content": "➖ حذف رابط",
    }
    messages_actions = {
        "reply": "💬 رد",
        "quick_reply": "⚡ رد سريع",
        "ban": "🚫 حظر",
        "ignore": "⏭ تجاهل",
        "unban": "🔓 إلغاء حظر",
        "add_admin": "➕ إضافة مشرف",
        "remove_admin": "➖ إزالة مشرف",
    }

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

    logs = await get_reply_logs(admin_id=admin_id, limit=50)
    if log_type == "materials":
        label_map = materials_actions
        title = "📦 سجل إدارة المواد"
    else:
        label_map = messages_actions
        title = "💬 سجل الطلبات"

    filtered = [l for l in logs if l.action_type in label_map]
    if not filtered:
        await message.answer(f"📋 لا توجد سجلات {title} لهذا المشرف.")
        await state.clear()
        return

    admin_info = await get_user(admin_id)
    admin_name = admin_info.full_name if admin_info else str(admin_id)
    out = f"📋 {title} للمشرف {admin_name}:\n\n"
    for log in filtered[:15]:
        action = label_map.get(log.action_type, log.action_type)
        out += f"{action} "
        if log.action_type in ("reply", "quick_reply"):
            out += f"للمستخدم {log.user_name or log.user_id}\n"
            if log.user_message:
                out += f"👤 المستخدم: {log.user_message[:200]}\n"
            out += f"💬 الرد: {log.admin_reply or 'رسالة'}\n"
        else:
            out += f"{log.details or ''}\n"
        out += f"🕐 {log.replied_at.strftime('%Y-%m-%d %H:%M')}\n\n"
    if len(filtered) > 15:
        out += f"...و {len(filtered) - 15} سجل آخر"
    await message.answer(out)
    await state.clear()


# ─── مراجعة الطلبات المرسلة (Messages Queue) ───

async def show_next_unread(target, state: FSMContext) -> None:
    bot = target.bot if hasattr(target, "bot") else target.message.bot
    chat_id = target.message.chat.id if hasattr(target, "message") else target.chat.id

    admin_id = target.from_user.id if hasattr(target, 'from_user') and target.from_user else (target.message.from_user.id if hasattr(target, 'message') and target.message.from_user else None)
    if not admin_id:
        admin_id = (await state.get_data()).get("admin_id")

    messages = await get_unread_messages()
    if not messages:
        await state.set_state(ReviewState.browsing)
        reply_kb = review_reply_keyboard(muted=False, has_prev=False, has_next=False)
        await bot.send_message(chat_id=chat_id, text="✅ لا يوجد مرسلات.", reply_markup=reply_kb)
        return

    data = await state.get_data()
    current_idx = data.get("queue_index", 0)

    if current_idx >= len(messages):
        await state.set_state(ReviewState.browsing)
        reply_kb = review_reply_keyboard(muted=False, has_prev=False, has_next=False)
        await bot.send_message(chat_id=chat_id, text="✅ انتهت المراجعة!\nلا يوجد مرسلات جدد.", reply_markup=reply_kb)
        return
        return

    msg = messages[current_idx]
    user = await get_user(msg.user_id)
    user_name = user.full_name if user else "غير معروف"
    username_part = f"@{user.username}" if user and user.username else "لا يوجد"

    text_content = msg.content or msg.caption or ""

    caption = (
        f"📩 الرسالة {current_idx + 1}/{len(messages)}\n"
        f"{'═' * 15}\n"
        f"👤 {user_name}\n"
        f"🆔 {msg.user_id}\n"
        f"🔗 {username_part}"
    )
    if text_content:
        caption += f"\n{'─' * 10}\n{text_content[:400]}"
    caption += f"\n{'═' * 15}"

    await state.update_data(queue_index=current_idx, queue_total=len(messages))
    await state.set_state(ReviewState.browsing)

    from handlers.messages import _muted_admins
    muted = target.from_user.id in _muted_admins if hasattr(target, 'from_user') and target.from_user else False
    inline_kb = message_review_keyboard(msg.id, msg.user_id)
    reply_kb = review_reply_keyboard(muted=muted, has_prev=current_idx > 0, has_next=current_idx < len(messages) - 1)

    mtype = msg.message_type
    fid = msg.file_id

    import html as _html
    caption_clean = re.sub(r"<[^>]+>", "", caption)

    try:
        if mtype == "photo" and fid:
            await bot.send_photo(chat_id=chat_id, photo=fid, caption=caption_clean, reply_markup=inline_kb)
        elif mtype == "video" and fid:
            await bot.send_video(chat_id=chat_id, video=fid, caption=caption_clean, reply_markup=inline_kb)
        elif mtype == "document" and fid:
            await bot.send_document(chat_id=chat_id, document=fid, caption=caption_clean, reply_markup=inline_kb)
        elif mtype == "audio" and fid:
            await bot.send_audio(chat_id=chat_id, audio=fid, caption=caption_clean, reply_markup=inline_kb)
        elif mtype == "voice" and fid:
            await bot.send_voice(chat_id=chat_id, voice=fid, caption=caption_clean, reply_markup=inline_kb)
        elif mtype == "sticker" and fid:
            await bot.send_sticker(chat_id=chat_id, sticker=fid)
            await bot.send_message(chat_id=chat_id, text=caption_clean, reply_markup=inline_kb)
        elif mtype == "animation" and fid:
            await bot.send_animation(chat_id=chat_id, animation=fid, caption=caption_clean, reply_markup=inline_kb)
        elif mtype == "video_note" and fid:
            await bot.send_video_note(chat_id=chat_id, video_note=fid)
            await bot.send_message(chat_id=chat_id, text=caption_clean, reply_markup=inline_kb)
        else:
            await bot.send_message(chat_id=chat_id, text=caption_clean, reply_markup=inline_kb)
    except Exception:
        import traceback as tb_mod
        tb_str = tb_mod.format_exc()
        from database.crud import save_error
        save_error("show_next_unread", tb_str[-1000:])
        await bot.send_message(chat_id=chat_id, text=caption_clean, reply_markup=None)
        from aiogram.enums import ParseMode
        await bot.send_message(chat_id=chat_id, text=f"⚠️ خطأ في الأزرار:\n<code>{html_mod.escape(tb_str[-1500:])}</code>", parse_mode=ParseMode.HTML)

    await bot.send_message(chat_id=chat_id, text=".", reply_markup=reply_kb)


@router.message(ReviewState.browsing, F.text == "⬅️ السابق")
async def review_prev(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    current_idx = data.get("queue_index", 0)
    if current_idx > 0:
        current_idx -= 1
        await state.update_data(queue_index=current_idx)
    await show_next_unread(message, state)


@router.message(ReviewState.browsing, F.text == "➡️ التالي")
async def review_next(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    current_idx = data.get("queue_index", 0)
    current_idx += 1
    await state.update_data(queue_index=current_idx)
    await show_next_unread(message, state)


@router.message(ReviewState.browsing, F.text == "🔙 رجوع")
async def review_back(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🔝 القائمة الرئيسية", reply_markup=await admin_main_keyboard(message.from_user.id))


@router.message(ReviewState.browsing, F.text.in_(["🔇 إيقاف الإشعارات", "🔔 تشغيل الإشعارات"]))
async def review_mute(message: Message, state: FSMContext) -> None:
    admin_id = message.from_user.id
    from handlers.messages import _muted_admins
    if admin_id in _muted_admins:
        _muted_admins.discard(admin_id)
        status = "🔔 تم تشغيل الإشعارات"
    else:
        _muted_admins.add(admin_id)
        status = "🔇 تم إيقاف الإشعارات"
    await message.answer(status)
    await show_next_unread(message, state)


@router.callback_query(AdminFilter(), F.data.startswith("review_reply:"))
async def review_reply_cb(callback: CallbackQuery, state: FSMContext) -> None:
    from database.crud import get_admin_notifications, delete_admin_notifications, get_user
    from handlers.messages import _locked_messages
    parts = callback.data.split(":")
    msg_id = int(parts[1])
    user_id = int(parts[2])
    user_info = await get_user(user_id)
    user_name = user_info.full_name if user_info else "غير معروف"

    if msg_id in _locked_messages:
        await callback.answer("🔒 مشرف آخر يرد على هذه الرسالة حالياً.", show_alert=True)
        return

    _locked_messages[msg_id] = callback.from_user.id

    notifs = await get_admin_notifications(msg_id)
    for n in notifs:
        if n.admin_id != callback.from_user.id:
            try:
                await callback.bot.delete_message(chat_id=n.chat_id, message_id=n.notification_message_id)
            except Exception:
                pass

    await mark_message_read(msg_id)
    await state.update_data(reply_msg_id=msg_id)
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


@router.callback_query(AdminFilter(), F.data.startswith("review_delete:"))
async def review_delete_cb(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    msg_id = int(parts[1])
    await mark_message_read(msg_id)
    await callback.message.delete()
    data = await state.get_data()
    current_idx = data.get("queue_index", 0)
    await callback.answer("✅ تم حذف الرسالة.", show_alert=True)
    await show_next_unread(callback.message, state)


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
