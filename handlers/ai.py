import logging
import aiohttp
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from filters import AdminFilter
from database.crud import add_qa, delete_qa, get_all_qa, save_pdf_context, delete_pdf_context, get_all_pdfs, get_folder, get_content_items, get_folders
from keyboards.reply import ai_admin_keyboard, ai_user_keyboard, main_keyboard, cancel_keyboard
from services.gemini import call_gemini
from config import settings

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
    waiting_image_analysis = State()
    waiting_file_analysis = State()
    admin_chat = State()
    waiting_announcement = State()


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
    file_info = await message.bot.get_file(doc.file_id)
    file_bytes = await message.bot.download_file(file_info.file_path)
    with open(dest, "wb") as f:
        f.write(file_bytes.read())
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

    # Build context from Q&A and materials
    qa_list = await get_all_qa()
    qa_context = "\n".join(
        f"س: {qa.question}\nج: {qa.answer}" for qa in qa_list
    ) if qa_list else "لا توجد أسئلة مضافة بعد."

    folder_parts = []
    top_folders = await get_folders(None)
    for f in top_folders:
        subs = await get_folders(f.id)
        items = await get_content_items(f.id)
        names = [s.name for s in subs] + [(i.title or "محتوى") for i in items]
        folder_parts.append(f"{f.name}: {', '.join(names[:15])}")
    materials_context = "\n".join(folder_parts) if folder_parts else "لا توجد مواد بعد."

    system_prompt = (
        "أنت مساعد ذكي خاص بـ\"نَافِذَة\" — وهي منصة كلية. "
        "اسمك \"مساعد نافذة\". عندما يُسأل من أنت، قل: \"أنا مساعد نافذة الذكي، هنا لمساعدتك في كل ما يخص الكلية والمواد الدراسية.\"\n\n"
        "تتحدث بالعربية بأسلوب ودود ومفيد.\n\n"
        "تعليمات:\n"
        "1. رحب بالمستخدم وتحدث معه بشكل طبيعي (مرحبا، كيف حالك، إلخ).\n"
        "2. للأسئلة الخاصة بالكلية (مواعيد، مواد، شيتات، إلخ)، استخدم المعلومات الموجودة في السياق أدناه.\n"
        "3. إذا سأل عن شيء موجود في قاعدة الأسئلة، أجب بالإجابة الموجودة.\n"
        "4. إذا سأل عن شيء خاص بالكلية ولكن غير موجود في السياق، قل أنك ستبلغ المشرفين.\n"
        "5. للأسئلة العامة (رياضيات، لغة، ثقافة، محادثة عادية) أجب بحرية.\n"
        "6. لا تخترع معلومات عن الكلية. إذا لم تكن متأكداً، قل ذلك.\n\n"
        f"📚 قاعدة المعرفة (الأسئلة والأجوبة):\n{qa_context}\n\n"
        f"📁 المواد المتاحة:\n{materials_context}"
    )

    answer = await call_gemini(q, system_prompt=system_prompt)
    if answer:
        await message.answer(answer, reply_markup=ai_user_keyboard())
        # Notify admins if the answer says it doesn't know
        if "سأبلغ المشرفين" in answer or "إشعار المشرفين" in answer:
            from handlers.messages import forward_to_admins
            from database.crud import save_message
            msg = await save_message(
                user_id=message.from_user.id,
                message_type="text",
                content=f"[AI استفسار غير مجاب] {q}",
            )
            await forward_to_admins(message.bot, msg, message.from_user)
    else:
        await message.answer(
            "⚠️ عذراً، حدث خطأ. يرجى المحاولة لاحقاً.",
            reply_markup=ai_user_keyboard(),
        )


# ─── Admin: Image Analysis ───

@router.message(AdminFilter(), F.text == "🧠 تحليل صورة")
async def ai_admin_image_start(message: Message, state: FSMContext) -> None:
    await state.set_state(AIAdminState.waiting_image_analysis)
    await message.answer("🖼 أرسل الصورة التي تريد تحليلها:", reply_markup=cancel_keyboard())


@router.message(AIAdminState.waiting_image_analysis, AdminFilter(), F.photo)
async def ai_admin_image_analyze(message: Message, state: FSMContext) -> None:
    photo = message.photo[-1]
    file_info = await message.bot.get_file(photo.file_id)
    file_bytes = await message.bot.download_file(file_info.file_path)
    import base64
    b64 = base64.b64encode(file_bytes.read()).decode()

    prompt = "حلل هذه الصورة بالتفصيل باللغة العربية. ماذا ترى فيها؟"
    answer = await _call_groq_vision(prompt, b64)
    await state.clear()
    if answer:
        await message.answer(f"🧠 التحليل:\n\n{answer}", reply_markup=ai_admin_keyboard())
    else:
        await message.answer("⚠️ فشل تحليل الصورة.", reply_markup=ai_admin_keyboard())


@router.message(AIAdminState.waiting_image_analysis, AdminFilter())
async def ai_admin_image_invalid(message: Message, state: FSMContext) -> None:
    await message.answer("❌ يرجى إرسال صورة.")


# ─── Admin: File Analysis ───

