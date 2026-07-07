import logging
import re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database.crud import (
    add_folder, remove_folder, get_folders, get_folder,
    add_content_item, remove_content_item, get_content_items,
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
    deleting = State()


def reply_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ إضافة مجلد"), KeyboardButton(text="📄 إضافة محتوى")],
            [KeyboardButton(text="➖ حذف")],
            [KeyboardButton(text="🔙 رجوع")],
        ],
        resize_keyboard=True,
    )


def folder_kb(folders: list, items: list, back_cb: str = None, prefix: str = "mf") -> InlineKeyboardMarkup:
    kb = []
    for f in folders:
        kb.append([InlineKeyboardButton(text=f"📁 {f.name}", callback_data=f"{prefix}:{f.id}")])
    for i in items:
        label = i.title or "📄 عرض"
        kb.append([InlineKeyboardButton(text=f"📩 {label}", callback_data=f"mi:{i.id}")])
    if back_cb:
        kb.append([InlineKeyboardButton(text="🔙 رجوع", callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=kb)


@router.message(AdminFilter(), F.text.in_(["▶️ تشغيل المواد", "⏹ إيقاف المواد"]))
async def toggle_materials(message: Message) -> None:
    from database.crud import set_materials_active
    new_state = "▶️ تشغيل المواد" not in message.text
    set_materials_active(new_state)
    await message.answer("✅ تم تشغيل نظام المواد" if new_state else "✅ تم إيقاف نظام المواد")


async def render_folder(message: Message, folder_id: int = None) -> None:
    folders = await get_folders(folder_id)
    items = await get_content_items(folder_id) if folder_id else []
    if not folders and not items:
        if folder_id:
            f = await get_folder(folder_id)
            name = f.name if f else "?"
            await message.answer(f"📂 {name}\nالمجلد فارغ.", reply_markup=folder_kb([], [], f"mup:{f.parent_id or 0}"))
        else:
            await message.answer("📚 لا توجد مجلدات بعد.", reply_markup=folder_kb([], []))
        return
    if folder_id:
        f = await get_folder(folder_id)
        name = f.name if f else "?"
        await message.answer(f"📂 {name}", reply_markup=folder_kb(folders, items, f"mup:{f.parent_id or 0}"))
    else:
        await message.answer("📚 المواد:", reply_markup=folder_kb(folders, items))


@router.message(AdminFilter(), F.text == "📚 إدارة المواد")
async def materials_entry(message: Message, state: FSMContext) -> None:
    await state.set_state(MState.browsing)
    await state.update_data(folder_id=None)
    folders = await get_folders()
    items = []
    if not folders:
        await message.answer("📚 لا توجد مجلدات بعد.", reply_markup=folder_kb([], []))
    else:
        await message.answer("📚 المواد:", reply_markup=folder_kb(folders, items))
    await message.answer("🔽 استخدم الأزرار:", reply_markup=reply_kb())


@router.callback_query(MState.browsing, F.data.startswith("mf:"))
async def open_folder(cq: CallbackQuery, state: FSMContext) -> None:
    fid = int(cq.data.split(":")[1])
    await state.update_data(folder_id=fid)
    folders = await get_folders(fid)
    items = await get_content_items(fid)
    f = await get_folder(fid)
    name = f.name if f else "?"
    await cq.message.edit_text(f"📂 {name}", reply_markup=folder_kb(folders, items, f"mup:{f.parent_id or 0}"))
    await cq.message.answer(reply_markup=reply_kb())
    await cq.answer()


@router.callback_query(MState.browsing, F.data.startswith("mup:"))
async def folder_up(cq: CallbackQuery, state: FSMContext) -> None:
    parent_id = int(cq.data.split(":")[1])
    await state.update_data(folder_id=parent_id if parent_id else None)
    if parent_id:
        folders = await get_folders(parent_id)
        items = await get_content_items(parent_id)
        f = await get_folder(parent_id)
        name = f.name if f else "?"
        await cq.message.edit_text(f"📂 {name}", reply_markup=folder_kb(folders, items, f"mup:{f.parent_id or 0}"))
    else:
        folders = await get_folders()
        items = []
        await cq.message.edit_text("📚 المواد:", reply_markup=folder_kb(folders, items))
    await cq.message.answer(reply_markup=reply_kb())
    await cq.answer()


@router.callback_query(F.data.startswith("mi:"))
async def show_item(cq: CallbackQuery) -> None:
    from database.database import async_session
    from database.models import ContentItem
    from sqlalchemy import select
    iid = int(cq.data.split(":")[1])
    async with async_session() as s:
        r = await s.execute(select(ContentItem).where(ContentItem.id == iid))
        item = r.scalar_one_or_none()
    if not item:
        await cq.answer("❌ غير موجود", show_alert=True)
        return
    await cq.answer()
    if item.channel_username and item.channel_message_id:
        try:
            from bot import bot
            await bot.forward_message(chat_id=cq.from_user.id, from_chat_id=item.channel_username, message_id=item.channel_message_id)
        except Exception as e:
            await cq.message.answer(f"❌ تعذر التوجيه: {e}")
    else:
        await cq.message.answer(f"🔗 {item.link}")


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
    pid = data.get("parent_id")
    await add_folder(name, pid)
    await message.answer(f"✅ تم إضافة المجلد: {name}")
    await state.set_state(MState.browsing)
    await render_folder(message, pid)
    await message.answer(reply_markup=reply_kb())


@router.message(AdminFilter(), F.text == "📄 إضافة محتوى")
async def add_item_prompt(message: Message, state: FSMContext) -> None:
    fid = (await state.get_data()).get("folder_id")
    if not fid:
        await message.answer("❌ ادخل مجلد أولاً (اختر مجلد من القائمة أعلاه).")
        return
    await state.set_state(MState.add_item_link)
    await message.answer("🔗 أرسل رابط منشور تيليغرام (https://t.me/...):")


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
    await message.answer("✏️ أرسل عنوانًا (أو /skip):")


@router.message(MState.add_item_title, AdminFilter())
async def add_item_done(message: Message, state: FSMContext) -> None:
    title = None if message.text.strip() == "/skip" else message.text.strip()
    data = await state.get_data()
    await add_content_item(
        folder_id=data["folder_id"],
        link=data["link"],
        title=title,
        channel_username=str(data["channel_username"]),
        channel_message_id=data["channel_message_id"],
    )
    await message.answer("✅ تم إضافة المحتوى.")
    await state.set_state(MState.browsing)
    await render_folder(message, data["folder_id"])
    await message.answer(reply_markup=reply_kb())


@router.message(AdminFilter(), F.text == "➖ حذف")
async def delete_start(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    fid = data.get("folder_id")
    folders = await get_folders(fid)
    items = await get_content_items(fid) if fid else []
    if not folders and not items:
        await message.answer("❌ لا يوجد شيء لحذفه هنا.")
        return
    await state.set_state(MState.deleting)
    for f in folders:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🗑 حذف", callback_data=f"df:{f.id}")]])
        await message.answer(f"📁 {f.name}", reply_markup=kb)
    for i in items:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🗑 حذف", callback_data=f"di:{i.id}")]])
        label = i.title or "محتوى"
        await message.answer(f"📄 {label}", reply_markup=kb)
    await message.answer("🔻 اختر ما تريد حذفه:", reply_markup=reply_kb())


@router.callback_query(MState.deleting, F.data.startswith("df:"))
async def delete_folder(cq: CallbackQuery, state: FSMContext) -> None:
    fid = int(cq.data.split(":")[1])
    ok = await remove_folder(fid)
    await cq.answer()
    await cq.message.edit_text("✅ تم حذف المجلد." if ok else "❌ غير موجود.")
    if ok:
        await state.set_state(MState.browsing)


@router.callback_query(MState.deleting, F.data.startswith("di:"))
async def delete_item(cq: CallbackQuery, state: FSMContext) -> None:
    iid = int(cq.data.split(":")[1])
    ok = await remove_content_item(iid)
    await cq.answer()
    await cq.message.edit_text("✅ تم حذف المحتوى." if ok else "❌ غير موجود.")
    if ok:
        await state.set_state(MState.browsing)


@router.message(F.text == "📚 المواد")
async def student_browse(message: Message) -> None:
    if not is_materials_active():
        await message.answer("❌ ميزة المواد متوقفة.")
        return
    folders = await get_folders()
    if not folders:
        await message.answer("❌ لا توجد مواد بعد.")
        return
    await message.answer("📚 المواد:", reply_markup=folder_kb(folders, [], prefix="sf"))


@router.callback_query(F.data.startswith("sf:"))
async def student_open(cq: CallbackQuery) -> None:
    fid = int(cq.data.split(":")[1])
    folders = await get_folders(fid)
    items = await get_content_items(fid)
    f = await get_folder(fid)
    name = f.name if f else "?"
    back = f"sup:{f.parent_id or 0}"
    await cq.message.edit_text(f"📂 {name}", reply_markup=folder_kb(folders, items, back, "sf"))
    await cq.answer()


@router.callback_query(F.data.startswith("sup:"))
async def student_up(cq: CallbackQuery) -> None:
    parent_id = int(cq.data.split(":")[1])
    if parent_id:
        folders = await get_folders(parent_id)
        items = await get_content_items(parent_id)
        f = await get_folder(parent_id)
        name = f.name if f else "?"
        back = f"sup:{f.parent_id or 0}"
        await cq.message.edit_text(f"📂 {name}", reply_markup=folder_kb(folders, items, back, "sf"))
    else:
        folders = await get_folders()
        await cq.message.edit_text("📚 المواد:", reply_markup=folder_kb(folders, [], prefix="sf"))
    await cq.answer()


async def handle_back(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    fid = data.get("folder_id")
    if fid:
        f = await get_folder(fid)
        pid = f.parent_id if f else None
        await state.update_data(folder_id=pid)
        if pid:
            folders = await get_folders(pid)
            items = await get_content_items(pid)
            pf = await get_folder(pid)
            name = pf.name if pf else "?"
            await message.answer(f"📂 {name}", reply_markup=folder_kb(folders, items, f"mup:{pf.parent_id or 0}"))
        else:
            folders = await get_folders()
            await message.answer("📚 المواد:", reply_markup=folder_kb(folders, []))
        await message.answer(reply_markup=reply_kb())
    else:
        from handlers.admin import admin_main_keyboard as main_kb
        await state.clear()
        await message.answer("🔝 القائمة الرئيسية", reply_markup=await main_kb(message.from_user.id))
