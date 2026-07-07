import logging
import re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database.crud import (
    add_subject, remove_subject, get_all_subjects,
    add_section, remove_section, get_sections,
    add_content_type, remove_content_type, get_all_content_types,
    add_study_material, remove_study_material, get_study_materials,
    is_materials_active,
)
from filters import AdminFilter

logger = logging.getLogger(__name__)
router = Router()

LINK_REGEX = re.compile(r"https?://t\.me/(?:c/)?([a-zA-Z_]\w+|\d+)/(\d+)")


# ─── FSM ───

class MState(StatesGroup):
    browsing = State()
    add_subj = State()
    add_sec = State()
    add_ct = State()
    add_mat_link = State()
    add_mat_subj = State()
    add_mat_sec = State()
    add_mat_type = State()
    add_mat_title = State()
    del_confirm = State()


# ─── Helpers ───

def level_kb(level: str) -> ReplyKeyboardMarkup:
    buttons = {
        "subjects": ["➕ إضافة مادة", "➖ حذف مادة"],
        "sections": ["➕ إضافة قسم", "➖ حذف قسم"],
        "types":     ["➕ إضافة نوع محتوى", "➖ حذف نوع محتوى"],
        "materials": ["📄 إضافة شيت", "🗑 حذف شيت"],
    }
    return ReplyKeyboardMarkup(keyboard=[buttons[level], ["🔙 رجوع"]], resize_keyboard=True)


def _items_kb(items: list, callback_prefix: str, extra_buttons: list = None) -> InlineKeyboardMarkup:
    kb = [[InlineKeyboardButton(text=it.name, callback_data=f"{callback_prefix}:{it.id}")] for it in items]
    if extra_buttons:
        kb.append(extra_buttons)
    return InlineKeyboardMarkup(inline_keyboard=kb)


# ─── Settings toggle ───

@router.message(AdminFilter(), F.text.in_(["▶️ تشغيل المواد", "⏹ إيقاف المواد"]))
async def toggle_materials(message: Message) -> None:
    from database.crud import set_materials_active
    new_state = "▶️ تشغيل المواد" not in message.text
    set_materials_active(new_state)
    await message.answer("✅ تم تشغيل نظام المواد" if new_state else "✅ تم إيقاف نظام المواد")


# ─── Entry: 📚 إدارة المواد (admin) ───

@router.message(AdminFilter(), F.text == "📚 إدارة المواد")
async def materials_entry(message: Message, state: FSMContext) -> None:
    subjects = await get_all_subjects()
    await state.set_state(MState.browsing)
    await state.update_data(subject_id=None, section_id=None, type_id=None)
    if not subjects:
        await message.answer("📚 لا توجد مواد بعد.", reply_markup=level_kb("subjects"))
        return
    await message.answer("📚 اختر المادة:", reply_markup=_items_kb(subjects, "m_subj"))
    await message.answer("🔽 استخدم الأزرار أدناه:", reply_markup=level_kb("subjects"))


# ─── Navigation ───

@router.callback_query(MState.browsing, F.data.startswith("m_subj:"))
async def nav_sections(cq: CallbackQuery, state: FSMContext) -> None:
    subj_id = int(cq.data.split(":")[1])
    secs = await get_sections(subj_id)
    await state.update_data(subject_id=subj_id, section_id=None, type_id=None)
    if not secs:
        await cq.message.edit_text("📂 لا توجد أقسام.", reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="➕ إضافة قسم", callback_data="m_addsec")]]
        ))
    else:
        await cq.message.edit_text("📂 اختر القسم:", reply_markup=_items_kb(secs, "m_sec",
            [InlineKeyboardButton(text="➕ إضافة قسم", callback_data="m_addsec")]))
    await cq.answer()


@router.callback_query(MState.browsing, F.data.startswith("m_sec:"))
async def nav_types(cq: CallbackQuery, state: FSMContext) -> None:
    parts = cq.data.split(":")
    subj_id, sec_id = int(parts[1]), int(parts[2])
    types = await get_all_content_types()
    await state.update_data(section_id=sec_id, type_id=None)
    if not types:
        await cq.message.edit_text("📁 لا توجد أنواع محتوى.", reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="➕ إضافة نوع محتوى", callback_data="m_addct")]]
        ))
    else:
        await cq.message.edit_text("📁 اختر نوع المحتوى:", reply_markup=_items_kb(types, "m_type",
            [InlineKeyboardButton(text="➕ إضافة نوع محتوى", callback_data="m_addct")]))
    await cq.answer()


