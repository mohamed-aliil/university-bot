import logging
import re

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from database.crud import (
    add_monitored_channel, get_all_monitored_channels, remove_monitored_channel,
    get_monitored_channel_by_username, get_monitored_channel_by_channel_id,
    add_content_item, add_content_link, get_folders, add_folder,
    add_required_channel, get_all_required_channels, remove_required_channel,
    update_channel_message,
)
from datetime import datetime, timezone
from filters import SuperAdminFilter
from keyboards.reply import channels_keyboard, required_channels_keyboard, customize_news_keyboard, cancel_keyboard

logger = logging.getLogger(__name__)
router = Router()
channel_router = Router()


class ChannelManageState(StatesGroup):
    waiting_channel_input = State()
    waiting_mode = State()
    waiting_delete = State()
    waiting_required_channel = State()
    waiting_required_message = State()
    waiting_required_delete = State()


CHANNEL_REGEX = re.compile(r"(?:https?://)?t\.me/([a-zA-Z_]\w+)")


@router.message(SuperAdminFilter(), F.text == "🔙 رجوع")
async def back_from_sub_menus(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if data.get("in_required_channels"):
        await state.clear()
        await message.answer("📡 القنوات والأخبار:", reply_markup=await channels_keyboard())
        return
    if data.get("in_news_channel"):
        from services.news import load_templates
        from keyboards.reply import customize_news_keyboard
        await state.clear()
        await state.update_data(in_required_channels=True)
        templates = await load_templates()
        text = "📡 قوالب الأخبار الحالية:\n\n"
        for i, t in enumerate(templates, 1):
            text += f"{i}. {t}\n"
        await message.answer(text, reply_markup=customize_news_keyboard())
        return
    from handlers.admin import back_to_main
    await back_to_main(message, state)


@router.message(SuperAdminFilter(), F.text == "📰 تخصيص الأخبار")
async def customize_news_button(message: Message, state: FSMContext) -> None:
    from services.news import load_templates
    await state.clear()
    await state.update_data(in_required_channels=True)
    templates = await load_templates()
    text = "📡 قوالب الأخبار الحالية:\n\n"
    for i, t in enumerate(templates, 1):
        text += f"{i}. {t}\n"
    await message.answer(text, reply_markup=customize_news_keyboard())


@router.message(SuperAdminFilter(), F.text == "📡 القنوات والأخبار")
async def channels_menu(message: Message, state: FSMContext) -> None:
    logger.info(f"channels_menu called by {message.from_user.id}")
    await state.clear()
    await message.answer("📡 القنوات والأخبار:", reply_markup=await channels_keyboard())


@router.message(SuperAdminFilter(), F.text.startswith("🔒 القنوات الإجبارية"))
async def required_channels_menu(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.update_data(in_required_channels=True)
    await message.answer("🔒 إدارة القنوات الإجبارية:", reply_markup=required_channels_keyboard())


@router.message(SuperAdminFilter(), F.text == "➕ إضافة قناة إجبارية")
async def add_required_channel_start(message: Message, state: FSMContext) -> None:
    await state.set_state(ChannelManageState.waiting_required_channel)
    await message.answer(
        "✏️ أرسل رابط القناة أو المعرف (مثال: @qanat أو https://t.me/qanat):",
        reply_markup=cancel_keyboard(),
    )


@router.message(ChannelManageState.waiting_required_channel, SuperAdminFilter())
async def add_required_channel_link(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    match = re.search(r"(?:https?://)?t\.me/([a-zA-Z_]\w+)", text)
    chat_id = None
    channel_username = None
    if match:
        channel_username = match.group(1)
        chat_id = f"@{channel_username}"
    elif text.startswith("-100") or text.lstrip("-").isdigit():
        chat_id = text
    elif text.startswith("@"):
        channel_username = text[1:]
        chat_id = text
    else:
        await message.answer("❌ رابط غير صالح. أرسل رابط قناة أو معرف (@username) أو ID.")
        return

    try:
        chat = await message.bot.get_chat(chat_id)
        title = chat.title or channel_username or chat_id
        invite = await message.bot.create_chat_invite_link(chat_id, member_limit=0)
        await state.update_data(
            rc_chat_id=str(chat.id),
            rc_invite_link=invite.invite_link,
            rc_title=title,
        )
        await state.set_state(ChannelManageState.waiting_required_message)
        await message.answer(
            f"✅ تم التعرف على القناة: {title}\n\n"
            "✏️ أرسل الرسالة التي ستظهر للمستخدمين غير المشتركين (أو أرسل /skip لاستخدام رسالة افتراضية):",
            reply_markup=cancel_keyboard(),
        )
    except Exception as e:
        logger.exception("Failed to add required channel")
        await message.answer(
            f"❌ فشل. تأكد من إضافة البوت مشرفاً في القناة.\n\nالخطأ: {e}",
            reply_markup=await channels_keyboard(),
        )
        await state.clear()


@router.message(ChannelManageState.waiting_required_message, SuperAdminFilter())
async def add_required_channel_message(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    data = await state.get_data()
    custom_msg = None if text == "/skip" else text
    await add_required_channel(
        chat_id=data["rc_chat_id"],
        invite_link=data["rc_invite_link"],
        custom_message=custom_msg,
    )
    await message.answer(
        f"✅ تم إضافة القناة الإجبارية:\n"
        f"📌 {data['rc_title']}\n"
        f"🔗 {data['rc_invite_link']}\n\n"
        "جميع المستخدمين يجب أن يشتركوا فيها لاستخدام البوت.",
        reply_markup=await channels_keyboard(),
    )
    await state.clear()


@router.message(SuperAdminFilter(), F.text == "📋 القنوات الإجبارية")
async def list_required_channels(message: Message) -> None:
    channels = await get_all_required_channels()
    if not channels:
        await message.answer("❌ لا توجد قنوات إجبارية.", reply_markup=await channels_keyboard())
        return
    text = "🔒 القنوات الإجبارية:\n\n"
    for i, ch in enumerate(channels, 1):
        text += f"{i}. {ch.chat_id}\n   🔗 {ch.invite_link}\n"
        if ch.custom_message:
            msg_preview = ch.custom_message[:50].replace("\n", " ")
            text += f"   📝 {msg_preview}...\n"
        text += "\n"
    await message.answer(text, reply_markup=await channels_keyboard())


@router.message(SuperAdminFilter(), F.text == "➖ حذف قناة إجبارية")
async def delete_required_channel_start(message: Message, state: FSMContext) -> None:
    channels = await get_all_required_channels()
    if not channels:
        await message.answer("❌ لا توجد قنوات إجبارية للحذف.", reply_markup=await channels_keyboard())
        return
    text = "🔒 اختر القناة للحذف:\n\n"
    for i, ch in enumerate(channels, 1):
        text += f"{i}. {ch.chat_id}\n"
    await state.set_state(ChannelManageState.waiting_required_delete)
    await state.update_data(required_channels=channels)
    await message.answer(text + "\nأرسل رقم القناة:", reply_markup=cancel_keyboard())


@router.message(ChannelManageState.waiting_required_delete, SuperAdminFilter())
async def delete_required_channel_confirm(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    channels = data.get("required_channels", [])
    try:
        idx = int(message.text.strip()) - 1
        if idx < 0 or idx >= len(channels):
            raise ValueError
    except ValueError:
        await message.answer("❌ رقم غير صالح.")
        return
    ch = channels[idx]
    await remove_required_channel(ch.id)
    await message.answer(
        f"✅ تم حذف القناة الإجبارية: {ch.chat_id}",
        reply_markup=await channels_keyboard(),
    )
    await state.clear()


@router.message(SuperAdminFilter(), F.text == "📋 عرض القنوات")
async def list_channels(message: Message) -> None:
    channels = await get_all_monitored_channels()
    if not channels:
        await message.answer("❌ لا توجد قنوات مضافة.", reply_markup=await channels_keyboard())
        return
    text = "📡 القنوات المضافة:\n\n"
    for i, ch in enumerate(channels, 1):
        mode = "🤖 تلقائي" if ch.monitor_mode == "auto" else "🖐 يدوي"
        title = ch.title or "بدون اسم"
        uname = f"@{ch.channel_username}" if ch.channel_username else ch.channel_id
        text += f"{i}. {title}\n   {uname} | {mode}\n"
    await message.answer(text, reply_markup=await channels_keyboard())


@router.message(SuperAdminFilter(), F.text == "➕ إضافة قناة")
async def add_channel_start(message: Message, state: FSMContext) -> None:
    await state.set_state(ChannelManageState.waiting_channel_input)
    await message.answer(
        "✏️ أرسل رابط القناة أو المعرف (مثال: @qanat أو https://t.me/qanat أو -100123456):",
        reply_markup=cancel_keyboard(),
    )


@router.message(ChannelManageState.waiting_channel_input, SuperAdminFilter())
async def add_channel_process(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    channel_id = None
    channel_username = None

    match = CHANNEL_REGEX.search(text)
    if match:
        channel_username = match.group(1)
        channel_id = f"@{channel_username}"
    elif text.startswith("-100") or text.lstrip("-").isdigit():
        channel_id = text
    elif text.startswith("@"):
        channel_username = text[1:]
        channel_id = text
    else:
        await message.answer("❌ رابط غير صالح. أرسل رابط قناة أو معرف (@username) أو ID.")
        return

    existing = await get_monitored_channel_by_channel_id(channel_id)
    if existing:
        await message.answer("❌ هذه القناة مضافة بالفعل.", reply_markup=await channels_keyboard())
        await state.clear()
        return

    try:
        chat = await message.bot.get_chat(channel_id)
        title = chat.title or channel_username or channel_id
        if channel_username is None and hasattr(chat, "username") and chat.username:
            channel_username = chat.username
            channel_id = f"@{chat.username}"
    except Exception:
        title = channel_username or channel_id

    await state.update_data(
        channel_id=channel_id,
        channel_username=channel_username,
        title=title,
    )
    await state.set_state(ChannelManageState.waiting_mode)
    await message.answer(
        f"✅ تم التعرف على القناة: {title}\n"
        f"اختر وضع المراقبة:",
        reply_markup=channels_mode_keyboard(),
    )


@router.message(ChannelManageState.waiting_mode, SuperAdminFilter())
async def add_channel_mode(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    data = await state.get_data()

    if text == "🖐 يدوي":
        mc = await add_monitored_channel(
            channel_id=data["channel_id"],
            channel_username=data.get("channel_username"),
            title=data.get("title"),
            monitor_mode="manual",
        )
        await message.answer(
            f"✅ تم إضافة القناة: {data.get('title')}\n"
            f"الوضع: 🖐 يدوي\n"
            f"يمكنك الآن لصق روابطها في المواد.",
            reply_markup=await channels_keyboard(),
        )
        await state.clear()

    elif text == "🤖 تلقائي":
        mc = await add_monitored_channel(
            channel_id=data["channel_id"],
            channel_username=data.get("channel_username"),
            title=data.get("title"),
            monitor_mode="auto",
        )
        await message.answer(
            f"✅ تم إضافة القناة: {data.get('title')}\n"
            f"الوضع: 🤖 تلقائي\n"
            f"أول هاشتاق في المنشور = اسم المجلد\n"
            f"ثاني هاشتاق = عنوان المحتوى\n"
            f"بدون هاشتاقات = يتجاهله\n\n"
            f"⚠️ تأكد من إضافة البوت (@itjobTripoli_bot) "
            f"كمشرف في القناة حتى يستقبل المنشورات.",
            reply_markup=await channels_keyboard(),
        )
        await state.clear()
    else:
        await message.answer("❌ اختر 🖐 يدوي أو 🤖 تلقائي.")


@router.message(SuperAdminFilter(), F.text == "➖ حذف قناة")
async def delete_channel_start(message: Message, state: FSMContext) -> None:
    channels = await get_all_monitored_channels()
    if not channels:
        await message.answer("❌ لا توجد قنوات للحذف.", reply_markup=await channels_keyboard())
        return
    text = "📡 اختر القناة للحذف:\n\n"
    for i, ch in enumerate(channels, 1):
        uname = f"@{ch.channel_username}" if ch.channel_username else ch.channel_id
        text += f"{i}. {ch.title or uname}\n"
    await state.set_state(ChannelManageState.waiting_delete)
    await state.update_data(channels_list=channels)
    await message.answer(text + "\nأرسل رقم القناة:", reply_markup=cancel_keyboard())


@router.message(ChannelManageState.waiting_delete, SuperAdminFilter())
async def delete_channel_confirm(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    channels = data.get("channels_list", [])
    try:
        idx = int(message.text.strip()) - 1
        if idx < 0 or idx >= len(channels):
            raise ValueError
    except ValueError:
        await message.answer("❌ رقم غير صالح.")
        return
    ch = channels[idx]
    await remove_monitored_channel(ch.channel_id)
    await message.answer(
        f"✅ تم حذف القناة: {ch.title or ch.channel_id}",
        reply_markup=await channels_keyboard(),
    )
    await state.clear()


# ─── Auto-monitoring: channel posts (hashtag system) ───

HASHTAG_RE = re.compile(r"#(\w+)")

async def _resolve_folder(hashtag: str) -> int | None:
    roots = await get_folders(None)
    for f in roots:
        if f.name == hashtag:
            return f.id
    f = await add_folder(name=hashtag, parent_id=None)
    return f.id


@channel_router.channel_post()
async def auto_forward_channel_post(message: Message) -> None:
    ch_id = str(message.chat.id)
    mc = await get_monitored_channel_by_channel_id(ch_id)
    if not mc or mc.monitor_mode != "auto":
        return

    msg_id = message.message_id
    if message.media_group_id:
        return

    text = message.text or message.caption or ""
    tags = HASHTAG_RE.findall(text)

    if not tags:
        return

    folder_id = await _resolve_folder(tags[0])

    if len(tags) >= 2:
        title = tags[1]
    else:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        title = today

    try:
        ci = await add_content_item(folder_id=folder_id, title=title)
        link = f"https://t.me/{ch_id.replace('-100', 'c/').replace('@', '') if ch_id.startswith('-') else ch_id.replace('@', '')}/{msg_id}"
        uname = ch_id
        await add_content_link(ci.id, link, str(uname), msg_id)
        logger.info(f"Auto-saved from {ch_id} -> folder {folder_id} title={title}")
    except Exception as e:
        logger.error(f"Auto-forward failed from {ch_id}: {e}")


def channels_mode_keyboard():
    from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🖐 يدوي"), KeyboardButton(text="🤖 تلقائي")],
            [KeyboardButton(text="🔙 رجوع")],
        ],
        resize_keyboard=True,
    )
