import logging
import re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database.crud import (
    add_folder, remove_folder, get_folders, get_folder,
    add_content_item, remove_content_item, get_content_items,
    add_content_link, get_content_links,
    is_materials_active,
)
from filters import AdminFilter

logger = logging.getLogger(__name__)
router = Router()

LINK_REGEX = re.compile(r"https?://t\.me/(?:c/)?([a-zA-Z_]\w+|\d+)/(\d+)")


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
        row.append(KeyboardButton(text=f"📁 {f.name}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    row = []
    for i in items:
        label = i.title or "محتوى"
        row.append(KeyboardButton(text=f"📄 {label}"))
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
        row.append(KeyboardButton(text=f"📁 {f.name}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    row = []
    for i in items:
        label = i.title or "محتوى"
        row.append(KeyboardButton(text=f"📄 {label}"))
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
        msg = f"📂 {name}\n"
        if items:
            msg += "📄 المحتوى:\n" + "\n".join(f"  {i.title or 'بدون عنوان'}" for i in items)
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
    await state.set_state(MState.add_item_title)
    await message.answer("✏️ أرسل عنوانًا (أو أرسل /skip لعدم وضع عنوان):")


@router.message(MState.add_item_title, AdminFilter())
async def add_item_title(message: Message, state: FSMContext) -> None:
    title = None if message.text.strip() == "/skip" else message.text.strip()
    data = await state.get_data()
    ci = await add_content_item(folder_id=data["folder_id"], title=title)
    await add_content_link(ci.id, data["link"], str(data["channel_username"]), data["channel_message_id"])
    await state.update_data(content_item_id=ci.id, title=title)
    await state.set_state(MState.add_item_link_extra)
    await message.answer("✅ تم حفظ الرابط. أرسل رابط آخر أو /skip للإنهاء:")


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
        await message.answer("❌ رابط غير صالح. أرسل رابط صحيح أو /skip.")
        return
    ch, msg = match.group(1), int(match.group(2))
    chat_id = f"@{ch}" if not ch.startswith("-") else int(f"-100{ch}")
    data = await state.get_data()
    await add_content_link(data["content_item_id"], text, str(chat_id), msg)
    await message.answer("✅ تم حفظ الرابط. أرسل رابط آخر أو /skip للإنهاء:")


@router.message(AdminFilter(), F.text == "➖ حذف")
async def delete_start(message: Message, state: FSMContext) -> None:
    fid = (await state.get_data()).get("folder_id")
    folders = await get_folders(fid)
    items = await get_content_items(fid) if fid else []
    if not folders and not items:
        await message.answer("❌ لا يوجد شيء لحذفه.")
        return
    await state.set_state(MState.deleting)
    for f in folders:
        k = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🗑 حذف", callback_data=f"df:{f.id}")]])
        await message.answer(f"📁 {f.name}", reply_markup=k)
    for i in items:
        k = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🗑 حذف", callback_data=f"di:{i.id}")]])
        await message.answer(f"📄 {i.title or 'محتوى'}", reply_markup=k)
    await message.answer("🔻 اختر ما تريد حذفه:")


@router.callback_query(MState.deleting, F.data.startswith("df:"))
async def delete_folder(cq: CallbackQuery, state: FSMContext) -> None:
    ok = await remove_folder(int(cq.data.split(":")[1]))
    await cq.answer()
    await cq.message.edit_text("✅ تم حذف المجلد." if ok else "❌ غير موجود.")
    if ok:
        await state.set_state(MState.browsing)


@router.callback_query(MState.deleting, F.data.startswith("di:"))
async def delete_item(cq: CallbackQuery, state: FSMContext) -> None:
    ok = await remove_content_item(int(cq.data.split(":")[1]))
    await cq.answer()
    await cq.message.edit_text("✅ تم حذف المحتوى." if ok else "❌ غير موجود.")
    if ok:
        await state.set_state(MState.browsing)


async def forward_item(user_id: int, item_id: int, bot) -> None:
    from database.database import async_session
    from database.models import ContentItem
    from database.crud import get_content_links
    from sqlalchemy import select
    async with async_session() as s:
        r = await s.execute(select(ContentItem).where(ContentItem.id == item_id))
        item = r.scalar_one_or_none()
    if not item:
        return
    links = await get_content_links(item_id)
    if not links:
        return
    for link in links:
        if link.channel_username and link.channel_message_id:
            try:
                await bot.forward_message(chat_id=user_id, from_chat_id=link.channel_username, message_id=link.channel_message_id)
            except Exception:
                pass
        else:
            try:
                await bot.send_message(chat_id=user_id, text=f"🔗 {link.link}")
            except Exception:
                pass


# ─── Admin folder navigation via reply keyboard ───

@router.message(MState.browsing, AdminFilter(), F.text.startswith("📁 "))
async def admin_open_folder(message: Message, state: FSMContext) -> None:
    name = message.text[2:].strip()
    pid = (await state.get_data()).get("folder_id")
    folders = await get_folders(pid)
    match = [f for f in folders if f.name == name]
    if not match:
        return
    fid = match[0].id
    await state.update_data(folder_id=fid)
    await render_admin(message, fid)


@router.message(MState.browsing, AdminFilter(), F.text.startswith("📄 "))
async def admin_show_item(message: Message, state: FSMContext) -> None:
    label = message.text[2:].strip()
    pid = (await state.get_data()).get("folder_id")
    if not pid:
        return
    items = await get_content_items(pid)
    match = [i for i in items if (i.title or "محتوى") == label]
    if not match:
        return
    await forward_item(message.from_user.id, match[0].id, message.bot)


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


# ─── Student browsing (with FSM) ───

class SState(StatesGroup):
    browsing = State()


@router.message(F.text == "📚 المواد")
async def student_browse(message: Message, state: FSMContext = None) -> None:
    if state is None:
        from aiogram.fsm.context import FSMContextProxy
        # shouldn't happen, but just in case
        return
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


@router.message(SState.browsing, F.text.startswith("📁 "))
async def student_open_folder(message: Message, state: FSMContext) -> None:
    name = message.text[2:].strip()
    pid = (await state.get_data()).get("folder_id")
    folders = await get_folders(pid)
    match = [f for f in folders if f.name == name]
    if not match:
        return
    fid = match[0].id
    await state.update_data(folder_id=fid)
    subs = await get_folders(fid)
    items = await get_content_items(fid)
    await message.answer(f"📂 {match[0].name}", reply_markup=student_kb(subs, items))


@router.message(SState.browsing, F.text.startswith("📄 "))
async def student_show_item(message: Message, state: FSMContext) -> None:
    label = message.text[2:].strip()
    pid = (await state.get_data()).get("folder_id")
    if pid is None:
        return
    items = await get_content_items(pid)
    match = [i for i in items if (i.title or "محتوى") == label]
    if not match:
        return
    await forward_item(message.from_user.id, match[0].id, message.bot)


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
            await message.answer(f"📂 {pf.name}", reply_markup=student_kb(subs, items))
        else:
            folders = await get_folders()
            await message.answer("📚 المواد:", reply_markup=student_kb(folders, []))
    else:
        await state.clear()
        from keyboards.reply import main_keyboard
        await message.answer("🔝 القائمة الرئيسية", reply_markup=main_keyboard())
