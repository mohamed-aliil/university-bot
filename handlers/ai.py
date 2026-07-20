import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from filters import AdminFilter
from database.crud import add_qa, delete_qa, get_all_qa, save_pdf_context, delete_pdf_context, get_all_pdfs, get_folder, get_content_items, get_folders
from keyboards.reply import ai_admin_keyboard, ai_user_keyboard, main_keyboard, cancel_keyboard
from services.gemini import call_gemini, is_college_question, find_best_qa

logger = logging.getLogger(__name__)
router = Router()


class AIState(StatesGroup):
    waiting_for_question = State()


class AIAdminState(StatesGroup):
    waiting_question = State()
    waiting_answer = State()
    waiting_delete_id = State()
    waiting_pdf_name = State()
    waiting_pdf_file = State()


@router.message(AdminFilter(), F.text == "🤖 الذكاء الاصطناعي")
async def ai_admin_panel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🤖 إدارة الذكاء الاصطناعي:", reply_markup=ai_admin_keyboard())


@router.message(AdminFilter(), F.text == "➕ إضافة سؤال/جواب")
async def ai_add_qa_start(message: Message, state: FSMContext) -> None:
    await state.set_state(AIAdminState.waiting_question)
    await message.answer("✏️ أرسل السؤال:", reply_markup=cancel_keyboard())


@router.message(AIAdminState.waiting_question, AdminFilter())
async def ai_add_qa_question(message: Message, state: FSMContext) -> None:
    await state.update_data(question=message.text)
    await state.set_state(AIAdminState.waiting_answer)
    await message.answer("✏️ أرسل الجواب:", reply_markup=cancel_keyboard())


