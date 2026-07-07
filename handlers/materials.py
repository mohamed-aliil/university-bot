import logging
import re
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from database.crud import (
    add_subject, remove_subject, get_all_subjects,
    add_section, remove_section, get_sections,
    add_content_type, remove_content_type, get_all_content_types,
    add_study_material, remove_study_material, get_study_materials,
    is_materials_active,
)
from filters import AdminFilter, SuperAdminFilter
from config import settings

logger = logging.getLogger(__name__)
router = Router()

LINK_REGEX = re.compile(r"https?://t\.me/(?:c/)?([a-zA-Z_]\w+|\d+)/(\d+)")


class AddSubjectState(StatesGroup):
    waiting_name = State()

class RemoveSubjectState(StatesGroup):
    waiting_confirm = State()

class AddSectionState(StatesGroup):
    waiting_subject = State()
    waiting_name = State()

class RemoveSectionState(StatesGroup):
    waiting_subject = State()

class AddContentTypeState(StatesGroup):
    waiting_name = State()

class RemoveContentTypeState(StatesGroup):
    waiting_confirm = State()

class AddMaterialState(StatesGroup):
    waiting_link = State()
    waiting_subject = State()
    waiting_section = State()
    waiting_type = State()
    waiting_title = State()

class RemoveMaterialState(StatesGroup):
    waiting_confirm = State()


@router.message(AdminFilter(), F.text.in_(["▶️ تشغيل المواد", "⏹ إيقاف المواد"]))
async def toggle_materials(message: Message) -> None:
    from database.crud import set_materials_active
    new_state = "▶️ تشغيل المواد" not in message.text
    set_materials_active(new_state)
    status = "✅ تم تشغيل نظام المواد" if new_state else "✅ تم إيقاف نظام المواد"
    await message.answer(status)


@router.message(AdminFilter(), F.text == "➕ إضافة مادة")
async def add_subject_start(message: Message, state: FSMContext) -> None:
    from keyboards.reply import cancel_keyboard
    await state.set_state(AddSubjectState.waiting_name)
    await message.answer("✏️ أرسل اسم المادة الجديدة:", reply_markup=cancel_keyboard())


@router.message(AddSubjectState.waiting_name, AdminFilter())
async def add_subject_save(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not name:
        await message.answer("❌ الاسم لا يمكن أن يكون فارغًا.")
        return
    try:
        await add_subject(name)
        await message.answer(f"✅ تم إضافة مادة: {name}")
    except Exception:
        await message.answer("❌ هذه المادة موجودة بالفعل.")
    await state.clear()


@router.message(AdminFilter(), F.text == "➖ حذف مادة")
async def remove_subject_start(message: Message, state: FSMContext) -> None:
    subjects = await get_all_subjects()
    if not subjects:
        await message.answer("❌ لا توجد مواد لحذفها.")
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=s.name, callback_data=f"rm_subj:{s.id}")]
            for s in subjects
        ]
    )
    await state.set_state(RemoveSubjectState.waiting_confirm)
    await message.answer("🔻 اختر المادة لحذفها:", reply_markup=kb)


@router.callback_query(RemoveSubjectState.waiting_confirm, F.data.startswith("rm_subj:"))
async def remove_subject_confirm(cq: CallbackQuery, state: FSMContext) -> None:
    subject_id = int(cq.data.split(":")[1])
    ok = await remove_subject(subject_id)
    await cq.answer()
    await cq.message.edit_text("✅ تم حذف المادة." if ok else "❌ غير موجودة.")
    await state.clear()


@router.message(AdminFilter(), F.text == "➕ إضافة قسم")
async def add_section_start(message: Message, state: FSMContext) -> None:
    subjects = await get_all_subjects()
    if not subjects:
        await message.answer("❌ لا توجد مواد. أضف مادة أولاً.")
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=s.name, callback_data=f"add_sec_subj:{s.id}")]
            for s in subjects
        ]
    )
    await state.set_state(AddSectionState.waiting_subject)
    await message.answer("🔻 اختر المادة لإضافة قسم فيها:", reply_markup=kb)


