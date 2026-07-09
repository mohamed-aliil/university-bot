import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from config import settings
from database.crud import get_or_create_user, save_message, save_attachment, is_banned, is_admin_user, get_all_autoreplies, get_all_admins
from keyboards.reply import main_keyboard, admin_reply_keyboard, cancel_keyboard, confirm_send_keyboard
from services.spam import contains_spam

logger = logging.getLogger(__name__)
router = Router()


class ReplyState(StatesGroup):
    waiting_for_reply = State()


class PendingUserMessage(StatesGroup):
    waiting_confirmation = State()


def get_message_type_text(msg_type: str) -> str:
    type_map = {
        "text": "📝 نص",
        "photo": "🖼 صورة",
        "video": "🎥 فيديو",
        "document": "📄 ملف",
        "audio": "🎵 صوتي",
        "voice": "🎤 تسجيل صوتي",
        "sticker": "😊 ملصق",
        "animation": "🎬 متحركة",
        "video_note": "🎞 رسالة فيديو",
    }
    return type_map.get(msg_type, msg_type)


async def forward_to_admins(message: Message, msg_type: str, db_message_id: int) -> None:
    user = message.from_user

    content_preview = (
        message.text or message.caption or
        (f"[{msg_type_map().get(msg_type, 'وسائط')}]" if msg_type != "text" else "")
    )
    short_notification = (
        f"💬 محادثة جديدة\n"
        f"👤 {user.full_name}\n"
        f"🆔 {user.id}\n"
        f"──────────\n"
        f"{content_preview[:200]}"
    )

    reply_markup = admin_reply_keyboard(user.id, user.full_name)

    all_admin_ids = list(settings.admin_ids)
    db_admins = await get_all_admins()
    for a in db_admins:
        if a.user_id not in all_admin_ids:
            all_admin_ids.append(a.user_id)

    for admin_id in all_admin_ids:
        try:
            await message.bot.send_message(
                chat_id=admin_id,
                text=short_notification,
                reply_markup=reply_markup,
            )
        except Exception as e:
            logger.error(f"Failed to send notification to admin {admin_id}: {e}")


async def forward_message_copy(message: Message, chat_id: int, caption: str, reply_markup) -> None:
    if message.text:
        await message.bot.send_message(chat_id=chat_id, text=caption, reply_markup=reply_markup)
    elif message.photo:
        await message.bot.send_photo(
            chat_id=chat_id, photo=message.photo[-1].file_id,
            caption=caption, reply_markup=reply_markup,
        )
    elif message.video:
        await message.bot.send_video(
            chat_id=chat_id, video=message.video.file_id,
            caption=caption, reply_markup=reply_markup,
        )
    elif message.document:
        await message.bot.send_document(
            chat_id=chat_id, document=message.document.file_id,
            caption=caption, reply_markup=reply_markup,
        )
    elif message.audio:
        await message.bot.send_audio(
            chat_id=chat_id, audio=message.audio.file_id,
            caption=caption, reply_markup=reply_markup,
        )
    elif message.voice:
        await message.bot.send_voice(
            chat_id=chat_id, voice=message.voice.file_id,
            caption=caption, reply_markup=reply_markup,
        )
    elif message.sticker:
        await message.bot.send_sticker(chat_id=chat_id, sticker=message.sticker.file_id)
        await message.bot.send_message(chat_id=chat_id, text=caption, reply_markup=reply_markup)
    elif message.animation:
        await message.bot.send_animation(
            chat_id=chat_id, animation=message.animation.file_id,
            caption=caption, reply_markup=reply_markup,
        )
    elif message.video_note:
        await message.bot.send_video_note(chat_id=chat_id, video_note=message.video_note.file_id)
        await message.bot.send_message(chat_id=chat_id, text=caption, reply_markup=reply_markup)
    else:
        await message.bot.send_message(chat_id=chat_id, text=caption, reply_markup=reply_markup)


def extract_message_content(message: Message) -> dict:
    data = {"type": "text", "content": None, "file_id": None, "file_unique_id": None, "caption": None}

    if message.text:
        data["type"] = "text"
        data["content"] = message.text
    elif message.photo:
        data["type"] = "photo"
        data["file_id"] = message.photo[-1].file_id
        data["file_unique_id"] = message.photo[-1].file_unique_id
        data["caption"] = message.caption
    elif message.video:
        data["type"] = "video"
        data["file_id"] = message.video.file_id
        data["file_unique_id"] = message.video.file_unique_id
        data["caption"] = message.caption
    elif message.document:
        data["type"] = "document"
        data["file_id"] = message.document.file_id
        data["file_unique_id"] = message.document.file_unique_id
        data["caption"] = message.caption
    elif message.audio:
        data["type"] = "audio"
        data["file_id"] = message.audio.file_id
        data["file_unique_id"] = message.audio.file_unique_id
        data["caption"] = message.caption
    elif message.voice:
        data["type"] = "voice"
        data["file_id"] = message.voice.file_id
        data["file_unique_id"] = message.voice.file_unique_id
    elif message.sticker:
        data["type"] = "sticker"
        data["file_id"] = message.sticker.file_id
        data["file_unique_id"] = message.sticker.file_unique_id
    elif message.animation:
        data["type"] = "animation"
        data["file_id"] = message.animation.file_id
        data["file_unique_id"] = message.animation.file_unique_id
        data["caption"] = message.caption
    elif message.video_note:
        data["type"] = "video_note"
        data["file_id"] = message.video_note.file_id
        data["file_unique_id"] = message.video_note.file_unique_id

    return data