@router.message(AdminFilter(), F.text == "📄 تحليل ملف")
async def ai_admin_file_start(message: Message, state: FSMContext) -> None:
    await state.set_state(AIAdminState.waiting_file_analysis)
    await message.answer("📄 أرسل الملف (PDF, صورة, نص) لتحليله:", reply_markup=cancel_keyboard())


@router.message(AIAdminState.waiting_file_analysis, AdminFilter(), F.document)
async def ai_admin_file_analyze(message: Message, state: FSMContext) -> None:
    doc = message.document
    file_info = await message.bot.get_file(doc.file_id)
    file_bytes = await message.bot.download_file(file_info.file_path)
    content = file_bytes.read()
    text = content.decode("utf-8", errors="ignore")[:3000]

    prompt = f"حلل هذا المحتوى بالعربية:\n\n{text}"
    answer = await call_gemini(prompt)
    await state.clear()
    if answer:
        await message.answer(f"📄 تحليل الملف:\n\n{answer}", reply_markup=ai_admin_keyboard())
    else:
        await message.answer("⚠️ فشل تحليل الملف.", reply_markup=ai_admin_keyboard())


@router.message(AIAdminState.waiting_file_analysis, AdminFilter())
async def ai_admin_file_invalid(message: Message, state: FSMContext) -> None:
    await message.answer("❌ يرجى إرسال ملف.")


# ─── Admin: Smart Chat ───

@router.message(AdminFilter(), F.text == "🤖 محادثة ذكية")
async def ai_admin_chat_start(message: Message, state: FSMContext) -> None:
    await state.set_state(AIAdminState.admin_chat)
    await message.answer(
        "🤖 محادثة ذكية مع المساعد.\nاسأل أي شيء أو استخدم 🔙 رجوع للخروج.",
        reply_markup=cancel_keyboard(),
    )


@router.message(AIAdminState.admin_chat, AdminFilter(), F.text == "❌ إلغاء")
async def ai_admin_chat_exit(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🔝 القائمة", reply_markup=ai_admin_keyboard())


@router.message(AIAdminState.admin_chat, AdminFilter())
async def ai_admin_chat_message(message: Message, state: FSMContext) -> None:
    q = message.text or message.caption or ""
    if not q:
        return
    answer = await call_gemini(q)
    if answer:
        await message.answer(answer, reply_markup=cancel_keyboard())
    else:
        await message.answer("⚠️ فشل.", reply_markup=cancel_keyboard())


# ─── Admin: تحليل الإعلانات والتنويهات ───

@router.message(AdminFilter(), F.text == "📰 تحليل إعلان")
async def ai_admin_announcement_start(message: Message, state: FSMContext) -> None:
    await state.set_state(AIAdminState.waiting_announcement)
    await message.answer(
        "📰 أرسل نص الإعلان أو التنويه وسأقوم باستخراج الأسئلة والأجوبة منه وإضافتها تلقائياً.",
        reply_markup=cancel_keyboard(),
    )


@router.message(AIAdminState.waiting_announcement, AdminFilter())
async def ai_admin_announcement_analyze(message: Message, state: FSMContext) -> None:
    text = message.text or message.caption or ""
    if not text or len(text) < 20:
        await message.answer("❌ النص قصير جداً. أرسل الإعلان كاملاً.")
        return

    await message.answer("🤔 جاري تحليل الإعلان واستخراج الأسئلة...")

    prompt = (
        "اقرأ هذا الإعلان ثم استخرج منه أسئلة وأجوبة محتملة قد يسألها طالب.\n"
        "يجب أن تكون الأسئلة متنوعة وتغطي كل المعلومات المهمة في الإعلان.\n"
        "أعد النتيجة بهذا التنسيق بالضبط:\n"
        "---\n"
        "س: السؤال الأول\n"
        "ج: الجواب الأول\n"
        "---\n"
        "س: السؤال الثاني\n"
        "ج: الجواب الثاني\n"
        "---\n\n"
        f"الإعلان:\n{text}"
    )
    answer = await call_gemini(prompt)
    if not answer or "س:" not in answer:
        await message.answer("⚠️ فشل في استخراج الأسئلة. حاول مرة أخرى.", reply_markup=ai_admin_keyboard())
        await state.clear()
        return

    import re
    pairs = re.findall(r"س:\s*(.*?)\nج:\s*(.*?)(?:\n---|$)", answer, re.DOTALL)
    if not pairs:
        await message.answer("⚠️ لم أتمكن من استخراج أزواج أسئلة.", reply_markup=ai_admin_keyboard())
        await state.clear()
        return

    added = 0
    for q, a in pairs:
        q = q.strip()
        a = a.strip()
        if q and a:
            existing = await get_all_qa()
            if not any(e.question.strip().lower() == q.lower() for e in existing):
                await add_qa(q, a)
                added += 1

    await state.clear()
    await message.answer(
        f"✅ تم استخراج وإضافة {added} سؤال/جواب من الإعلان:\n\n"
        + "\n".join(f"📌 {q[:50]}…\n💬 {a[:50]}…" for q, a in pairs[:5]),
        reply_markup=ai_admin_keyboard(),
    )

async def _call_groq_vision(prompt: str, image_b64: str) -> str | None:
    api_key = settings.GROQ_API_KEY
    if not api_key:
        return None
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "openai/gpt-oss-120b",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ],
            }
        ],
        "max_tokens": 1024,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload, headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "").strip()
    except Exception:
        return None
    return None