@router.callback_query(AddSectionState.waiting_subject, F.data.startswith("add_sec_subj:"))
async def add_section_subject_chosen(cq: CallbackQuery, state: FSMContext) -> None:
    subject_id = int(cq.data.split(":")[1])
    await state.update_data(subject_id=subject_id)
    await state.set_state(AddSectionState.waiting_name)
    await cq.answer()
    await cq.message.edit_text("✏️ أرسل اسم القسم الجديد (مثال: نصفي، نهائي):")


@router.message(AddSectionState.waiting_name, AdminFilter())
async def add_section_save(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not name:
        await message.answer("❌ الاسم لا يمكن أن يكون فارغًا.")
        return
    data = await state.get_data()
    await add_section(data["subject_id"], name)
    await message.answer(f"✅ تم إضافة القسم: {name}")
    await state.clear()


@router.message(AdminFilter(), F.text == "➖ حذف قسم")
async def remove_section_start(message: Message, state: FSMContext) -> None:
    subjects = await get_all_subjects()
    if not subjects:
        await message.answer("❌ لا توجد مواد.")
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=s.name, callback_data=f"rm_sec_subj:{s.id}")]
            for s in subjects
        ]
    )
    await state.set_state(RemoveSectionState.waiting_subject)
    await message.answer("🔻 اختر المادة:", reply_markup=kb)


@router.callback_query(RemoveSectionState.waiting_subject, F.data.startswith("rm_sec_subj:"))
async def remove_section_subject_chosen(cq: CallbackQuery, state: FSMContext) -> None:
    subject_id = int(cq.data.split(":")[1])
    sections = await get_sections(subject_id)
    if not sections:
        await cq.answer("❌ لا توجد أقسام في هذه المادة.", show_alert=True)
        return
    await state.update_data(subject_id=subject_id)
    await state.set_state(RemoveSubjectState.waiting_confirm)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=s.name, callback_data=f"rm_sec_del:{s.id}")]
            for s in sections
        ]
    )
    await cq.answer()
    await cq.message.edit_text("🔻 اختر القسم لحذفه:", reply_markup=kb)


@router.callback_query(RemoveSubjectState.waiting_confirm, F.data.startswith("rm_sec_del:"))
async def remove_section_confirm(cq: CallbackQuery, state: FSMContext) -> None:
    section_id = int(cq.data.split(":")[1])
    ok = await remove_section(section_id)
    await cq.answer()
    await cq.message.edit_text("✅ تم حذف القسم." if ok else "❌ غير موجود.")
    await state.clear()


@router.message(AdminFilter(), F.text == "➕ إضافة نوع محتوى")
async def add_content_type_start(message: Message, state: FSMContext) -> None:
    from keyboards.reply import cancel_keyboard
    await state.set_state(AddContentTypeState.waiting_name)
    await message.answer("✏️ أرسل اسم نوع المحتوى (مثال: شيتات، شروحات، ملخصات):", reply_markup=cancel_keyboard())


@router.message(AddContentTypeState.waiting_name, AdminFilter())
async def add_content_type_save(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if not name:
        await message.answer("❌ الاسم لا يمكن أن يكون فارغًا.")
        return
    try:
        await add_content_type(name)
        await message.answer(f"✅ تم إضافة نوع المحتوى: {name}")
    except Exception:
        await message.answer("❌ هذا النوع موجود بالفعل.")
    await state.clear()


@router.message(AdminFilter(), F.text == "➖ حذف نوع محتوى")
async def remove_content_type_start(message: Message, state: FSMContext) -> None:
    types = await get_all_content_types()
    if not types:
        await message.answer("❌ لا توجد أنواع محتوى.")
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t.name, callback_data=f"rm_ct:{t.id}")]
            for t in types
        ]
    )
    await state.set_state(RemoveContentTypeState.waiting_confirm)
    await message.answer("🔻 اختر نوع المحتوى لحذفه:", reply_markup=kb)