@router.message(F.text == "✉️ تواصل معنا")
async def contact_prompt(message: Message) -> None:
    user = message.from_user
    if user.id in settings.admin_ids:
        from keyboards.reply import admin_panel_keyboard
        await message.answer("🔧 لوحة التحكم:", reply_markup=admin_panel_keyboard())
        return
    await message.answer(
        "✉️ نافذة التواصل المباشر مع إدارة القناة.\n\n"
        "يمكنك إرسال رسالتك أو ملفاتك الآن بأي صيغة تفضلها؛\n"
        "وسيتولى فريق الإشراف مراجعتها والرد عليك في أسرع وقت لخدمتك.",
        reply_markup=main_keyboard(),
    )


@router.message()
async def handle_all_messages(message: Message, state: FSMContext) -> None:
    user = message.from_user

    if user.id in settings.admin_ids or await is_admin_user(user.id):
        return

    if await is_banned(user.id):
        return

    from database.crud import is_bot_active
    if not is_bot_active():
        await message.answer(
            "⛔ البوت متوقف حاليًا. يرجى المحاولة لاحقًا.",
            reply_markup=main_keyboard(),
        )
        return

    is_spam, spam_reason = contains_spam(message.text or message.caption or "")
    if is_spam:
        return

    if message.text:
        autoreplies = await get_all_autoreplies()
        for ar in autoreplies:
            if ar.trigger.lower() in message.text.lower():
                await message.answer(ar.response)
                break

    content_data = extract_message_content(message)
    preview = content_data["content"] or content_data["caption"] or ""
    if not preview:
        type_names = {"photo": "🖼 صورة", "video": "🎥 فيديو", "document": "📄 ملف",
                      "audio": "🎵 صوتي", "voice": "🎤 تسجيل", "sticker": "😊 ملصق",
                      "animation": "🎬 متحركة", "video_note": "🎞 فيديو"}
        preview = type_names.get(content_data["type"], "📎 رسالة")

    sent = await message.answer(
        f"📝 تأكيد الإرسال\n\n"
        f"{preview}\n\n"
        f"هل أنت متأكد من إرسال هذه الرسالة؟",
        reply_markup=confirm_send_keyboard(message.message_id),
    )

    await state.set_state(PendingUserMessage.waiting_confirmation)
    await state.update_data(content_data=content_data, pending_msg_id=message.message_id)


@router.callback_query(PendingUserMessage.waiting_confirmation, F.data.startswith("confirm_send:yes:"))
async def confirm_send_yes(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    content_data = data.get("content_data", {})
    user = callback.from_user

    await get_or_create_user(
        user_id=user.id,
        full_name=user.full_name or "بدون اسم",
        username=user.username,
    )

    db_msg = await save_message(
        user_id=user.id,
        message_type=content_data.get("type", "text"),
        content=content_data.get("content"),
        file_id=content_data.get("file_id"),
        file_unique_id=content_data.get("file_unique_id"),
        caption=content_data.get("caption"),
    )

    caption_text = (
        f"💬 رسالة جديدة\n"
        f"👤 {user.full_name}\n"
        f"🆔 {user.id}\n"
    )
    if content_data.get("caption"):
        caption_text += f"\n📝 {content_data['caption']}"

    reply_markup = admin_reply_keyboard(user.id, user.full_name)

    all_admin_ids = list(settings.admin_ids)
    db_admins = await get_all_admins()
    for a in db_admins:
        if a.user_id not in all_admin_ids:
            all_admin_ids.append(a.user_id)

    for admin_id in all_admin_ids:
        try:
            msg_type = content_data.get("type", "text")
            file_id = content_data.get("file_id")
            bot = callback.bot
            if msg_type == "photo" and file_id:
                await bot.send_photo(chat_id=admin_id, photo=file_id, caption=caption_text, reply_markup=reply_markup)
            elif msg_type == "video" and file_id:
                await bot.send_video(chat_id=admin_id, video=file_id, caption=caption_text, reply_markup=reply_markup)
            elif msg_type == "document" and file_id:
                await bot.send_document(chat_id=admin_id, document=file_id, caption=caption_text, reply_markup=reply_markup)
            elif msg_type == "audio" and file_id:
                await bot.send_audio(chat_id=admin_id, audio=file_id, caption=caption_text, reply_markup=reply_markup)
            elif msg_type == "voice" and file_id:
                await bot.send_voice(chat_id=admin_id, voice=file_id, caption=caption_text, reply_markup=reply_markup)
            elif msg_type == "sticker" and file_id:
                await bot.send_sticker(chat_id=admin_id, sticker=file_id)
                await bot.send_message(chat_id=admin_id, text=caption_text, reply_markup=reply_markup)
            elif msg_type == "animation" and file_id:
                await bot.send_animation(chat_id=admin_id, animation=file_id, caption=caption_text, reply_markup=reply_markup)
            elif msg_type == "video_note" and file_id:
                await bot.send_video_note(chat_id=admin_id, video_note=file_id)
                await bot.send_message(chat_id=admin_id, text=caption_text, reply_markup=reply_markup)
            else:
                await bot.send_message(chat_id=admin_id, text=caption_text, reply_markup=reply_markup)
        except Exception as e:
            logger.error(f"Failed to send notification to admin {admin_id}: {e}")

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "✅ تم إرسال رسالتك بنجاح!\n"
        "سيتم مراجعتها من قبل المشرفين في أقرب وقت ممكن.",
        reply_markup=main_keyboard(),
    )
    await state.clear()
    await callback.answer()


@router.callback_query(PendingUserMessage.waiting_confirmation, F.data.startswith("confirm_send:no:"))
async def confirm_send_no(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "❌ تم إلغاء الإرسال.",
        reply_markup=main_keyboard(),
    )
    await state.clear()
    await callback.answer()
