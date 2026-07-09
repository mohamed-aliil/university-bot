import asyncio
import logging
import re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database.crud import (
    add_folder, remove_folder, get_folders, get_folder,
    add_content_item, remove_content_item, get_content_items,
    add_content_link, get_content_links,
    is_materials_active,
    get_monitored_channel_by_username, get_monitored_channel_by_channel_id,
)
from filters import AdminFilter

logger = logging.getLogger(__name__)
router = Router()

LINK_REGEX = re.compile(r"(?:https?://)?t\.me/(?:c/)?([a-zA-Z_]\w+|\d+)/(\d+)")


class MState(StatesGroup):
    browsing = State()
    add_folder = State()
    add_item_link = State()
    add_item_title = State()
    add_item_link_extra = State()
    deleting = State()


def build_kb(folders: list, items: list) -> ReplyKeyboardMarkup:
    kb = []
    row = []
    for f in folders:
        row.append(KeyboardButton(text=f.name))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    row = []
    for i in items:
        label = i.title or "محتوى"
        row.append(KeyboardButton(text=label))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([KeyboardButton(text="➕ إضافة مجلد"), KeyboardButton(text="📄 إضافة محتوى")])
    kb.append([KeyboardButton(text="➖ حذف"), KeyboardButton(text="🔙 رجوع")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


def student_kb(folders: list, items: list) -> ReplyKeyboardMarkup:
    kb = []
    row = []
    for f in folders:
        row.append(KeyboardButton(text=f.name))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    row = []
    for i in items:
        label = i.title or "محتوى"
        row.append(KeyboardButton(text=label))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([KeyboardButton(text="🔙 رجوع")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


async def render_admin(message: Message, folder_id: int = None) -> None:
    folders = await get_folders(folder_id)
    items = await get_content_items(folder_id) if folder_id else []
    if folder_id:
        f = await get_folder(folder_id)
        name = f.name if f else "?"
        msg = f"📍 {name}\n"
        if items:
            msg += "📄 المحتوى:\n" + "\n".join(f"  • {i.title or 'بدون عنوان'}" for i in items)
        await message.answer(msg, reply_markup=build_kb(folders, items))
    else:
        await message.answer("📚 المواد:", reply_markup=build_kb(folders, items))


@router.message(AdminFilter(), F.text == "📚 إعدادات المواد")
async def materials_settings(message: Message) -> None:
    from keyboards.reply import materials_settings_keyboard
    await message.answer("📚 إعدادات المواد:", reply_markup=materials_settings_keyboard())


@router.message(AdminFilter(), F.text.in_(["▶️ تشغيل المواد", "⏹ إيقاف المواد"]))
async def toggle_materials(message: Message) -> None:
    from database.crud import set_materials_active
    from keyboards.reply import materials_settings_keyboard
    new_state = "▶️ تشغيل المواد" in message.text
    set_materials_active(new_state)
    await message.answer("✅ تم تشغيل نظام المواد" if new_state else "✅ تم إيقاف نظام المواد", reply_markup=materials_settings_keyboard())


@router.message(AdminFilter(), F.text == "📚 إدارة المواد")
async def materials_entry(message: Message, state: FSMContext) -> None:
    await state.set_state(MState.browsing)
    await state.update_data(folder_id=None)
    await render_admin(message)


@router.message(AdminFilter(), F.text == "➕ إضافة مجلد")
async def add_folder_prompt(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.update_data(parent_id=data.get("folder_id"))
    await state.set_state(MState.add_folder)
    await message.answer("✏️ أرسل اسم المجلد الجديد:")


@router.message(MState.add_folder, AdminFilter())
async def add_folder_done(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not name:
        await message.answer("❌ الاسم فارغ.")
        return
    data = await state.get_data()
    await add_folder(name, data.get("parent_id"))
    await message.answer(f"✅ تم إضافة المجلد: {name}")
    await state.set_state(MState.browsing)
    await render_admin(message, data.get("parent_id"))


@router.message(AdminFilter(), F.text == "📄 إضافة محتوى")
async def add_item_prompt(message: Message, state: FSMContext) -> None:
    fid = (await state.get_data()).get("folder_id")
    if not fid:
        await message.answer("❌ ادخل مجلد أولاً.")
        return
    await state.set_state(MState.add_item_link)
    await message.answer("🔗 أرسل رابط منشور تيليغرام (أول رابط):")


@router.message(MState.add_item_link, AdminFilter())
async def add_item_link(message: Message, state: FSMContext) -> None:
    link = message.text.strip()
    match = LINK_REGEX.search(link)
    if not match:
        await message.answer("❌ رابط غير صالح.")
        return
    ch, msg = match.group(1), int(match.group(2))
    chat_id = f"@{ch}" if not ch.startswith("-") else int(f"-100{ch}")
    await state.update_data(link=link, channel_username=chat_id, channel_message_id=msg)

    mc = None
    if not ch.startswith("-"):
        mc = await get_monitored_channel_by_username(ch)
        if not mc:
            mc = await get_monitored_channel_by_channel_id(f"@{ch}")
    else:
        lookup_id = f"-100{ch}"
        mc = await get_monitored_channel_by_channel_id(lookup_id)

    if mc:
        try:
            fwd = await message.bot.forward_message(
                chat_id=message.chat.id,
                from_chat_id=chat_id,
                message_id=msg,
            )
            if fwd.photo or fwd.video or fwd.document or fwd.audio or fwd.voice or fwd.animation:
                await message.answer("✅ تم جلب الملف من القناة.")
            else:
                await fwd.delete()
                await message.answer("🔗 تم التعرف على القناة (لا يوجد ملف في هذه الرسالة).")
        except Exception as e:
            logger.warning(f"Could not fetch from monitored channel {chat_id}: {e}")

    await state.set_state(MState.add_item_title)
    await message.answer("✏️ أرسل عنوانًا (أو /skip):")


@router.message(MState.add_item_title, AdminFilter())
async def add_item_title(message: Message, state: FSMContext) -> None:
    title = None if message.text.strip() == "/skip" else message.text.strip()
    data = await state.get_data()
    ci = await add_content_item(folder_id=data["folder_id"], title=title)
    await add_content_link(ci.id, data["link"], str(data["channel_username"]), data["channel_message_id"])
    await state.update_data(content_item_id=ci.id)
    await state.set_state(MState.add_item_link_extra)
    await message.answer("✅ تم حفظ الرابط. أرسل رابط آخر أو /skip:")


@router.message(MState.add_item_link_extra, AdminFilter())
async def add_item_extra_link(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    if text == "/skip":
        data = await state.get_data()
        await message.answer("✅ تم إضافة المحتوى بجميع روابطه.")
        await state.set_state(MState.browsing)
        await render_admin(message, data["folder_id"])
        return
    match = LINK_REGEX.search(text)
    if not match:
        await message.answer(f"❌ الرابط غير معروف. تأكد أن الرابط صحيح:\n\n{text[:200]}")
        return
    ch, msg = match.group(1), int(match.group(2))
    chat_id = f"@{ch}" if not ch.startswith("-") else int(f"-100{ch}")
    data = await state.get_data()
    await add_content_link(data["content_item_id"], text, str(chat_id), msg)
    await message.answer("✅ تم حفظ الرابط. أرسل رابط آخر أو /skip:")


# ─── Delete by name ───

@router.message(AdminFilter(), F.text == "➖ حذف")
async def delete_prompt(message: Message, state: FSMContext) -> None:
    fid = (await state.get_data()).get("folder_id")
    folders = await get_folders(fid)
    items = await get_content_items(fid) if fid else []
    if not folders and not items:
        await message.answer("❌ لا يوجد شيء لحذفه هنا.")
        return
    await state.set_state(MState.deleting)
    msg = "🔻 أرسل اسم المجلد أو المحتوى الذي تريد حذفه:\n\n"
    if folders:
        msg += "📂 المجلدات:\n" + "\n".join(f"  • {f.name}" for f in folders) + "\n\n"
    if items:
        msg += "📄 المحتوى:\n" + "\n".join(f"  • {i.title or 'بدون عنوان'}" for i in items)
    await message.answer(msg)


@router.message(MState.deleting, AdminFilter())
async def delete_by_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not name:
        return
    fid = (await state.get_data()).get("folder_id")
    folders = await get_folders(fid)
    items = await get_content_items(fid) if fid else []
    folder_match = [f for f in folders if f.name == name]
    item_match = [i for i in items if (i.title or "محتوى") == name]
    if not folder_match and not item_match:
        await message.answer("❌ لا يوجد مجلد أو محتوى بهذا الاسم.")
        await state.set_state(MState.browsing)
        await render_admin(message, fid)
        return
    for f in folder_match:
        await remove_folder(f.id)
        await message.answer(f"✅ تم حذف المجلد: {f.name}")
    for i in item_match:
        await remove_content_item(i.id)
        await message.answer(f"✅ تم حذف المحتوى: {i.title or 'بدون عنوان'}")
    await state.set_state(MState.browsing)
    await render_admin(message, fid)


# ─── Admin folder navigation ───

@router.message(MState.browsing, AdminFilter())
async def admin_navigate(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    pid = (await state.get_data()).get("folder_id")
    folders = await get_folders(pid)
    items = await get_content_items(pid) if pid else []
    folder_match = [f for f in folders if f.name == text]
    item_match = [i for i in items if (i.title or "محتوى") == text]
    if folder_match:
        fid = folder_match[0].id
        await state.update_data(folder_id=fid)
        await render_admin(message, fid)
    elif item_match:
        await forward_item(message.from_user.id, item_match[0].id, message.bot)


async def forward_item(user_id: int, item_id: int, bot) -> None:
    from database.crud import get_content_links
    from database.database import async_session
    from database.models import ContentItem
    from sqlalchemy import select
    async with async_session() as s:
        r = await s.execute(select(ContentItem).where(ContentItem.id == item_id))
        item = r.scalar_one_or_none()
    if not item:
        await bot.send_message(chat_id=user_id, text="❌ المحتوى غير موجود.")
        return
    links = await get_content_links(item_id)
    if not links:
        await bot.send_message(chat_id=user_id, text="❌ لا توجد روابط لهذا المحتوى.")
        return
    async def forward_one(link):
        ch = link.channel_username
        mid = link.channel_message_id
        if ch and mid:
            try:
                fid = int(ch) if ch.lstrip("-").isdigit() else ch
                await bot.forward_message(chat_id=user_id, from_chat_id=fid, message_id=mid)
            except Exception as e:
                err = str(e)
                if "chat not found" in err.lower():
                    err += "\n⚠️ البوت ليس مشرفاً في هذه القناة أو القناة محذوفة."
                await bot.send_message(chat_id=user_id, text=f"❌ فشل التحويل: {link.link}\n{err}")
        else:
            await bot.send_message(chat_id=user_id, text=f"🔗 {link.link}")

    await asyncio.gather(*[forward_one(l) for l in links])
    logger.info(f"Forwarded {len(links)} links for content item {item_id} to user {user_id}")


# ─── Back ───

async def handle_back(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    fid = data.get("folder_id")
    if fid:
        f = await get_folder(fid)
        pid = f.parent_id if f else None
        await state.update_data(folder_id=pid)
        await render_admin(message, pid)
    else:
        from handlers.admin import admin_main_keyboard as main_kb
        await state.clear()
        await message.answer("🔝 القائمة الرئيسية", reply_markup=await main_kb(message.from_user.id))


# ─── Student ───

class SState(StatesGroup):
    browsing = State()


@router.message(F.text == "📚 المواد")
async def student_browse(message: Message, state: FSMContext) -> None:
    if not is_materials_active():
        await message.answer("❌ ميزة المواد متوقفة.")
        return
    folders = await get_folders()
    if not folders:
        await message.answer("❌ لا توجد مواد بعد.")
        return
    await state.set_state(SState.browsing)
    await state.update_data(folder_id=None)
    await message.answer("📚 المواد:", reply_markup=student_kb(folders, []))


@router.message(SState.browsing, F.text == "🔙 رجوع")
async def student_back(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    fid = data.get("folder_id")
    if fid:
        f = await get_folder(fid)
        pid = f.parent_id if f else None
        await state.update_data(folder_id=pid)
        if pid:
            subs = await get_folders(pid)
            items = await get_content_items(pid)
            pf = await get_folder(pid)
            await message.answer(f"📍 {pf.name}", reply_markup=student_kb(subs, items))
        else:
            folders = await get_folders()
            await message.answer("📚 المواد:", reply_markup=student_kb(folders, []))
    else:
        await state.clear()
        from keyboards.reply import main_keyboard
        await message.answer("🔝 القائمة الرئيسية", reply_markup=main_keyboard())


@router.message(SState.browsing)
async def student_navigate(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    pid = (await state.get_data()).get("folder_id")
    folders = await get_folders(pid)
    items = await get_content_items(pid) if pid is not None else []
    folder_match = [f for f in folders if f.name == text]
    item_match = [i for i in items if (i.title or "محتوى") == text]
    if folder_match:
        fid = folder_match[0].id
        await state.update_data(folder_id=fid)
        subs = await get_folders(fid)
        content = await get_content_items(fid)
        f = await get_folder(fid)
        await message.answer(f"📍 {f.name}", reply_markup=student_kb(subs, content))
    elif item_match:
        await forward_item(message.from_user.id, item_match[0].id, message.bot)