@router.callback_query(RemoveContentTypeState.waiting_confirm, F.data.startswith("rm_ct:"))
async def remove_content_type_confirm(cq: CallbackQuery, state: FSMContext) -> None:
    ct_id = int(cq.data.split(":")[1])
    ok = await remove_content_type(ct_id)
    await cq.answer()
    await cq.message.edit_text("✅ تم الحذف." if ok else "❌ غير موجود.")
    await state.clear()


@router.message(AdminFilter(), F.text == "📄 إضافة شيت/رابط")
async def add_material_start(message: Message, state: FSMContext) -> None:
    from keyboards.reply import cancel_keyboard
    subjects = await get_all_subjects()
    if not subjects:
        await message.answer("❌ لا توجد مواد. أضف مادة أولاً.")
        return
    types = await get_all_content_types()
    if not types:
        await message.answer("❌ لا توجد أنواع محتوى. أضف نوع محتوى أولاً.")
        return
    await state.set_state(AddMaterialState.waiting_link)
    await message.answer("🔗 أرسل رابط منشور تيليغرام (مثل: https://t.me/القناة/123):", reply_markup=cancel_keyboard())


@router.message(AddMaterialState.waiting_link, AdminFilter())
async def add_material_link(message: Message, state: FSMContext) -> None:
    link = message.text.strip()
    match = LINK_REGEX.search(link)
    if not match:
        await message.answer("❌ الرابط غير صالح. يجب أن يكون رابط منشور تيليغرام.")
        return
    channel_part, msg_id = match.group(1), int(match.group(2))
    channel_username = f"@{channel_part}" if not channel_part.startswith("-") else None
    if not channel_username:
        chat_id = int(f"-100{channel_part}")
    else:
        chat_id = channel_username

    await state.update_data(link=link, channel_username=chat_id, channel_message_id=msg_id)
    await state.set_state(AddMaterialState.waiting_subject)

    subjects = await get_all_subjects()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=s.name, callback_data=f"am_subj:{s.id}")]
            for s in subjects
        ]
    )
    await message.answer("📚 اختر المادة:", reply_markup=kb)


@router.callback_query(AddMaterialState.waiting_subject, F.data.startswith("am_subj:"))
async def add_material_subject_chosen(cq: CallbackQuery, state: FSMContext) -> None:
    subject_id = int(cq.data.split(":")[1])
    await state.update_data(subject_id=subject_id)
    await state.set_state(AddMaterialState.waiting_section)
    sections = await get_sections(subject_id)
    if not sections:
        await cq.answer("❌ لا توجد أقسام لهذه المادة.", show_alert=True)
        await state.clear()
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=s.name, callback_data=f"am_sec:{s.id}")]
            for s in sections
        ]
    )
    await cq.answer()
    await cq.message.edit_text("📂 اختر القسم:", reply_markup=kb)


@router.callback_query(AddMaterialState.waiting_section, F.data.startswith("am_sec:"))
async def add_material_section_chosen(cq: CallbackQuery, state: FSMContext) -> None:
    section_id = int(cq.data.split(":")[1])
    await state.update_data(section_id=section_id)
    await state.set_state(AddMaterialState.waiting_type)
    types = await get_all_content_types()
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t.name, callback_data=f"am_type:{t.id}")]
            for t in types
        ]
    )
    await cq.answer()
    await cq.message.edit_text("📁 اختر نوع المحتوى:", reply_markup=kb)


@router.callback_query(AddMaterialState.waiting_type, F.data.startswith("am_type:"))
async def add_material_type_chosen(cq: CallbackQuery, state: FSMContext) -> None:
    content_type_id = int(cq.data.split(":")[1])
    await state.update_data(content_type_id=content_type_id)
    await state.set_state(AddMaterialState.waiting_title)
    await cq.answer()
    await cq.message.edit_text("✏️ أرسل عنوانًا لهذه المادة (أو /skip لتخطي):")


