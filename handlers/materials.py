import logging
import re
from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database.crud import (
    add_folder, remove_folder, get_folders, get_folder,
    add_content_item, remove_content_item, get_content_items, get_content_item,
    add_content_link, get_content_links, remove_content_link,
    update_content_item_title, rename_folder,
    is_materials_active,
    save_admin_action,
    is_admin_user,
)
from filters import AdminFilter
from config import settings
from keyboards.reply import main_keyboard, communication_keyboard

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
    add_item_title = State()
    deleting = State()
    edit_menu = State()
    rename_folder = State()


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
        rename_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="تعديل الاسم", callback_data=f"rename_folder:{folder_id}")]])
        await message.answer(msg, reply_markup=rename_kb)
        await message.answer("─" * 5, reply_markup=build_kb(folders, items))
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
    await state.set_state(MState.add_item_title)
    await message.answer("✏️ أرسل اسم المحتوى:")


@router.message(MState.add_item_title, AdminFilter())
async def add_item_title_save(message: Message, state: FSMContext) -> None:
    title = message.text.strip()
    if not title:
        await message.answer("❌ الاسم فارغ.")
        return
    data = await state.get_data()
    ci = await add_content_item(folder_id=data["folder_id"], title=title)
    await save_admin_action(message.from_user.id, message.from_user.full_name or "", "add_content", f"📄 {title}")
    await state.update_data(edit_item_id=ci.id, edit_item_title=title)
    await state.set_state(MState.edit_menu)
    header = f"📄 {title}\n{'═' * 15}\nلا توجد روابط.\n"
    await message.answer(header, reply_markup=content_edit_kb())


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
        await state.update_data(edit_item_id=item.id, edit_item_title=item.title, folder_id=pid)
        await state.set_state(MState.edit_menu)
        await message.answer(header, reply_markup=content_edit_kb())
    elif text == "🔙 رجوع":
        await handle_back(message, state)


@router.callback_query(AdminFilter(), F.data.startswith("rename_folder:"))
async def rename_folder_cb(callback: CallbackQuery, state: FSMContext) -> None:
    folder_id = int(callback.data.split(":")[1])
    f = await get_folder(folder_id)
    if not f:
        await callback.answer("❌ المجلد غير موجود.")
        return
    await state.update_data(rename_folder_id=folder_id)
    await state.set_state(MState.rename_folder)
    await callback.message.answer(f"✏️ تغيير اسم المجلد: {f.name}\nأرسل الاسم الجديد:", reply_markup=cancel_inline_kb())
    await callback.answer()


@router.message(MState.rename_folder, AdminFilter())
async def rename_folder_save(message: Message, state: FSMContext) -> None:
    new_name = message.text.strip()
    if not new_name:
        await message.answer("❌ الاسم فارغ.")
        return
    data = await state.get_data()
    folder_id = data.get("rename_folder_id")
    if not folder_id:
        await state.set_state(MState.browsing)
        await render_admin(message)
        return
    ok = await rename_folder(folder_id, new_name)
    if ok:
        await save_admin_action(message.from_user.id, message.from_user.full_name or "", "rename_folder", f"✏️ مجلد #{folder_id} ← {new_name}")
        await message.answer(f"✅ تم تغيير الاسم إلى: {new_name}")
    else:
        await message.answer("❌ المجلد غير موجود.")
    await state.set_state(MState.browsing)
    await render_admin(message, folder_id)


@router.callback_query(AdminFilter(), F.data.startswith("confirm_delete_item:"))
async def confirm_delete_item_cb(callback: CallbackQuery, state: FSMContext) -> None:
    item_id = int(callback.data.split(":")[1])
    item = await get_content_item(item_id)
    if not item:
        await callback.answer("❌ المحتوى غير موجود.", show_alert=True)
        return
    await remove_content_item(item_id)
    data = await state.get_data()
    await save_admin_action(callback.from_user.id, callback.from_user.full_name or "", "remove_content", f"🗑 محتوى #{item_id} ({item.title or 'بدون عنوان'})")
    await callback.message.edit_text(f"✅ تم حذف «{item.title or 'بدون عنوان'}».")
    await state.set_state(MState.browsing)
    await render_admin(callback.message, data.get("folder_id"))
    await callback.answer()


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
                return
            except Exception:
                pass
        try:
            m = LINK_REGEX.search(link.link)
            if m:
                ch2, mid2 = m.group(1), int(m.group(2))
                fid2 = int(ch2) if ch2.lstrip("-").isdigit() else f"@{ch2}"
                await bot.copy_message(chat_id=user_id, from_chat_id=fid2, message_id=mid2)
                return
        except Exception:
            pass
        await bot.send_message(chat_id=user_id, text=f"🔗 {link.link}", disable_web_page_preview=False)

    for l in links:
        await forward_one(l)
    logger.info(f"Forwarded {len(links)} links for content item {item_id} to user {user_id}")


