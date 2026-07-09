import asyncio
import logging
import re
from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database.crud import (
    add_folder, remove_folder, get_folders, get_folder,
    add_content_item, remove_content_item, get_content_items,
    add_content_link, get_content_links, remove_content_link,
    update_content_item_title,
    is_materials_active,
    save_admin_action,
)
from filters import AdminFilter

logger = logging.getLogger(__name__)
router = Router()

LINK_REGEX = re.compile(r"(?:https?://)?t\.me/(?:c/)?([a-zA-Z_]\w+|\d+)/(\d+)")

def content_edit_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✏️ تغيير الاسم"), KeyboardButton(text="➕ إضافة رابط")],
            [KeyboardButton(text="➖ حذف رابط"), KeyboardButton(text="🗑 حذف المحتوى")],
            [KeyboardButton(text="🔙 رجوع")],
        ],
        resize_keyboard=True,
    )


class MState(StatesGroup):
    browsing = State()
    add_folder = State()
    add_item_link = State()
    add_item_title = State()
    add_item_link_extra = State()
    deleting = State()
    edit_menu = State()


class EditContentState(StatesGroup):
    edit_title = State()
    add_link = State()
    add_link_extra = State()
    delete_link = State()


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
    pid = data.get("parent_id")
    await add_folder(name=name, parent_id=pid)
    await save_admin_action(message.from_user.id, message.from_user.full_name or "", "add_folder", f"📂 {name}")
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
        logger.warning(f"Could not forward {chat_id}/{msg}: {e}")

    await state.set_state(MState.add_item_title)
    await message.answer("✏️ أرسل عنوانًا (أو /skip):")


@router.message(MState.add_item_title, AdminFilter())
async def add_item_title(message: Message, state: FSMContext) -> None:
    title = None if message.text.strip() == "/skip" else message.text.strip()
    data = await state.get_data()
    ci = await add_content_item(folder_id=data["folder_id"], title=title)
    await add_content_link(ci.id, data["link"], str(data["channel_username"]), data["channel_message_id"])
    await save_admin_action(message.from_user.id, message.from_user.full_name or "", "add_content", f"📄 {title or 'بدون عنوان'} في مجلد {data['folder_id']}")
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
        await save_admin_action(message.from_user.id, message.from_user.full_name or "", "remove_folder", f"📂 {f.name}")
        await message.answer(f"✅ تم حذف المجلد: {f.name}")
    for i in item_match:
        await remove_content_item(i.id)
        await save_admin_action(message.from_user.id, message.from_user.full_name or "", "remove_content", f"📄 {i.title or 'بدون عنوان'}")
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
        item = item_match[0]
        links = await get_content_links(item.id)
        header = f"📄 {item.title or 'بدون عنوان'}\n{'═' * 15}\n"
        if links:
            for idx, lnk in enumerate(links, 1):
                header += f"{idx}. {lnk.link}\n"
        else:
            header += "لا توجد روابط.\n"
        await state.update_data(edit_item_id=item.id, folder_id=pid)
        await state.set_state(MState.edit_menu)
        await message.answer(header, reply_markup=content_edit_kb())


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
                await bot.copy_message(chat_id=user_id, from_chat_id=fid, message_id=mid)
            except Exception as e:
                err = str(e)
                if "chat not found" in err.lower():
                    await bot.send_message(chat_id=user_id, text=f"⚠️ البوت لا يستطيع الوصول للقناة.\n🔗 {link.link}")
                else:
                    await bot.send_message(chat_id=user_id, text=f"🔗 {link.link}")
        else:
            await bot.send_message(chat_id=user_id, text=f"🔗 {link.link}")

    await asyncio.gather(*[forward_one(l) for l in links])
    logger.info(f"Forwarded {len(links)} links for content item {item_id} to user {user_id}")


# ─── Edit content (ReplyKeyboard) ───