@router.message(AddMaterialState.waiting_title, AdminFilter())
async def add_material_save(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    title = None if text == "/skip" else text
    data = await state.get_data()
    await add_study_material(
        subject_id=data["subject_id"],
        section_id=data["section_id"],
        content_type_id=data["content_type_id"],
        link=data["link"],
        title=title,
        channel_username=str(data["channel_username"]),
        channel_message_id=data["channel_message_id"],
    )
    await message.answer("✅ تم إضافة المادة الدراسية.")
    await state.clear()


@router.message(AdminFilter(), F.text == "🗑 حذف شيت")
async def remove_material_start(message: Message, state: FSMContext) -> None:
    from database.database import async_session
    from database.models import StudyMaterial, Subject, Section
    from sqlalchemy import select

    async with async_session() as session:
        result = await session.execute(select(StudyMaterial).order_by(StudyMaterial.created_at.desc()))
        materials = list(result.scalars().all())

    if not materials:
        await message.answer("❌ لا توجد مواد لحذفها.")
        return

    await state.set_state(RemoveMaterialState.waiting_confirm)

    async with async_session() as session:
        for m in materials:
            subj = await session.get(Subject, m.subject_id)
            sec = await session.get(Section, m.section_id)
            subj_name = subj.name if subj else "?"
            sec_name = sec.name if sec else "?"
            label = f"{subj_name} / {sec_name} / {m.title or 'بلا عنوان'}"
            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🗑 حذف", callback_data=f"rm_mat:{m.id}")]
                ]
            )
            await message.answer(label, reply_markup=kb)

    await message.answer("🔻 اضغط على حذف بجانب ما تريد حذفه.")


@router.callback_query(RemoveMaterialState.waiting_confirm, F.data.startswith("rm_mat:"))
async def remove_material_confirm(cq: CallbackQuery, state: FSMContext) -> None:
    material_id = int(cq.data.split(":")[1])
    ok = await remove_study_material(material_id)
    await cq.answer()
    await cq.message.edit_text("✅ تم الحذف." if ok else "❌ غير موجود.")
    await state.clear()


@router.message(AdminFilter(), F.text == "📋 عرض المواد الدراسية")
async def view_all_materials(message: Message) -> None:
    from database.database import async_session
    from database.models import StudyMaterial, Subject, Section, ContentType
    from sqlalchemy import select

    async with async_session() as session:
        result = await session.execute(
            select(StudyMaterial).order_by(StudyMaterial.created_at.desc())
        )
        materials = list(result.scalars().all())

    if not materials:
        await message.answer("❌ لا توجد مواد مضافة.")
        return

    lines = ["📋 جميع المواد الدراسية:\n"]
    async with async_session() as session:
        for m in materials:
            subj = await session.get(Subject, m.subject_id)
            sec = await session.get(Section, m.section_id)
            ct = await session.get(ContentType, m.content_type_id)
            subj_name = subj.name if subj else "?"
            sec_name = sec.name if sec else "?"
            ct_name = ct.name if ct else "?"
            line = f"• {subj_name} / {sec_name} / {ct_name}"
            if m.title:
                line += f" — {m.title}"
            lines.append(line)

    await message.answer("\n".join(lines)[:4000])


# ─── Student Browsing ───

@router.message(F.text == "📚 المواد")
async def materials_browse(message: Message) -> None:
    if not is_materials_active():
        await message.answer("❌ ميزة المواد الدراسية متوقفة حاليًا.")
        return
    subjects = await get_all_subjects()
    if not subjects:
        await message.answer("❌ لا توجد مواد بعد.")
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=s.name, callback_data=f"mat_subj:{s.id}")]
            for s in subjects
        ]
    )
    await message.answer("📚 اختر المادة:", reply_markup=kb)


@router.callback_query(F.data.startswith("mat_subj:"))
async def browse_subject(cq: CallbackQuery) -> None:
    subject_id = int(cq.data.split(":")[1])
    sections = await get_sections(subject_id)
    if not sections:
        await cq.answer("❌ لا توجد أقسام لهذه المادة.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=s.name, callback_data=f"mat_sec:{subject_id}:{s.id}")]
            for s in sections
        ] + [[InlineKeyboardButton(text="🔙 رجوع", callback_data="mat_back_subjects")]]
    )
    await cq.message.edit_text("📂 اختر القسم:", reply_markup=kb)