@router.callback_query(MState.browsing, F.data.startswith("m_type:"))
async def nav_materials(cq: CallbackQuery, state: FSMContext) -> None:
    parts = cq.data.split(":")
    subj_id, sec_id, type_id = int(parts[1]), int(parts[2]), int(parts[3])
    mats = await get_study_materials(subj_id, sec_id, type_id)
    await state.update_data(type_id=type_id)
    if not mats:
        await cq.message.edit_text("📄 لا توجد مواد.", reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="📄 إضافة شيت", callback_data="m_addmat")]]
        ))
    else:
        btns = []
        for m in mats:
            label = m.title or "عرض"
            btns.append([InlineKeyboardButton(text=f"📩 {label}", callback_data=f"m_view:{m.id}")])
        btns.append([InlineKeyboardButton(text="📄 إضافة شيت", callback_data="m_addmat")])
        await cq.message.edit_text("📄 المواد:", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))
    await cq.answer()


@router.callback_query(F.data == "m_addsec")
async def add_sec_from_inline(cq: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    subj_id = data.get("subject_id")
    if not subj_id:
        await cq.answer("❌ اختر مادة أولاً.", show_alert=True)
        return
    await state.set_state(MState.add_sec)
    await state.update_data(subj_id=subj_id)
    await cq.answer()
    await cq.message.answer("✏️ أرسل اسم القسم الجديد:")


@router.callback_query(F.data == "m_addct")
async def add_ct_from_inline(cq: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(MState.add_ct)
    await cq.answer()
    await cq.message.answer("✏️ أرسل اسم نوع المحتوى الجديد:")


@router.callback_query(F.data == "m_addmat")
async def add_mat_from_inline(cq: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("subject_id") or not data.get("section_id") or not data.get("type_id"):
        await cq.answer("❌ اختر مادة وقسم ونوع أولاً.", show_alert=True)
        return
    await state.set_state(MState.add_mat_link)
    await cq.answer()
    await cq.message.answer("🔗 أرسل رابط منشور تيليغرام (https://t.me/...):")


# ─── Show material ───

@router.callback_query(F.data.startswith("m_view:"))
async def show_material(cq: CallbackQuery) -> None:
    from database.database import async_session
    from database.models import StudyMaterial
    from sqlalchemy import select
    mid = int(cq.data.split(":")[1])
    async with async_session() as s:
        r = await s.execute(select(StudyMaterial).where(StudyMaterial.id == mid))
        mat = r.scalar_one_or_none()
    if not mat:
        await cq.answer("❌ غير موجود", show_alert=True)
        return
    await cq.answer()
    src = mat.channel_username
    if src and mat.channel_message_id:
        try:
            from bot import bot
            await bot.forward_message(chat_id=cq.from_user.id, from_chat_id=src, message_id=mat.channel_message_id)
        except Exception as e:
            await cq.message.answer(f"❌ تعذر التوجيه: {e}")
    else:
        await cq.message.answer(f"🔗 {mat.link}")


# ─── Student browsing ───

@router.message(F.text == "📚 المواد")
async def student_browse(message: Message) -> None:
    if not is_materials_active():
        await message.answer("❌ ميزة المواد متوقفة.")
        return
    subjects = await get_all_subjects()
    if not subjects:
        await message.answer("❌ لا توجد مواد.")
        return
    await message.answer("📚 اختر المادة:", reply_markup=_items_kb(subjects, "s_subj"))


@router.callback_query(F.data.startswith("s_subj:"))
async def s_nav_sections(cq: CallbackQuery) -> None:
    subj_id = int(cq.data.split(":")[1])
    secs = await get_sections(subj_id)
    if not secs:
        await cq.answer("❌ لا توجد أقسام.", show_alert=True)
        return
    await cq.message.edit_text("📂 اختر القسم:", reply_markup=_items_kb(secs, f"s_sec:{subj_id}",
        [InlineKeyboardButton(text="🔙 رجوع", callback_data="s_back")]))


@router.callback_query(F.data.startswith("s_sec:"))
async def s_nav_types(cq: CallbackQuery) -> None:
    parts = cq.data.split(":")
    subj_id, sec_id = int(parts[1]), int(parts[2])
    types = await get_all_content_types()
    if not types:
        await cq.answer("❌ لا توجد أنواع محتوى.", show_alert=True)
        return
    await cq.message.edit_text("📁 اختر نوع المحتوى:", reply_markup=_items_kb(types, f"s_type:{subj_id}:{sec_id}",
        [InlineKeyboardButton(text="🔙 رجوع", callback_data=f"s_back_sec:{subj_id}")]))


@router.callback_query(F.data.startswith("s_type:"))
async def s_show_materials(cq: CallbackQuery) -> None:
    parts = cq.data.split(":")
    subj_id, sec_id, type_id = int(parts[1]), int(parts[2]), int(parts[3])
    mats = await get_study_materials(subj_id, sec_id, type_id)
    if not mats:
        await cq.answer("❌ لا توجد مواد.", show_alert=True)
        return
    btns = []
    for m in mats:
        label = m.title or "عرض"
        btns.append([InlineKeyboardButton(text=f"📩 {label}", callback_data=f"s_view:{m.id}")])
    btns.append([InlineKeyboardButton(text="🔙 رجوع", callback_data=f"s_back_sec:{subj_id}")])
    await cq.message.edit_text("📄 المواد:", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))


@router.callback_query(F.data.startswith("s_view:"))
async def s_show_material(cq: CallbackQuery) -> None:
    from database.database import async_session
    from database.models import StudyMaterial
    from sqlalchemy import select
    mid = int(cq.data.split(":")[1])
    async with async_session() as s:
        r = await s.execute(select(StudyMaterial).where(StudyMaterial.id == mid))
        mat = r.scalar_one_or_none()
    if not mat:
        await cq.answer("❌ غير موجود", show_alert=True)
        return
    await cq.answer()
    src = mat.channel_username
    if src and mat.channel_message_id:
        try:
            from bot import bot
            await bot.forward_message(chat_id=cq.from_user.id, from_chat_id=src, message_id=mat.channel_message_id)
        except Exception as e:
            await cq.message.answer(f"❌ تعذر التوجيه: {e}")
    else:
        await cq.message.answer(f"🔗 {mat.link}")


@router.callback_query(F.data == "s_back")
async def s_back_to_subjects(cq: CallbackQuery) -> None:
    subjects = await get_all_subjects()
    if not subjects:
        await cq.message.edit_text("❌ لا توجد مواد.")
        return
    await cq.message.edit_text("📚 اختر المادة:", reply_markup=_items_kb(subjects, "s_subj"))


@router.callback_query(F.data.startswith("s_back_sec:"))
async def s_back_to_sections(cq: CallbackQuery) -> None:
    subj_id = int(cq.data.split(":")[1])
    secs = await get_sections(subj_id)
    if not secs:
        await cq.message.edit_text("📂 لا توجد أقسام.")
        return
    await cq.message.edit_text("📂 اختر القسم:", reply_markup=_items_kb(secs, f"s_sec:{subj_id}",
        [InlineKeyboardButton(text="🔙 رجوع", callback_data="s_back")]))


# ─── Add Subject ───

@router.message(MState.browsing, AdminFilter(), F.text == "➕ إضافة مادة")
async def add_subject_prompt(message: Message, state: FSMContext) -> None:
    await state.set_state(MState.add_subj)
    await message.answer("✏️ أرسل اسم المادة الجديدة:")


@router.message(MState.add_subj, AdminFilter())
async def add_subject_done(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not name:
        await message.answer("❌ الاسم فارغ.")
        return
    try:
        await add_subject(name)
        await message.answer(f"✅ تم إضافة {name}")
    except Exception:
        await message.answer("❌ موجودة بالفعل.")
    await state.set_state(MState.browsing)
    subjects = await get_all_subjects()
    if subjects:
        await message.answer("📚 اختر المادة:", reply_markup=_items_kb(subjects, "m_subj"))
    await message.answer(reply_markup=level_kb("subjects"))


# ─── Add Section ───

@router.message(MState.add_sec, AdminFilter())
async def add_section_done(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not name:
        await message.answer("❌ الاسم فارغ.")
        return
    data = await state.get_data()
    subj_id = data.get("subj_id") or data.get("subject_id")
    if not subj_id:
        await message.answer("❌ لا توجد مادة محددة.")
        await state.set_state(MState.browsing)
        return
    await add_section(subj_id, name)
    await message.answer(f"✅ تم إضافة القسم {name}")
    await state.set_state(MState.browsing)
    secs = await get_sections(subj_id)
    if secs:
        await message.answer("📂 اختر القسم:", reply_markup=_items_kb(secs, "m_sec",
            [InlineKeyboardButton(text="➕ إضافة قسم", callback_data="m_addsec")]))
    await message.answer(reply_markup=level_kb("sections"))


@router.message(AdminFilter(), F.text == "➕ إضافة قسم")
async def add_section_prompt(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    subj_id = data.get("subject_id")
    if not subj_id:
        await message.answer("❌ اختر مادة أولاً من القائمة أعلاه.")
        return
    await state.set_state(MState.add_sec)
    await message.answer("✏️ أرسل اسم القسم الجديد:")


# ─── Add Content Type ───

@router.message(MState.add_ct, AdminFilter())
async def add_ct_done(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not name:
        await message.answer("❌ الاسم فارغ.")
        return
    try:
        await add_content_type(name)
        await message.answer(f"✅ تم إضافة {name}")
    except Exception:
        await message.answer("❌ موجود بالفعل.")
    await state.set_state(MState.browsing)
    types = await get_all_content_types()
    if types:
        await message.answer("📁 اختر نوع المحتوى:", reply_markup=_items_kb(types, "m_type",
            [InlineKeyboardButton(text="➕ إضافة نوع محتوى", callback_data="m_addct")]))
    await message.answer(reply_markup=level_kb("types"))


@router.message(AdminFilter(), F.text == "➕ إضافة نوع محتوى")
async def add_ct_prompt(message: Message, state: FSMContext) -> None:
    await state.set_state(MState.add_ct)
    await message.answer("✏️ أرسل اسم نوع المحتوى الجديد:")


# ─── Add Material ───

@router.message(MState.add_mat_link, AdminFilter())
async def add_mat_link_received(message: Message, state: FSMContext) -> None:
    link = message.text.strip()
    match = LINK_REGEX.search(link)
    if not match:
        await message.answer("❌ رابط غير صالح. استخدم https://t.me/...")
        return
    channel_part, msg_id = match.group(1), int(match.group(2))
    chat_id = f"@{channel_part}" if not channel_part.startswith("-") else int(f"-100{channel_part}")
    await state.update_data(link=link, channel_username=chat_id, channel_message_id=msg_id)
    await state.set_state(MState.add_mat_title)
    await message.answer("✏️ أرسل عنوانًا (أو /skip):")


@router.message(MState.add_mat_title, AdminFilter())
async def add_mat_done(message: Message, state: FSMContext) -> None:
    title = None if message.text.strip() == "/skip" else message.text.strip()
    data = await state.get_data()
    await add_study_material(
        subject_id=data["subject_id"],
        section_id=data["section_id"],
        content_type_id=data["type_id"],
        link=data["link"],
        title=title,
        channel_username=str(data["channel_username"]),
        channel_message_id=data["channel_message_id"],
    )
    await message.answer("✅ تم إضافة المادة الدراسية.")
    await state.set_state(MState.browsing)
    subj_id, sec_id, type_id = data["subject_id"], data["section_id"], data["type_id"]
    mats = await get_study_materials(subj_id, sec_id, type_id)
    if mats:
        btns = [[InlineKeyboardButton(text=f"📩 {m.title or 'عرض'}", callback_data=f"m_view:{m.id}")] for m in mats]
        btns.append([InlineKeyboardButton(text="📄 إضافة شيت", callback_data="m_addmat")])
        await message.answer("📄 المواد:", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))
    await message.answer(reply_markup=level_kb("materials"))


@router.message(AdminFilter(), F.text == "📄 إضافة شيت")
async def add_mat_prompt(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("subject_id") or not data.get("section_id") or not data.get("type_id"):
        await message.answer("❌ اختر مادة → قسم → نوع محتوى أولاً من القائمة.")
        return
    await state.set_state(MState.add_mat_link)
    await message.answer("🔗 أرسل رابط منشور تيليغرام (https://t.me/...):")


# ─── Delete ───

@router.message(MState.browsing, AdminFilter(), F.text == "➖ حذف مادة")
async def del_subject_list(message: Message, state: FSMContext) -> None:
    subjects = await get_all_subjects()
    if not subjects:
        await message.answer("❌ لا توجد مواد.")
        return
    await state.set_state(MState.del_confirm)
    await state.update_data(del_type="subject")
    await message.answer("🔻 اختر المادة لحذفها:", reply_markup=_items_kb(subjects, "d_item"))


@router.message(MState.browsing, AdminFilter(), F.text == "➖ حذف قسم")
async def del_section_list(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    subj_id = data.get("subject_id")
    if not subj_id:
        await message.answer("❌ اختر مادة أولاً.")
        return
    secs = await get_sections(subj_id)
    if not secs:
        await message.answer("❌ لا توجد أقسام.")
        return
    await state.set_state(MState.del_confirm)
    await state.update_data(del_type="section")
    await message.answer("🔻 اختر القسم لحذفه:", reply_markup=_items_kb(secs, "d_item"))


@router.message(MState.browsing, AdminFilter(), F.text == "➖ حذف نوع محتوى")
async def del_type_list(message: Message, state: FSMContext) -> None:
    types = await get_all_content_types()
    if not types:
        await message.answer("❌ لا توجد أنواع محتوى.")
        return
    await state.set_state(MState.del_confirm)
    await state.update_data(del_type="content_type")
    await message.answer("🔻 اختر نوع المحتوى لحذفه:", reply_markup=_items_kb(types, "d_item"))


@router.message(MState.browsing, AdminFilter(), F.text == "🗑 حذف شيت")
async def del_material_list(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    subj_id, sec_id, type_id = data.get("subject_id"), data.get("section_id"), data.get("type_id")
    if not all([subj_id, sec_id, type_id]):
        await message.answer("❌ اختر مادة → قسم → نوع محتوى أولاً.")
        return
    mats = await get_study_materials(subj_id, sec_id, type_id)
    if not mats:
        await message.answer("❌ لا توجد مواد.")
        return
    await state.set_state(MState.del_confirm)
    await state.update_data(del_type="material")
    btns = [[InlineKeyboardButton(text=f"🗑 {m.title or 'بلا عنوان'}", callback_data=f"d_item:{m.id}")] for m in mats]
    await message.answer("🔻 اختر المادة لحذفها:", reply_markup=InlineKeyboardMarkup(inline_keyboard=btns))


@router.callback_query(MState.del_confirm, F.data.startswith("d_item:"))
async def del_confirm(cq: CallbackQuery, state: FSMContext) -> None:
    item_id = int(cq.data.split(":")[1])
    data = await state.get_data()
    del_type = data.get("del_type")
    ok = False
    if del_type == "subject":
        ok = await remove_subject(item_id)
    elif del_type == "section":
        ok = await remove_section(item_id)
    elif del_type == "content_type":
        ok = await remove_content_type(item_id)
    elif del_type == "material":
        ok = await remove_study_material(item_id)
    await cq.answer()
    await cq.message.edit_text("✅ تم الحذف." if ok else "❌ غير موجود.")
    await state.set_state(MState.browsing)
    await state.update_data(del_type=None)


# ─── Back ───

@router.message(AdminFilter(), F.text == "🔙 رجوع")
async def manage_back(message: Message, state: FSMContext) -> None:
    from handlers.admin import admin_main_keyboard as main_kb
    data = await state.get_data()
    subj_id = data.get("subject_id")
    sec_id = data.get("section_id")

    if sec_id:
        # go up to sections
        await state.update_data(section_id=None, type_id=None)
        secs = await get_sections(subj_id)
        if secs:
            await message.answer("📂 اختر القسم:", reply_markup=_items_kb(secs, "m_sec",
                [InlineKeyboardButton(text="➕ إضافة قسم", callback_data="m_addsec")]))
        await message.answer(reply_markup=level_kb("sections"))
    elif subj_id:
        # go up to subjects
        await state.update_data(subject_id=None)
        subjects = await get_all_subjects()
        if subjects:
            await message.answer("📚 اختر المادة:", reply_markup=_items_kb(subjects, "m_subj"))
        await message.answer(reply_markup=level_kb("subjects"))
    else:
        # go to main admin menu
        await state.clear()
        await message.answer("🔝 القائمة الرئيسية", reply_markup=await main_kb(message.from_user.id))