@router.message(MState.edit_menu, AdminFilter())
async def edit_menu_handler(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    item_id = data.get("edit_item_id")
    if not item_id:
        await state.set_state(MState.browsing)
        await render_admin(message, data.get("folder_id"))
        return
    text = message.text.strip()

    if text == "✏️ تغيير الاسم":
        await state.set_state(EditContentState.edit_title)
        await message.answer("✏️ أرسل الاسم الجديد:")

    elif text == "➕ إضافة رابط":
        await state.set_state(EditContentState.add_link)
        await message.answer("🔗 أرسل رابط المنشور:")

    elif text == "➖ حذف رابط":
        links = await get_content_links(item_id)
        if not links:
            await message.answer("❌ لا توجد روابط للحذف.", reply_markup=content_edit_kb())
            return
        t = "📋 الروابط:\n"
        for idx, lnk in enumerate(links, 1):
            t += f"{idx}. {lnk.link}\n"
        t += "\nأرسل رقم الرابط لحذفه:"
        await state.set_state(EditContentState.delete_link)
        await message.answer(t)

    elif text == "🗑 حذف المحتوى":
        await remove_content_item(item_id)
        await save_admin_action(message.from_user.id, message.from_user.full_name or "", "remove_content", f"🗑 محتوى #{item_id}")
        await message.answer("✅ تم حذف المحتوى.")
        await state.set_state(MState.browsing)
        await render_admin(message, data.get("folder_id"))

    elif text == "🔙 رجوع":
        await state.set_state(MState.browsing)
        await render_admin(message, data.get("folder_id"))

    else:
        await message.answer("❌ اختر من الأزرار.", reply_markup=content_edit_kb())


@router.message(EditContentState.edit_title, AdminFilter())
async def edit_title_save(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    item_id = data.get("edit_item_id")
    await update_content_item_title(item_id, message.text.strip())
    await save_admin_action(message.from_user.id, message.from_user.full_name or "", "edit_content_title", f"✏️ محتوى #{item_id} ← {message.text.strip()}")
    links = await get_content_links(item_id)
    t = f"✅ تم تحديث الاسم.\n📄 {message.text.strip()}\n{'═' * 15}\n"
    for idx, lnk in enumerate(links, 1):
        t += f"{idx}. {lnk.link}\n"
    await state.set_state(MState.edit_menu)
    await message.answer(t, reply_markup=content_edit_kb())


@router.message(EditContentState.add_link, AdminFilter())
async def edit_addlink_save(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    item_id = data.get("edit_item_id")
    text = message.text.strip()
    match = LINK_REGEX.search(text)
    if not match:
        await message.answer("❌ رابط غير صالح.")
        return
    ch, msg = match.group(1), int(match.group(2))
    chat_id = f"@{ch}" if not ch.startswith("-") else int(f"-100{ch}")
    await add_content_link(item_id, text, str(chat_id), msg)
    await save_admin_action(message.from_user.id, message.from_user.full_name or "", "add_link_content", f"🔗 محتوى #{item_id}: {text[:80]}")
    links = await get_content_links(item_id)
    t = "✅ تم إضافة الرابط.\n"
    for idx, lnk in enumerate(links, 1):
        t += f"{idx}. {lnk.link}\n"
    await state.set_state(MState.edit_menu)
    await message.answer(t, reply_markup=content_edit_kb())


@router.message(EditContentState.delete_link, AdminFilter())
async def edit_dellink_save(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    item_id = data.get("edit_item_id")
    links = await get_content_links(item_id)
    try:
        idx = int(message.text.strip()) - 1
        if idx < 0 or idx >= len(links):
            raise ValueError
    except ValueError:
        await message.answer("❌ رقم غير صالح.")
        return
    await remove_content_link(links[idx].id)
    await save_admin_action(message.from_user.id, message.from_user.full_name or "", "remove_link_content", f"➖ محتوى #{item_id}: {links[idx].link[:80]}")
    links = await get_content_links(item_id)
    t = "✅ تم حذف الرابط.\n"
    for idx, lnk in enumerate(links, 1):
        t += f"{idx}. {lnk.link}\n"
    await state.set_state(MState.edit_menu)
    await message.answer(t, reply_markup=content_edit_kb())


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