@router.callback_query(F.data.startswith("mat_sec:"))
async def browse_section(cq: CallbackQuery) -> None:
    parts = cq.data.split(":")
    subject_id = int(parts[1])
    section_id = int(parts[2])
    types = await get_all_content_types()
    if not types:
        await cq.answer("❌ لا توجد أنواع محتوى.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t.name, callback_data=f"mat_type:{subject_id}:{section_id}:{t.id}")]
            for t in types
        ] + [[InlineKeyboardButton(text="🔙 رجوع", callback_data=f"mat_back_sections:{subject_id}")]]
    )
    await cq.message.edit_text("📁 اختر نوع المحتوى:", reply_markup=kb)


@router.callback_query(F.data.startswith("mat_type:"))
async def browse_materials(cq: CallbackQuery) -> None:
    parts = cq.data.split(":")
    subject_id = int(parts[1])
    section_id = int(parts[2])
    content_type_id = int(parts[3])
    materials = await get_study_materials(subject_id, section_id, content_type_id)
    if not materials:
        await cq.answer("❌ لا توجد مواد دراسية هنا.", show_alert=True)
        return
    text = "📄 المواد الدراسية:\n"
    kb_buttons = []
    for m in materials:
        label = m.title or "عرض"
        text += f"\n🔹 {label}"
        kb_buttons.append(
            [InlineKeyboardButton(text=f"📩 {label}", callback_data=f"mat_view:{m.id}")]
        )
    kb_buttons.append([InlineKeyboardButton(text="🔙 رجوع", callback_data=f"mat_back_sections:{subject_id}")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    await cq.message.edit_text(text, reply_markup=kb)


@router.callback_query(F.data.startswith("mat_view:"))
async def show_material(cq: CallbackQuery) -> None:
    from database.database import async_session
    from database.models import StudyMaterial
    from sqlalchemy import select
    material_id = int(cq.data.split(":")[1])
    async with async_session() as session:
        result = await session.execute(select(StudyMaterial).where(StudyMaterial.id == material_id))
        mat = result.scalar_one_or_none()
    if not mat:
        await cq.answer("❌ غير موجود", show_alert=True)
        return
    await cq.answer()
    from_chat = mat.channel_username
    if not from_chat or not from_chat.startswith("@"):
        from_chat = f"@{from_chat}" if from_chat and not from_chat.startswith("-") else from_chat
    if from_chat and mat.channel_message_id:
        try:
            from bot import bot
            await bot.forward_message(
                chat_id=cq.from_user.id,
                from_chat_id=from_chat,
                message_id=mat.channel_message_id,
            )
        except Exception as e:
            await cq.message.answer(f"❌ تعذر إعادة التوجيه:\n{e}")
    else:
        await cq.message.answer(f"🔗 الرابط:\n{mat.link}")


@router.callback_query(F.data == "mat_back_subjects")
async def back_to_subjects(cq: CallbackQuery) -> None:
    subjects = await get_all_subjects()
    if not subjects:
        await cq.message.edit_text("❌ لا توجد مواد بعد.")
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=s.name, callback_data=f"mat_subj:{s.id}")]
            for s in subjects
        ]
    )
    await cq.message.edit_text("📚 اختر المادة:", reply_markup=kb)


@router.callback_query(F.data.startswith("mat_back_sections:"))
async def back_to_sections(cq: CallbackQuery) -> None:
    subject_id = int(cq.data.split(":")[1])
    sections = await get_sections(subject_id)
    if not sections:
        await cq.answer("❌ لا توجد أقسام.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=s.name, callback_data=f"mat_sec:{subject_id}:{s.id}")]
            for s in sections
        ] + [[InlineKeyboardButton(text="🔙 رجوع", callback_data="mat_back_subjects")]]
    )
    await cq.message.edit_text("📂 اختر القسم:", reply_markup=kb)