@router.message(AIAdminState.waiting_answer, AdminFilter())
async def ai_add_qa_answer(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    q = data["question"]
    a = message.text
    qa = await add_qa(q, a)
    await state.clear()
    await message.answer(f"✅ تم إضافة السؤال/جواب (رقم {qa.id}):\n\n📌 {q}\n💬 {a}", reply_markup=ai_admin_keyboard())


@router.message(AdminFilter(), F.text == "➖ حذف سؤال/جواب")
async def ai_delete_qa_start(message: Message, state: FSMContext) -> None:
    qa_list = await get_all_qa()
    if not qa_list:
        await message.answer("❌ لا توجد أسئلة.", reply_markup=ai_admin_keyboard())
        return
    lines = []
    for qa in qa_list:
        q_short = qa.question[:40]
        lines.append(f"🔹 {qa.id}: {q_short}")
    await state.set_state(AIAdminState.waiting_delete_id)
    await message.answer(
        "📋 الأسئلة الموجودة:\n\n" + "\n".join(lines[-20:]) + "\n\nأرسل الرقم للحذف:",
        reply_markup=cancel_keyboard(),
    )


@router.message(AIAdminState.waiting_delete_id, AdminFilter())
async def ai_delete_qa_confirm(message: Message, state: FSMContext) -> None:
    try:
        qa_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ رقم غير صالح.")
        return
    ok = await delete_qa(qa_id)
    await state.clear()
    if ok:
        await message.answer("✅ تم حذف السؤال.", reply_markup=ai_admin_keyboard())
    else:
        await message.answer("❌ الرقم غير موجود.", reply_markup=ai_admin_keyboard())


@router.message(AdminFilter(), F.text == "📋 عرض الأسئلة")
async def ai_view_qa(message: Message, state: FSMContext) -> None:
    qa_list = await get_all_qa()
    if not qa_list:
        await message.answer("❌ لا توجد أسئلة.", reply_markup=ai_admin_keyboard())
        return
    lines = []
    for qa in qa_list:
        q_short = qa.question[:50]
        a_short = qa.answer[:50]
        lines.append(f"🔹 {qa.id}: 📌 {q_short}\n   💬 {a_short}")
    for i in range(0, len(lines), 10):
        chunk = "\n\n".join(lines[i:i+10])
        await message.answer(f"📋 الأسئلة:\n\n{chunk}")
    await message.answer("🔝 القائمة:", reply_markup=ai_admin_keyboard())


@router.message(AdminFilter(), F.text == "📄 رفع ملف سياق")
async def ai_upload_pdf_start(message: Message, state: FSMContext) -> None:
    await state.set_state(AIAdminState.waiting_pdf_name)
    await message.answer("✏️ أرسل اسم الملف (مثلاً: منهج الرياضيات):", reply_markup=cancel_keyboard())


@router.message(AIAdminState.waiting_pdf_name, AdminFilter())
async def ai_upload_pdf_name(message: Message, state: FSMContext) -> None:
    await state.update_data(pdf_name=message.text)
    await state.set_state(AIAdminState.waiting_pdf_file)
    await message.answer("📄 أرسل ملف PDF:", reply_markup=cancel_keyboard())


@router.message(AIAdminState.waiting_pdf_file, AdminFilter(), F.document)
async def ai_upload_pdf_file(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    name = data["pdf_name"]
    doc = message.document
    if not doc.file_name or not doc.file_name.lower().endswith(".pdf"):
        await message.answer("❌ يرجى إرسال ملف PDF.")
        return
    import os
    pdf_dir = "data/pdfs"
    os.makedirs(pdf_dir, exist_ok=True)
    dest = os.path.join(pdf_dir, f"{name}_{doc.file_id[:20]}.pdf")
    file = await message.bot.get_file(doc.file_id)
    await file.download(destination=dest)
    pdf = await save_pdf_context(name, dest)
    await state.clear()
    await message.answer(f"✅ تم رفع {name} بنجاح.", reply_markup=ai_admin_keyboard())


@router.message(AdminFilter(), F.text == "🔙 رجوع")
async def ai_back_to_admin(message: Message, state: FSMContext) -> None:
    await state.clear()
    from handlers.admin import admin_main_keyboard
    await message.answer("🔝 القائمة الرئيسية", reply_markup=await admin_main_keyboard(message.from_user.id))


# ─── User AI interface ───

@router.message(F.text == "🤖 استفسار ذكي")
async def ai_user_start(message: Message, state: FSMContext) -> None:
    await state.set_state(AIState.waiting_for_question)
    await message.answer(
        "🤖 مرحباً بك في الاستفسار الذكي!\n\n"
        "اسأل أي سؤال وسأحاول مساعدتك.\n"
        "مثال: موعد امتحان الرياضيات، شيتات الكلية، إلخ.\n\n"
        "أو استخدم 🔙 رجوع للعودة.",
        reply_markup=ai_user_keyboard(),
    )


@router.message(AIState.waiting_for_question, F.text == "🔙 رجوع")
async def ai_user_back(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🔝 القائمة الرئيسية", reply_markup=main_keyboard())


@router.message(AIState.waiting_for_question)
async def ai_user_question(message: Message, state: FSMContext) -> None:
    q = message.text.strip()
    if not q:
        return

    await message.answer("🤔 جاري البحث عن إجابة...")

    # Step 1: Search in Q&A database
    qa_list = await get_all_qa()
    best_q, best_a, score = await find_best_qa(q, qa_list)
    if best_a and score >= 0.4:
        await message.answer(
            f"📌 السؤال المشابه: {best_q}\n\n💬 {best_a}",
            reply_markup=ai_user_keyboard(),
        )
        return

    # Step 2: Check if it's a college question
    if is_college_question(q):
        # Build context from materials
        context_parts = []
        top_folders = await get_folders(None)
        for f in top_folders:
            subs = await get_folders(f.id)
            items = await get_content_items(f.id)
            names = [s.name for s in subs] + [(i.title or "محتوى") for i in items]
            context_parts.append(f"{f.name}: {', '.join(names[:10])}")

        system_prompt = (
            "أنت مساعد ذكي لبوابة كلية. أجب على أسئلة الطلاب بناءً على السياق المقدم فقط.\n"
            "إذا كانت الإجابة غير موجودة في السياق، قل: 'عذراً، لا توجد معلومات كافية عندي. سأبلغ المشرفين.'\n"
            "لا تخترع معلومات.\n\n"
            "السياق (المواد المتاحة):\n" + "\n".join(context_parts)
        )
        answer = await call_gemini(q, system_prompt=system_prompt)
        if answer:
            if "لا توجد معلومات" in answer or "عذراً" in answer:
                await message.answer(
                    f"{answer}\n\n📝 سيتم إشعار المشرفين.",
                    reply_markup=ai_user_keyboard(),
                )
                # Notify admins
                from handlers.messages import forward_to_admins
                from database.crud import save_message
                msg = await save_message(
                    user_id=message.from_user.id,
                    message_type="text",
                    content=f"[AI استفسار غير مجاب] {q}",
                )
                await forward_to_admins(message.bot, msg, message.from_user)
            else:
                await message.answer(answer, reply_markup=ai_user_keyboard())
        else:
            await message.answer(
                "⚠️ عذراً، حدث خطأ في معالجة سؤالك. يرجى المحاولة لاحقاً.",
                reply_markup=ai_user_keyboard(),
            )
        return

    # Step 3: General question → Gemini answers freely
    answer = await call_gemini(q)
    if answer:
        await message.answer(answer, reply_markup=ai_user_keyboard())
    else:
        await message.answer(
            "⚠️ عذراً، حدث خطأ. يرجى المحاولة لاحقاً.",
            reply_markup=ai_user_keyboard(),
        )