# ─── Edit content (ReplyKeyboard with inline cancel) ───

def cancel_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ إلغاء", callback_data="edit:cancel")]])


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
        await message.answer("✏️ أرسل الاسم الجديد:", reply_markup=cancel_inline_kb())

    elif text == "➕ إضافة رابط":
        await state.set_state(EditContentState.add_link)
        await message.answer("🔗 أرسل رابط المنشور:", reply_markup=cancel_inline_kb())

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
        await message.answer(t, reply_markup=cancel_inline_kb())

    elif text == "🗑 حذف المحتوى":
        item = await get_content_item(item_id)
        name = item.title if item else "المحتوى"
        confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ نعم، احذف", callback_data=f"confirm_delete_item:{item_id}"),
             InlineKeyboardButton(text="❌ إلغاء", callback_data="edit:cancel")]
        ])
        await message.answer(f"🗑 هل أنت متأكد من حذف «{name}»؟", reply_markup=confirm_kb)

    elif text == "🔙 رجوع":
        await state.set_state(MState.browsing)
        await render_admin(message, data.get("folder_id"))

    else:
        await message.answer("❌ اختر من الأزرار.", reply_markup=content_edit_kb())


@router.callback_query(AdminFilter(), F.data == "edit:cancel")
async def edit_cancel_cb(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    item_id = data.get("edit_item_id")
    if not item_id:
        await state.set_state(MState.browsing)
        await render_admin(callback.message, data.get("folder_id"))
    else:
        await state.set_state(MState.edit_menu)
        await callback.message.answer("🔙 تم الإلغاء.", reply_markup=content_edit_kb())
    await callback.answer()


@router.message(EditContentState.edit_title, AdminFilter())
async def edit_title_save(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    item_id = data.get("edit_item_id")
    new_title = message.text.strip()
    if new_title == "🔙 رجوع":
        await state.set_state(MState.edit_menu)
        await message.answer("🔙 تم الإلغاء.", reply_markup=content_edit_kb())
        return
    await update_content_item_title(item_id, new_title)
    await save_admin_action(message.from_user.id, message.from_user.full_name or "", "edit_content_title", f"✏️ محتوى #{item_id} ← {new_title}")
    await state.update_data(edit_item_title=new_title)
    links = await get_content_links(item_id)
    t = f"✅ تم تحديث الاسم.\n📄 {new_title}\n{'═' * 15}\n"
    for idx, lnk in enumerate(links, 1):
        t += f"{idx}. {lnk.link}\n"
    await state.set_state(MState.edit_menu)
    await message.answer(t, reply_markup=content_edit_kb())


@router.message(EditContentState.add_link, AdminFilter())
async def edit_addlink_save(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    item_id = data.get("edit_item_id")
    text = message.text.strip()
    if text == "🔙 رجوع":
        await state.set_state(MState.edit_menu)
        await message.answer("🔙 تم الإلغاء.", reply_markup=content_edit_kb())
        return

    urls = [u.strip() for u in text.split("\n") if u.strip()]
    added = 0
    failed = 0
    for url in urls:
        match = LINK_REGEX.search(url)
        if not match:
            failed += 1
            continue
        ch, msg_id = match.group(1), int(match.group(2))
        chat_id = f"@{ch}" if not ch.startswith("-") else int(f"-100{ch}")
        try:
            fwd = await message.bot.forward_message(
                chat_id=message.chat.id,
                from_chat_id=chat_id,
                message_id=msg_id,
            )
            if not (fwd.photo or fwd.video or fwd.document or fwd.audio or fwd.voice or fwd.animation):
                await fwd.delete()
        except Exception:
            pass
        await add_content_link(item_id, url, str(chat_id), msg_id)
        await save_admin_action(message.from_user.id, message.from_user.full_name or "", "add_link_content", f"🔗 محتوى #{item_id}: {url[:80]}")
        added += 1

    t = f"✅ تمت إضافة {added} رابط" + ("." if not failed else f"، فشل {failed} رابط غير صالح.")
    if added:
        links = await get_content_links(item_id)
        t += "\n" + "\n".join(f"{idx}. {lnk.link}" for idx, lnk in enumerate(links, 1))
    await state.set_state(MState.edit_menu)
    await message.answer(t, reply_markup=content_edit_kb())


@router.message(EditContentState.delete_link, AdminFilter())
async def edit_dellink_save(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    item_id = data.get("edit_item_id")
    text = message.text.strip()
    if text == "🔙 رجوع":
        await state.set_state(MState.edit_menu)
        await message.answer("🔙 تم الإلغاء.", reply_markup=content_edit_kb())
        return
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
    await state.set_state(MState.browsing)
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


@router.message(F.text == "نَافِذَة الـمَوَادّ")
async def student_browse(message: Message, state: FSMContext) -> None:
    user = message.from_user
    if user.id in settings.admin_ids or await is_admin_user(user.id):
        from handlers.admin import admin_main_keyboard
        await state.clear()
        await message.answer("القائمة الرئيسية", reply_markup=await admin_main_keyboard(user.id))
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
    await message.answer("نَافِذَة الـمَوَادّ:", reply_markup=student_kb(folders, []))


@router.message(SState.browsing, F.text == "🔙 رجوع")
async def student_back(message: Message, state: FSMContext) -> None:
    try:
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
                return
            folders = await get_folders()
            await message.answer("نَافِذَة الـمَوَادّ:", reply_markup=student_kb(folders, []))
            return
        await state.clear()
        user_obj = message.from_user
        if user_obj.id in settings.admin_ids or await is_admin_user(user_obj.id):
            from handlers.admin import admin_main_keyboard
            await message.answer("🔝 القائمة الرئيسية", reply_markup=await admin_main_keyboard(user_obj.id))
        else:
            await message.answer("🔝 القائمة الرئيسية", reply_markup=main_keyboard())
    except Exception as e:
        logger.exception("student_back error: %s", e)
        await state.clear()
        user_obj = message.from_user
        if user_obj.id in settings.admin_ids or await is_admin_user(user_obj.id):
            from handlers.admin import admin_main_keyboard
            await message.answer("🔝 القائمة الرئيسية", reply_markup=await admin_main_keyboard(user_obj.id))
        else:
            await message.answer("🔝 القائمة الرئيسية", reply_markup=main_keyboard())


@router.message(SState.browsing)
async def student_navigate(message: Message, state: FSMContext) -> None:
    text = message.text.strip()

    if text in ("/start",):
        await state.clear()
        from handlers.start import _admin_kb
        from database.crud import get_or_create_user, is_admin_user
        user = message.from_user
        await get_or_create_user(
            user_id=user.id,
            full_name=user.full_name or "بدون اسم",
            username=user.username,
        )
        is_super = user.id in settings.admin_ids
        if is_super or await is_admin_user(user.id):
            await message.answer("مرحباً.", reply_markup=await _admin_kb(user.id))
        else:
            from keyboards.reply import main_keyboard
            await message.answer("مرحباً.", reply_markup=main_keyboard())
        return

    data = await state.get_data()
    pid = data.get("folder_id")
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
        try:
            from database.crud import save_or_replace_user_message
            await save_or_replace_user_message(user_id=message.from_user.id, content=text)
        except Exception:
            pass
        await forward_item(message.from_user.id, item_match[0].id, message.bot)
    else:
        user_obj = message.from_user
        if user_obj.id in settings.admin_ids or await is_admin_user(user_obj.id):
            await state.clear()
            from handlers.admin import admin_main_keyboard
            await message.answer("القائمة الرئيسية", reply_markup=await admin_main_keyboard(user_obj.id))
            return
        from keyboards.reply import main_keyboard
        from handlers.messages import ContactState
        if text in ("نَافِذَة التَّوَاصُل", "نَافِذَة الـمَوَادّ", "💬 التواصل", "⚙️ الإعدادات", "📩 الطلبات المرسلة", "نَافِذَة الـ AI"):
            await state.clear()
            if text == "نَافِذَة التَّوَاصُل":
                await state.set_state(ContactState.waiting_for_message)
                await message.answer(
                    "📬 نَافِذَة التَّوَاصُل\nأرسل رسالتك الآن وسيتم الرد عليك في أقرب وقت.",
                    reply_markup=communication_keyboard(),
                )
                return
            if text == "نَافِذَة الـمَوَادّ":
                from database.crud import is_materials_active
                if not is_materials_active():
                    await message.answer("المواد غير متاحة حاليًا.", reply_markup=main_keyboard())
                    return
                top_folders = await get_folders(None)
                await state.set_state(SState.browsing)
                await state.update_data(folder_id=None)
                await message.answer("نَافِذَة الـمَوَادّ:", reply_markup=student_kb(top_folders, []))
                return
            if await is_admin_user(message.from_user.id) or message.from_user.id in settings.admin_ids:
                from handlers.admin import settings_button, admin_main_keyboard
                await message.answer("القائمة الرئيسية", reply_markup=await admin_main_keyboard(message.from_user.id))
            else:
                await message.answer("القائمة الرئيسية", reply_markup=main_keyboard())
            return
        await message.answer(
            f"⚠️ '{text}' غير موجود. تم تحديث القائمة:",
            reply_markup=student_kb(folders, items),
        )
