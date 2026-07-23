import logging
import re
import asyncio
import aiohttp
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardMarkup, ReplyKeyboardMarkup
from filters import AdminFilter
from database.crud import (add_qa, delete_qa, get_all_qa, save_pdf_context, delete_pdf_context, get_all_pdfs,
                           get_folder, get_content_items, get_folders, get_content_links,
                           add_article, delete_article, get_all_articles, get_all_prerequisites,
                             clear_prerequisites, add_prerequisite, is_ai_active, is_ai_silent,
                             add_folder, remove_folder, rename_folder, add_content_item, remove_content_item,
                             update_content_item_title, add_content_link, remove_content_link, update_content_link,
                             ban_user, unban_user, get_user, add_alias,
                             get_all_aliases, has_agreed_ai, set_agreed_ai, log_ai_action,
                             add_autoreply, remove_autoreply, get_all_autoreplies, get_all_users)
from keyboards.reply import ai_admin_keyboard, ai_user_keyboard, main_keyboard, cancel_keyboard, smart_mode_keyboard, agreement_keyboard
from services.gemini import call_gemini, call_groq_vision
from config import settings

logger = logging.getLogger(__name__)
router = Router()

MAX_MSG_LEN = 4000  # Leave room for safety


async def safe_send(message: Message, text: str, reply_markup=None) -> None:
    """Split long text and send in chunks to avoid message_too_long."""
    if not text:
        return
    if len(text) <= MAX_MSG_LEN:
        await message.answer(text, reply_markup=reply_markup, parse_mode=None)
        return
    parts = []
    while text:
        if len(text) <= MAX_MSG_LEN:
            parts.append(text)
            break
        split_at = text.rfind("\n", 0, MAX_MSG_LEN)
        if split_at == -1:
            split_at = text.rfind(" ", 0, MAX_MSG_LEN)
        if split_at == -1:
            split_at = MAX_MSG_LEN
        parts.append(text[:split_at])
        text = text[split_at:].strip()
    for i, part in enumerate(parts):
        markup = reply_markup if i == len(parts) - 1 else None
        await message.answer(part, reply_markup=markup, parse_mode=None)
        await asyncio.sleep(0.3)


class AIState(StatesGroup):
    waiting_for_question = State()
    waiting_agreement = State()


class AIAdminState(StatesGroup):
    waiting_question = State()
    waiting_answer = State()
    waiting_delete_id = State()
    waiting_pdf_name = State()
    waiting_pdf_file = State()
    waiting_image_analysis = State()
    waiting_file_analysis = State()
    admin_chat = State()
    waiting_article_title = State()
    waiting_article_text = State()
    smart_mode = State()


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
        "📋 الأسئلة الموجودة:\n\n" + "\n".join(lines[-20:]) + "\n\nأرسل رقم السؤال للحذف\n(أو عدة أرقام كل رقم في سطر):",
        reply_markup=cancel_keyboard(),
    )


@router.message(AIAdminState.waiting_delete_id, AdminFilter())
async def ai_delete_qa_confirm(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    ids = set()
    for line in text.splitlines():
        line = line.strip()
        try:
            ids.add(int(line))
        except ValueError:
            pass
    if not ids:
        await message.answer("❌ أرسل رقماً واحداً أو عدة أرقام كل رقم في سطر.")
        return
    deleted = 0
    not_found = 0
    for qa_id in ids:
        ok = await delete_qa(qa_id)
        if ok:
            deleted += 1
        else:
            not_found += 1
    await state.clear()
    parts = []
    if deleted:
        parts.append(f"✅ تم حذف {deleted} سؤال/جواب")
    if not_found:
        parts.append(f"❌ {not_found} غير موجودة")
    await message.answer(" | ".join(parts), reply_markup=ai_admin_keyboard())


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


# ─── User AI interface (conversation) ───

@router.message(F.text == "نَافِذَة الـ AI")
async def ai_user_start(message: Message, state: FSMContext) -> None:
    if not is_ai_active():
        if is_ai_silent():
            await state.clear()
            await message.answer("🔝", reply_markup=main_keyboard())
            return
        await message.answer("🛑 نَافِذَة الـ AI متوقفة حالياً. حاول لاحقاً.", reply_markup=main_keyboard())
        return
    if await has_agreed_ai(message.from_user.id):
        await state.set_state(AIState.waiting_for_question)
        await state.update_data(history=[])
        await message.answer(
            "مرحباً بك في نَافِذَة الـ AI!\n"
            "أنا نموذج ذكاء اصطناعي مُطوّر لبوت نَافِذَة، أعمل على معالجة أسئلتك ومساعدتك في كافة استفساراتك الجامعية خطوة بخطوة.\n"
            "تفضل بكتابة سؤالك وسأجيبك فوراً!\n\n"
            "أو استخدم 🔙 رجوع للعودة.",
            reply_markup=ai_user_keyboard(),
        )
        return
    await state.set_state(AIState.waiting_agreement)
    name = message.from_user.full_name or message.from_user.username or str(message.from_user.id)
    await log_ai_action(message.from_user.id, name, "📋 عرض اتفاقية AI")
    terms = (
        "اتفاقية استخدام نَافِذَة الـ AI\n\n"
        "قبل البدء، الرجاء الاطلاع على الشروط التالية:\n\n"
        "1. طبيعة الخدمة: هذا البوت يعمل بالذكاء الاصطناعي وهو قيد التجربة، "
        "وقد تظهر به بعض الأخطاء أو معلومات غير دقيقة من وقت لآخر.\n\n"
        "2. المسؤولية: يُعد البوت أداة استرشادية مساعدة، واستخدامه يتم تحت "
        "مسؤوليتك الخاصة. نرجو دائماً مراجعة المحتوى والتأكد من صحة المعلومات "
        "من المصادر الرسمية.\n\n"
        "3. البيانات: قد يتم استخدام بعض المحادثات بشكل مجهول بهدف تحسين "
        "الخدمة وتطويرها.\n\n"
        "4. الاستخدام المقبول: يُمنع استخدام البوت لإرسال محتوى مسيء أو "
        "مخالف للأنظمة. يحق للإدارة إيقاف الوصول عن أي مستخدم يخالف ذلك.\n\n"
        "5. التعديلات: يحق لإدارة البوت تعديل هذه الشروط أو إيقاف الخدمة "
        "في أي وقت دون إشعار مسبق.\n\n"
        "6. التواصل: عند وجود أي استفسار، يُرجى التواصل عبر زر "
        "\"نَافِذَة التَّوَاصُل\" في القائمة الرئيسية.\n\n"
        "بالضغط على \"✅ موافقة\"، فإنك توافق على جميع ما ورد أعلاه."
    )
    await message.answer(terms, reply_markup=agreement_keyboard())


@router.callback_query(AIState.waiting_agreement, F.data == "agree_ai")
async def ai_user_agree(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await set_agreed_ai(callback.from_user.id)
    name = callback.from_user.full_name or callback.from_user.username or str(callback.from_user.id)
    await log_ai_action(callback.from_user.id, name, "✅ موافقة على اتفاقية AI")
    await state.set_state(AIState.waiting_for_question)
    await state.update_data(history=[])
    await callback.message.answer(
        "مرحباً بك في نَافِذَة الـ AI!\n"
        "أنا نموذج ذكاء اصطناعي مُطوّر لبوت نَافِذَة، أعمل على معالجة أسئلتك ومساعدتك في كافة استفساراتك الجامعية خطوة بخطوة.\n"
        "تفضل بكتابة سؤالك وسأجيبك فوراً!\n\n"
        "أو استخدم 🔙 رجوع للعودة.",
        reply_markup=ai_user_keyboard(),
    )


@router.callback_query(AIState.waiting_agreement, F.data == "disagree_ai")
async def ai_user_disagree(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    await callback.message.answer("تم العودة إلى القائمة الرئيسية.", reply_markup=main_keyboard())


@router.message(AIState.waiting_agreement)
async def ai_user_agreement_fallback(message: Message, state: FSMContext) -> None:
    await message.answer("الرجاء استخدام الأزرار أعلاه للموافقة أو الرفض.", reply_markup=agreement_keyboard())


@router.message(AIState.waiting_for_question, F.text == "🔙 رجوع")
async def ai_user_back(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🔝 القائمة الرئيسية", reply_markup=main_keyboard())


@router.message(AIState.waiting_for_question)
async def ai_user_question(message: Message, state: FSMContext) -> None:
    try:
        await _ai_user_question(message, state)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.exception("AI user question error")
        from database.crud import save_error
        save_error("ai_user_question", tb[:1500])
        err_msg = str(e)[:200] or "خطأ غير معروف"
        try:
            await message.answer(
                f"⚠️ حدث خطأ: {err_msg}\n\nحاول مرة أخرى أو استخدم 🔙 رجوع.",
                reply_markup=ai_user_keyboard(),
            )
        except Exception:
            pass  # ignore if even the error message fails
        for admin_id in settings.admin_ids:
            try:
                await message.bot.send_message(admin_id, f"⚠️ خطأ في AI:\n{tb[:3500]}", parse_mode=None)
            except Exception as e2:
                logger.error("Failed to send traceback to admin %s: %s", admin_id, e2)


async def _ai_user_question(message: Message, state: FSMContext) -> None:
    q = (message.text or message.caption or "").strip()
    if not q:
        return

    if not is_ai_active():
        await state.clear()
        await message.answer("🛑 المساعد الذكي متوقف حالياً.", reply_markup=main_keyboard())
        return

    data = await state.get_data()
    history: list[dict] = data.get("history", [])

    # Check if AI previously offered to notify admins and user is confirming
    if data.get("pending_admin_notify"):
        confirm_words = ["نعم", "اي", "أي", "تمام", "طيب", "ih", "is", "ok", "yes", "aye", "go ahead", "ابشر", "هات"]
        if any(w in q.lower() for w in confirm_words):
            await state.update_data(pending_admin_notify=False)
            from handlers.messages import forward_to_admins
            from database.crud import save_message
            ai_context = "\n".join(
                f"المستخدم: {turn['user']}\nالمساعد: {turn['assistant']}"
                for turn in history[-5:]
            )
            original_q = data.get("pending_notify_q", q)
            msg = await save_message(
                user_id=message.from_user.id,
                message_type="text",
                content=f"[طلب AI]\n{original_q}\n\nسجل المحادثة:\n{ai_context}",
            )
            await forward_to_admins(message, "text", msg.id)
            await message.answer("✅ تم إبلاغ المشرفين، سيردون عليك قريباً إن شاء الله.", reply_markup=ai_user_keyboard())
            return
        else:
            await state.update_data(pending_admin_notify=False)
            # fall through to normal AI processing

    # Build static context from Q&A, materials, articles, and prerequisites
    try:
        qa_list = await get_all_qa()
    except Exception as e:
        logger.error("AI: get_all_qa failed: %s", e)
        qa_list = []
    qa_context = "\n".join(
        f"س: {qa.question}\nج: {qa.answer}" for qa in qa_list
    ) if qa_list else "لا توجد أسئلة مضافة بعد."

    # Build full materials tree recursively with links (max depth 10)
    async def build_tree(parent_id: int | None, indent: int = 0, depth: int = 0) -> str:
        if depth > 10:
            return ""
        prefix = "  " * indent + "• "
        lines = []
        folders = await get_folders(parent_id)
        for f in folders:
            lines.append(f"{prefix}📁 {f.name}")
            child = await build_tree(f.id, indent + 1, depth + 1)
            if child:
                lines.append(child)
            items = await get_content_items(f.id)
            for item in items:
                links = await get_content_links(item.id)
                link_str = ""
                if links:
                    link_str = " → ".join(l.link[:50] for l in links[:3])
                    if len(links) > 3:
                        link_str += f" (+{len(links)-3})"
                title = item.title or "محتوى"
                lines.append(f"{'  ' * (indent+1)}• 📄 {title}" + (f" — {link_str}" if link_str else ""))
        return "\n".join(lines)

    try:
        if await get_folders(None):
            materials_context = await build_tree(None)
        else:
            materials_context = "لا توجد مواد بعد."
    except Exception as e:
        logger.error("AI: build_tree failed: %s", e)
        materials_context = "حدث خطأ أثناء بناء شجرة المواد."
    if len(materials_context) > 6000:
        materials_context = materials_context[:6000] + "\n... (يوجد المزيد)"

    try:
        articles_list = await get_all_articles()
    except Exception as e:
        logger.error("AI: get_all_articles failed: %s", e)
        articles_list = []
    articles_context = ""
    for a in articles_list:
        c = a.content[:1000]
        articles_context += f"\nعنوان: {a.title}\nمحتوى: {c}\n"

    try:
        prereqs_list = await get_all_prerequisites()
    except Exception as e:
        logger.error("AI: get_all_prerequisites failed: %s", e)
        prereqs_list = []

    # Load PDF context files
    try:
        pdfs = await get_all_pdfs()
        pdf_context = ""
        for p in pdfs:
            pdf_context += f"\n📄 {p.name}: "
            try:
                with open(p.file_path, "rb") as pf:
                    raw = pf.read()
                text = raw.decode("utf-8", errors="ignore")[:1500]
                pdf_context += text[:500] + "...\n"
            except Exception:
                pdf_context += "(تعذر قراءة الملف)\n"
        if pdfs:
            pdf_context = "📚 الملفات السياقية:\n" + pdf_context + "\n"
    except Exception:
        pdf_context = ""

    # Build two views: forward (what a course opens) and backward (what a course needs)
    forward_map: dict[str, list[tuple[str, str]]] = {}
    backward_map: dict[str, list[tuple[str, str]]] = {}
    for p in prereqs_list:
        key = f"{p.prerequisite_name} ({p.prerequisite_code})"
        val = (p.course_name, p.course_code)
        forward_map.setdefault(key, []).append(val)
        key2 = f"{p.course_name} ({p.course_code})"
        val2 = (p.prerequisite_name, p.prerequisite_code)
        backward_map.setdefault(key2, []).append(val2)

    forward_lines = []
    for course, opens in forward_map.items():
        names = [f"{n} ({c})" for n, c in opens]
        forward_lines.append(f"{course} ← تفتح → {', '.join(names)}")
    backward_lines = []
    for course, needs in backward_map.items():
        names = [f"{n} ({c})" for n, c in needs]
        backward_lines.append(f"{course} ← تحتاج → {', '.join(names)}")

    prereqs_context = ""
    if forward_lines:
        prereqs_context += "📌 المواد والمواد التي تفتحها:\n" + "\n".join(forward_lines)
        prereqs_context += "\n\n"
    if backward_lines:
        prereqs_context += "📌 المواد ومتطلباتها القبلية:\n" + "\n".join(backward_lines)
    if not prereqs_context:
        prereqs_context = "لا توجد متطلبات دراسية محفوظة."

    # Build aliases context
    try:
        aliases_list = await get_all_aliases()
    except Exception:
        aliases_list = []
    aliases_context = ""
    for a in aliases_list:
        aliases_context += f"- '{a.alias}' ← {a.course_name} ({a.course_code})\n"
    if aliases_list:
        aliases_context = "📌 الأسماء البديلة للمواد (المستخدمون يسألون بها):\n" + aliases_context

    # Build conversation history
    history_lines = []
    for turn in history[-10:]:  # last 10 exchanges max
        history_lines.append(f"المستخدم: {turn['user']}")
        history_lines.append(f"المساعد: {turn['assistant']}")
    history_context = "\n".join(history_lines)

    history_note = ""
    if history_context:
        history_note = f"\nسجل المحادثة السابقة (للتذكير فقط):\n{history_context}\n"

    system_prompt = (
        "أنت مساعد ذكي خاص بـ\"نَافِذَة\" — منصة كلية. اسمك \"مساعد نافذة\".\n\n"
        "تتحدث بالعربية بأسلوب ودود طبيعي.\n"
        "ممنوع استخدام ** أو * أو أي تنسيق Markdown — اكتب نص فقط.\n"
        "ممنوع تكتب تفكير داخلي أو تحليل — جاوب مباشرة بالعربية فقط.\n\n"
        f"{history_note}"
        f"{aliases_context}"
        f"📚 قاعدة المعرفة:\n{qa_context}\n\n"
        f"📁 المواد:\n{materials_context}\n\n"
        f"📰 المقالات:\n{articles_context}\n\n"
        f"{pdf_context}"
        f"🔗 المتطلبات:\n{prereqs_context}\n\n"
        "📌 تعليمات بسيطة:\n"
        "- افهم السؤال حتى لو فيه أخطاء إملائية.\n"
        "- استخدم قاعدة المعرفة والمواد والمقالات للإجابة.\n"
        "- عندما يسألك عن مجلد أو مادة معينة، ابحث في قائمة المواد أعلاه وأجب منه.\n"
        "- إذا عرفت الإجابة جاوب. إذا برا الكلية جاوب طبيعي.\n"
        "- إذا السؤال يحتاج مشرف (تسجيل، شكوى، طلب مادة)، جاوب طبيعي ثم في النهاية اسأل: "
        "'هل تريدني أن أبلغ المشرفين بهذا الطلب؟'\n"
        "- إذا استخدم المستخدم اسم مادة غريب وانت عارفها، اسأله هل يقصدها. لو قال نعم اكتب:\n"
        "[SAVE_ALIAS] الاسم | كود_المادة | اسم_المادة\n"
    )

    user_prompt = q

    answer = await call_gemini(user_prompt, system_prompt=system_prompt)
    if answer:
        # Process [SAVE_ALIAS] command from AI response
        save_match = re.search(r"\[SAVE_ALIAS\]\s*(.+?)\s*\|\s*(.+?)\s*\|\s*(.+)", answer, re.DOTALL)
        if save_match:
            alias_name = save_match.group(1).strip().lower()
            course_code = save_match.group(2).strip()
            course_name = save_match.group(3).strip()
            try:
                from database.crud import add_alias
                await add_alias(alias_name, course_code, course_name)
                # Also send confirmation to user
                try:
                    await message.answer(f"✅ تم حفظ الاسم البديل '{alias_name}' ← {course_name}")
                except Exception:
                    pass
            except Exception:
                pass
        # Try to forward actual files from Telegram links in the answer (deduplicated)
        forwarded = set()
        for tme_link in re.findall(r"https?://t\.me/([a-zA-Z0-9_]+)/(\d+)", answer):
            username, msg_id = tme_link[0], int(tme_link[1])
            key = f"{username}/{msg_id}"
            if key in forwarded:
                continue
            forwarded.add(key)
            try:
                chat = "@" + username
                await message.bot.copy_message(
                    chat_id=message.chat.id,
                    from_chat_id=chat,
                    message_id=msg_id,
                )
            except Exception as exc:
                logger.warning("copy_message failed for %s/%s: %s", username, msg_id, exc)
        # Strip Telegram links from displayed text (files already forwarded)
        clean_answer = re.sub(r"https?://t\.me/\S+", "", answer).strip()
        # Remove content inside <think> tags (reasoning output) first
        clean_answer = re.sub(r"<think>.*?</think>", "", clean_answer, flags=re.DOTALL).strip()
        # Then strip any remaining HTML tags
        clean_answer = re.sub(r"<[^>]+>", "", clean_answer)
        # Strip markdown bold markers ** **
        clean_answer = clean_answer.replace("**", "")
        # Strip CoT: find [Output Generation] marker first
        gen_match = re.search(r"\[Output Generation\].*?->\s*\"?(.*)", clean_answer, re.DOTALL)
        if gen_match:
            clean_answer = gen_match.group(1).strip().rstrip('"')
        else:
            # Fallback: remove from "Here's a thinking process" or similar to end of analysis
            # Strategy: find the first Arabic-only paragraph after the thinking process
            paragraphs = re.split(r"\n\s*\n", clean_answer)
            answer_parts = []
            for p in paragraphs:
                stripped = p.strip()
                if not stripped:
                    continue
                # Count Arabic vs non-Arabic chars
                arabic_count = len(re.findall(r"[\u0600-\u06FF]", stripped))
                total = len(stripped.strip())
                # If mostly non-Arabic and looks like analysis, skip
                if total > 0:
                    arabic_ratio = arabic_count / total
                else:
                    arabic_ratio = 0
                # Keep paragraph if: mostly Arabic, or it's short Arabic text
                is_thinking = (
                    re.match(r"^\d+\.\s", stripped)  # numbered "1. ..."
                    or re.match(r"^-\s", stripped)   # bullet "- ..."
                    or stripped.startswith("Here") 
                    or stripped.startswith("Let")
                    or stripped.startswith("Wait")
                    or stripped.startswith("I'll")
                    or stripped.startswith("Ok")
                    or arabic_ratio < 0.3
                )
                if not is_thinking:
                    answer_parts.append(stripped)
            if answer_parts:
                clean_answer = "\n\n".join(answer_parts)
            else:
                # Last resort: strip from first Arabic char
                m = re.search(r"[\u0600-\u06FF]", clean_answer)
                if m:
                    clean_answer = clean_answer[m.start():].strip()
        # Clean up double spaces / empty lines
        clean_answer = re.sub(r"\n{3,}", "\n\n", clean_answer)

        # Force the "ask permission" flow even if model ignores instructions
        had_notify_offer = False
        for phrase in ["سأبلغ المشرفين", "سأخبر المشرفين", "سأبلغ الإدارة", "سأخبر الإدارة"]:
            if phrase in clean_answer:
                clean_answer = clean_answer.replace(phrase, "هل تريدني أن أبلغ المشرفين بهذا الطلب؟")
                had_notify_offer = True
        if "📢" in clean_answer:
            clean_answer = clean_answer.replace("📢", "").strip()
        if had_notify_offer or (re.search(r"سأبلغ", clean_answer) and re.search(r"المشرفين|الإدارة", clean_answer)):
            await state.update_data(pending_admin_notify=True, pending_notify_q=q)
            clean_answer = clean_answer.replace("📢", "").strip()
            await state.update_data(pending_admin_notify=True, pending_notify_q=q)

        if clean_answer:
            await safe_send(message, clean_answer, reply_markup=ai_user_keyboard())
        # Save to history
        history.append({"user": q, "assistant": answer})
        await state.update_data(history=history)

        # Check if AI offered to notify admins (after forced replacement above)
        if "هل تريد" in clean_answer and "أبلغ المشرفين" in clean_answer:
            if not (await state.get_data()).get("pending_admin_notify"):
                await state.update_data(pending_admin_notify=True, pending_notify_q=q)
        elif any(w in q for w in ["قول للمشرف", "بلغ المشرف", "كلم المشرف", "ابلغ المشرف"]):
            from handlers.messages import forward_to_admins
            from database.crud import save_message
            ai_context = "\n".join(
                f"المستخدم: {turn['user']}\nالمساعد: {turn['assistant']}"
                for turn in history[-5:]
            )
            msg = await save_message(
                user_id=message.from_user.id,
                message_type="text",
                content=f"[طلب AI]\n{q}\n\nسجل المحادثة:\n{ai_context}",
            )
            await forward_to_admins(message, "text", msg.id)
    else:
        await message.answer(
            "⚠️ عذراً، حدث خطأ. يرجى المحاولة لاحقاً.",
            reply_markup=ai_user_keyboard(),
        )


# ─── Admin: Smart unified analysis ───

@router.message(AdminFilter(), F.text == "🧠 تحليل ذكي")
async def ai_smart_start(message: Message, state: FSMContext) -> None:
    await state.set_state(AIAdminState.smart_mode)
    await state.update_data(admin_history=[])
    await message.answer(
        "🧠 أرسل أي شيء للتحليل:\n"
        "• 🖼 صورة → تحليلها\n"
        "• 📄 PDF → حفظه كسياق علمي\n"
        "• 📝 نص متطلبات (تفتح/يحتاج) → استخراج العلاقات\n"
        "• 📝 نص عادي → محادثة ذكية مع أوامر\n\n"
        "🔙 استخدم رجوع للخروج.",
        reply_markup=smart_mode_keyboard(),
    )


@router.message(AIAdminState.smart_mode, AdminFilter(), F.photo)
async def ai_smart_image(message: Message, state: FSMContext) -> None:
    try:
        photo = message.photo[-2] if len(message.photo) >= 2 else message.photo[-1]
        file_info = await message.bot.get_file(photo.file_id)
        file_bytes = await message.bot.download_file(file_info.file_path)
        import base64
        b64 = base64.b64encode(file_bytes.read()).decode()
        if len(b64) > 20_000_000:
            await message.answer("⚠️ الصورة كبيرة جداً. أرسل صورة بدقة أقل.")
            return
        prompt = "حلل هذه الصورة بالتفصيل باللغة العربية. ماذا ترى فيها؟"
        answer = await call_groq_vision(prompt, b64)
        if answer:
            await safe_send(message, f"🧠 تحليل الصورة:\n\n{answer}")
        else:
            await message.answer("⚠️ فشل تحليل الصورة. تحقق من سجل الأخطاء.")
    except Exception as e:
        logger.exception("Image analysis error")
        from database.crud import save_error
        save_error("ai_smart_image", str(e)[:500])
        await message.answer(f"⚠️ خطأ: {str(e)[:150]}")


@router.message(AIAdminState.smart_mode, AdminFilter(), F.document)
async def ai_smart_document(message: Message, state: FSMContext) -> None:
    doc = message.document
    import os
    pdf_dir = "data/pdfs"
    os.makedirs(pdf_dir, exist_ok=True)
    name = (doc.file_name or "ملف").rsplit(".", 1)[0][:50]
    dest = os.path.join(pdf_dir, f"{name}_{doc.file_id[:20]}.pdf")
    file_info = await message.bot.get_file(doc.file_id)
    file_bytes = await message.bot.download_file(file_info.file_path)
    with open(dest, "wb") as f:
        f.write(file_bytes.read())
    pdf = await save_pdf_context(name, dest)

    await message.answer(f"✅ تم حفظ {name}. جاري استخراج النص وتحليله...")
    try:
        import fitz
        pdf_text = ""
        with fitz.open(dest) as doc_pdf:
            for page in doc_pdf:
                pdf_text += page.get_text()
        if not pdf_text.strip():
            pdf_text = "لم يتم استخراج نص من هذا PDF."
    except Exception as e:
        logger.warning("PDF text extraction failed: %s", e)
        pdf_text = "تعذر استخراج النص من هذا PDF."

    # Save full text as context
    await save_pdf_context(name, dest)
    # Store PDF text in state for conversation
    data = await state.get_data()
    admin_history: list = data.get("admin_history", [])
    admin_history.append({"user": f"[رفع ملف: {name}]", "assistant": f"محتوى الملف:\n{pdf_text[:3000]}"})
    admin_history = admin_history[-5:]
    await state.update_data(admin_history=admin_history)

    current_state = await state.get_state()
    _in_smart = current_state == AIAdminState.smart_mode.state
    _rm = None if _in_smart else cancel_keyboard()

    # Send an initial summary/analysis
    preview = pdf_text[:1500]
    summary = await call_gemini(
        f"لخص هذا المحتوى بالعربية في 3-4 نقاط:\n\n{preview}",
        system_prompt="لخص بدقة ووضوح بالعربية. لا تكتب Markdown.",
    )
    if summary:
        await safe_send(
            message,
            f"📄 تحليل \"{name}\":\n\n{summary}\n\n---\nيمكنك متابعة السؤال عن محتوى الملف.",
            reply_markup=_rm,
        )
    else:
        await safe_send(
            message,
            f"📄 تم حفظ \"{name}\". المحتوى:\n\n{pdf_text[:1000]}",
            reply_markup=_rm,
        )


@router.message(AIAdminState.smart_mode, AdminFilter())
async def ai_smart_text(message: Message, state: FSMContext) -> None:
    """Handle text in smart mode — detects prerequisites, else smart chat."""
    text = message.text or ""
    # Check for prerequisites patterns
    prereq_keywords = ["تفتح", "يحتاج", "متطلب", "prerequisite", "يفتح"]
    if any(kw in text for kw in prereq_keywords) and len(text) > 30:
        await _ai_admin_parse_prereqs(message, state)
    else:
        await _ai_admin_chat_message(message, state)


# ─── Admin: Smart chat (also accessible via smart mode) ───

@router.message(AdminFilter(), F.text == "🤖 محادثة ذكية")
async def ai_admin_chat_start(message: Message, state: FSMContext) -> None:
    await state.set_state(AIAdminState.admin_chat)
    await message.answer(
        "🤖 محادثة ذكية مع المساعد.\n\n"
        "تقدر تتكلم معاه عادي، أو تعطيه أوامر مثل:\n"
        "- ضيف سؤال: السؤال | الجواب\n"
        "- حذف سؤال 3\n"
        "- ضيف مقال: العنوان | المحتوى\n"
        "- حذف مقال 5\n"
        "- عرض الأسئلة\n"
        "- عرض المقالات\n"
        "- مسح المتطلبات\n\n"
        "أو استخدم 🔙 رجوع للخروج.",
        reply_markup=cancel_keyboard(),
    )


@router.message(AIAdminState.admin_chat, AdminFilter(), F.text == "❌ إلغاء")
async def ai_admin_chat_exit(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🔝 القائمة", reply_markup=ai_admin_keyboard())


@router.message(AIAdminState.admin_chat, AdminFilter())
async def ai_admin_chat_message(message: Message, state: FSMContext) -> None:
    try:
        await _ai_admin_chat_message(message, state)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.exception("AI admin chat error")
        from database.crud import save_error
        save_error("ai_admin_chat", tb[:1500])
        err_msg = str(e)[:300] or "خطأ غير معروف"
        await message.answer(f"⚠️ حدث خطأ: {err_msg}", reply_markup=cancel_keyboard())
        for admin_id in settings.admin_ids:
            try:
                await message.bot.send_message(admin_id, f"⚠️ خطأ في AI:\n{tb[:3500]}", parse_mode=None)
            except Exception:
                pass


async def _ai_admin_chat_message(message: Message, state: FSMContext) -> None:
    q = message.text or message.caption or ""
    if not q:
        return

    data = await state.get_data()
    admin_history: list[dict] = data.get("admin_history", [])

    current_state = await state.get_state()
    _in_smart = current_state == AIAdminState.smart_mode.state
    _rm = None if _in_smart else cancel_keyboard()

    qa_list = await get_all_qa()
    qa_context = "\n".join(
        f"{qa.id}: س: {qa.question[:60]} → ج: {qa.answer[:60]}"
        for qa in qa_list[-20:]
    ) if qa_list else "لا يوجد"

    articles_list = await get_all_articles()
    art_context = "\n".join(
        f"{a.id}: {a.title[:50]} ({len(a.content)} حرف)"
        for a in articles_list[-10:]
    ) if articles_list else "لا يوجد"

    prereqs_list = await get_all_prerequisites()
    prereq_count = len(prereqs_list)

    # Build folders/tree context for admin
    async def _tf(parent_id: int = None, indent: int = 0) -> str:
        lines = []
        for f in await get_folders(parent_id):
            lines.append(f"{'  ' * indent}• {f.name} (ID: {f.id})")
            items = await get_content_items(f.id)
            for it in items:
                lines.append(f"{'  ' * (indent+1)}📄 {it.title or 'محتوى'} (ID: {it.id})")
            child = await _tf(f.id, indent + 1)
            if child:
                lines.append(child)
        return "\n".join(lines)
    folders_tree = await _tf()

    # Build aliases context
    try:
        admin_aliases = await get_all_aliases()
    except Exception:
        admin_aliases = []
    aliases_str = "\n".join(f"'{a.alias}' ← {a.course_name} ({a.course_code})" for a in admin_aliases) or "لا يوجد"

    # Build conversation history
    history_lines = []
    for turn in admin_history:
        history_lines.append(f"المستخدم: {turn['user']}")
        history_lines.append(f"المساعد: {turn['assistant']}")
    history_context = "\n".join(history_lines)
    history_note = ""
    if history_context:
        history_note = f"\nسجل المحادثة السابقة (للتذكير فقط):\n{history_context}\n"

    admin_system_prompt = (
        "أنت مساعد ذكي في لوحة تحكم مشرفي \"نَافِذَة\".\n"
        "تحدث بالعربية. افهم الأخطاء الإملائية وصححها.\n"
        "ممنوع استخدام ** أو * أو أي تنسيق Markdown في ردك — اكتب نص فقط.\n"
        "ممنوع كتابة أي تفكير داخلي أو تحليل بالإنگليزية — جاوب مباشرة بالعربية فقط ولا تكتب anything in English.\n\n"
        "⚡ يمكنك تنفيذ الأوامر التالية إذا طلبها المشرف:\n"
        "- [ADD_QA] السؤال | الجواب ← إضافة سؤال/جواب\n"
        "- [DEL_QA] الرقم1 الرقم2 ... ← حذف أسئلة بأرقامها\n"
        "- [ADD_ARTICLE] العنوان | المحتوى ← إضافة مقال\n"
        "- [DEL_ARTICLE] الرقم ← حذف مقال برقمه\n"
        "- [LIST_QA] ← عرض كل الأسئلة\n"
        "- [LIST_ARTICLES] ← عرض كل المقالات\n"
        "- [CLEAR_PREREQS] ← مسح المتطلبات الدراسية\n"
        "- [ADD_PREREQ] كود_المادة | اسم_المادة | كود_المتطلب | اسم_المتطلب\n"
        "- [ADD_FOLDER] اسم المجلد | ID_المجلد_الأب (0 للأب)\n"
        "- [ADD_ITEM] ID_المجلد | عنوان المادة\n"
        "- [ADD_LINK] ID_العنصر | رابط t.me/...\n"
        "- [RENAME_FOLDER] ID | الاسم_الجديد\n"
        "- [RENAME_ITEM] ID | العنوان_الجديد\n"
        "- [UPDATE_LINK] ID | الرابط_الجديد\n"
        "- [DEL_FOLDER] ID\n"
        "- [DEL_ITEM] ID\n"
        "- [DEL_LINK] ID\n"
        "- [LIST_FOLDERS] ← عرض المجلدات والمواد\n"
        "- [BAN] user_id ← حظر مستخدم\n"
        "- [UNBAN] user_id ← إلغاء حظر\n"
        "- [VIEW_MESSAGES] ← عرض رسائل التواصل الواردة\n"
        "- [ADD_ALIAS] الاسم_البديل | كود_المادة | اسم_المادة ← حفظ اسم بديل\n"
        "- [ADD_REPLY] الكلمة | الرد ← إضافة رد سريع\n"
        "- [DEL_REPLY] الرقم ← حذف رد سريع\n"
        "- [LIST_REPLIES] ← عرض كل الردود السريعة\n"
        "- [SEND_TO_ALL] الرسالة ← إرسال رسالة لكل المستخدمين (مع تأكيد)\n"
        "- [SEND_MSG] user_id | الرسالة ← إرسال رسالة لمستخدم معين (مع تأكيد)\n\n"
        "إذا المشرف أعطى أمر مثل 'ضيف سؤال', 'دير هكي', 'حذف مقال 3', "
        "استخدم الأمر المناسب من فوق.\n"
        "إذا كان مجرد كلام أو محادثة، رد طبيعي بدون أكواد.\n"
        "عندما يسألك عن مجلد أو مادة معينة، ابحث في قائمة المجلدات أعلاه.\n\n"
        f"الأسئلة المحفوظة: {qa_context}\n"
        f"المقالات: {art_context}\n"
        f"المتطلبات الدراسية: {prereq_count} علاقة\n"
        f"الأسماء البديلة:\n{aliases_str}\n"
        f"المجلدات:\n{folders_tree[:4000]}"
        f"{history_note}"
    )

    answer = await call_gemini(q, system_prompt=admin_system_prompt)
    if not answer:
        await message.answer("⚠️ فشل.", reply_markup=_rm)
        return

    # Save to history (keep last 5)
    admin_history.append({"user": q, "assistant": answer})
    admin_history = admin_history[-5:]
    await state.update_data(admin_history=admin_history)

    if answer.startswith("[ADD_QA]"):
        parts = answer.replace("[ADD_QA]", "", 1).strip().split("|")
        if len(parts) >= 2:
            qq, aa = parts[0].strip(), "|".join(parts[1:]).strip()
            qa = await add_qa(qq, aa)
            await message.answer(f"✅ تم إضافة سؤال/جواب (رقم {qa.id})", reply_markup=_rm)
        else:
            await message.answer("❌ التنسيق خطأ. استخدم: السؤال | الجواب", reply_markup=_rm)

    elif answer.startswith("[DEL_QA]"):
        parts = answer.replace("[DEL_QA]", "", 1).strip()
        ids = set()
        for token in parts.replace(",", " ").split():
            try:
                ids.add(int(token))
            except ValueError:
                pass
        if not ids:
            await message.answer("❌ أرسل أرقام السؤوال.", reply_markup=cancel_keyboard())
        else:
            deleted = 0
            for qa_id in ids:
                if await delete_qa(qa_id):
                    deleted += 1
            await message.answer(f"✅ تم حذف {deleted} من {len(ids)}", reply_markup=cancel_keyboard())

    elif answer.startswith("[ADD_ARTICLE]"):
        parts = answer.replace("[ADD_ARTICLE]", "", 1).strip().split("|")
        if len(parts) >= 2:
            title, content = parts[0].strip(), "|".join(parts[1:]).strip()
            art = await add_article(title, content)
            await message.answer(f"✅ تم إضافة مقال: {art.title}", reply_markup=cancel_keyboard())
        else:
            await message.answer("❌ التنسيق خطأ. استخدم: العنوان | المحتوى", reply_markup=cancel_keyboard())

    elif answer.startswith("[DEL_ARTICLE]"):
        parts = answer.replace("[DEL_ARTICLE]", "", 1).strip()
        try:
            art_id = int(parts)
            ok = await delete_article(art_id)
            await message.answer(f"✅ تم حذف المقال {art_id}" if ok else "❌ الرقم غير موجود", reply_markup=cancel_keyboard())
        except ValueError:
            await message.answer("❌ أرسل رقم المقال.", reply_markup=cancel_keyboard())

    elif answer.startswith("[LIST_QA]"):
        qa_list = await get_all_qa()
        if qa_list:
            for i in range(0, len(qa_list), 10):
                chunk = "\n".join(f"{qa.id}: 📌 {qa.question[:50]}" for qa in qa_list[i:i+10])
                await message.answer(f"📋 الأسئلة:\n{chunk}", reply_markup=cancel_keyboard())
        else:
            await message.answer("❌ لا توجد أسئلة.", reply_markup=cancel_keyboard())

    elif answer.startswith("[LIST_ARTICLES]"):
        arts = await get_all_articles()
        if arts:
            for art in arts:
                await message.answer(f"🔹 {art.id}: {art.title} ({len(art.content)} حرف)", reply_markup=cancel_keyboard())
        else:
            await message.answer("❌ لا توجد مقالات.", reply_markup=cancel_keyboard())

    elif answer.startswith("[CLEAR_PREREQS]"):
        await clear_prerequisites()
        await message.answer("✅ تم مسح المتطلبات الدراسية.", reply_markup=cancel_keyboard())

    elif answer.startswith("[ADD_PREREQ]"):
        parts = answer.replace("[ADD_PREREQ]", "", 1).strip().split("|")
        if len(parts) >= 4:
            cc, cn, pc, pn = [p.strip() for p in parts[:4]]
            pr = await add_prerequisite(course_code=cc, course_name=cn, prerequisite_code=pc, prerequisite_name=pn)
            await message.answer(f"✅ تم إضافة متطلب: {cn} ← يحتاج {pn}", reply_markup=cancel_keyboard())
        else:
            await message.answer("❌ التنسيق: كود_المادة | اسم_المادة | كود_المتطلب | اسم_المتطلب", reply_markup=cancel_keyboard())

    elif answer.startswith("[ADD_FOLDER]"):
        parts = answer.replace("[ADD_FOLDER]", "", 1).strip().split("|")
        name = parts[0].strip()
        parent_id = None
        if len(parts) >= 2 and parts[1].strip().isdigit():
            pid = int(parts[1].strip())
            parent_id = pid if pid != 0 else None
        f = await add_folder(name, parent_id)
        await message.answer(f"✅ تم إضافة مجلد: {f.name} (ID: {f.id})", reply_markup=cancel_keyboard())

    elif answer.startswith("[ADD_ITEM]"):
        parts = answer.replace("[ADD_ITEM]", "", 1).strip().split("|")
        if len(parts) >= 1 and parts[0].strip().isdigit():
            fid = int(parts[0].strip())
            title = parts[1].strip() if len(parts) >= 2 else None
            ci = await add_content_item(fid, title)
            await message.answer(f"✅ تم إضافة مادة: {ci.title or 'محتوى'} (ID: {ci.id})", reply_markup=cancel_keyboard())
        else:
            await message.answer("❌ التنسيق: ID_المجلد | عنوان المادة", reply_markup=cancel_keyboard())

    elif answer.startswith("[ADD_LINK]"):
        parts = answer.replace("[ADD_LINK]", "", 1).strip().split("|")
        if len(parts) >= 2 and parts[0].strip().isdigit():
            iid = int(parts[0].strip())
            link = parts[1].strip()
            cl = await add_content_link(iid, link)
            await message.answer(f"✅ تم إضافة رابط (ID: {cl.id})", reply_markup=cancel_keyboard())
        else:
            await message.answer("❌ التنسيق: ID_العنصر | الرابط", reply_markup=cancel_keyboard())

    elif answer.startswith("[DEL_FOLDER]"):
        parts = answer.replace("[DEL_FOLDER]", "", 1).strip()
        try:
            fid = int(parts)
            ok = await remove_folder(fid)
            await message.answer(f"✅ تم حذف المجلد {fid}" if ok else "❌ المجلد غير موجود", reply_markup=cancel_keyboard())
        except ValueError:
            await message.answer("❌ أرسل رقم المجلد.", reply_markup=cancel_keyboard())

    elif answer.startswith("[DEL_ITEM]"):
        parts = answer.replace("[DEL_ITEM]", "", 1).strip()
        try:
            iid = int(parts)
            ok = await remove_content_item(iid)
            await message.answer(f"✅ تم حذف المادة {iid}" if ok else "❌ المادة غير موجودة", reply_markup=cancel_keyboard())
        except ValueError:
            await message.answer("❌ أرسل رقم المادة.", reply_markup=cancel_keyboard())

    elif answer.startswith("[DEL_LINK]"):
        parts = answer.replace("[DEL_LINK]", "", 1).strip()
        try:
            lid = int(parts)
            ok = await remove_content_link(lid)
            await message.answer(f"✅ تم حذف الرابط {lid}" if ok else "❌ الرابط غير موجود", reply_markup=cancel_keyboard())
        except ValueError:
            await message.answer("❌ أرسل رقم الرابط.", reply_markup=cancel_keyboard())

    elif answer.startswith("[RENAME_FOLDER]"):
        parts = answer.replace("[RENAME_FOLDER]", "", 1).strip().split("|")
        if len(parts) >= 2 and parts[0].strip().isdigit():
            fid = int(parts[0].strip())
            new_name = parts[1].strip()
            ok = await rename_folder(fid, new_name)
            await message.answer(f"✅ تم إعادة تسمية المجلد {fid} إلى {new_name}" if ok else "❌ المجلد غير موجود", reply_markup=cancel_keyboard())
        else:
            await message.answer("❌ التنسيق: ID | الاسم_الجديد", reply_markup=cancel_keyboard())

    elif answer.startswith("[RENAME_ITEM]"):
        parts = answer.replace("[RENAME_ITEM]", "", 1).strip().split("|")
        if len(parts) >= 2 and parts[0].strip().isdigit():
            iid = int(parts[0].strip())
            title = parts[1].strip()
            ok = await update_content_item_title(iid, title)
            await message.answer(f"✅ تم تحديث عنوان المادة {iid} إلى {title}" if ok else "❌ المادة غير موجودة", reply_markup=cancel_keyboard())
        else:
            await message.answer("❌ التنسيق: ID | العنوان_الجديد", reply_markup=cancel_keyboard())

    elif answer.startswith("[UPDATE_LINK]"):
        parts = answer.replace("[UPDATE_LINK]", "", 1).strip().split("|")
        if len(parts) >= 2 and parts[0].strip().isdigit():
            lid = int(parts[0].strip())
            new_link = parts[1].strip()
            ok = await update_content_link(lid, new_link)
            await message.answer(f"✅ تم تحديث الرابط {lid}" if ok else "❌ الرابط غير موجود", reply_markup=cancel_keyboard())
        else:
            await message.answer("❌ التنسيق: ID | الرابط_الجديد", reply_markup=cancel_keyboard())

    elif answer.startswith("[LIST_FOLDERS]"):
        ft = await _tf()
        if ft:
            for i in range(0, len(ft), 3500):
                await message.answer(f"📂 المجلدات:\n{ft[i:i+3500]}", reply_markup=cancel_keyboard())
        else:
            await message.answer("❌ لا توجد مجلدات.", reply_markup=cancel_keyboard())

    elif answer.startswith("[BAN]"):
        parts = answer.replace("[BAN]", "", 1).strip()
        try:
            uid = int(parts)
            ok = await ban_user(uid)
            await message.answer(f"✅ تم حظر {uid}" if ok else "❌ المستخدم غير موجود", reply_markup=cancel_keyboard())
        except ValueError:
            await message.answer("❌ أرسل رقم المستخدم.", reply_markup=cancel_keyboard())

    elif answer.startswith("[UNBAN]"):
        parts = answer.replace("[UNBAN]", "", 1).strip()
        try:
            uid = int(parts)
            ok = await unban_user(uid)
            await message.answer(f"✅ تم إلغاء حظر {uid}" if ok else "❌ المستخدم غير موجود", reply_markup=cancel_keyboard())
        except ValueError:
            await message.answer("❌ أرسل رقم المستخدم.", reply_markup=cancel_keyboard())

    elif answer.startswith("[VIEW_MESSAGES]"):
        from database.crud import get_unread_messages, save_or_replace_user_message
        msgs = await get_unread_messages()
        if msgs:
            for m in msgs[:10]:
                u = await get_user(m.user_id)
                uname = u.full_name if u else f"ID: {m.user_id}"
                await message.answer(
                    f"💬 من: {uname}\n🆔 {m.user_id}\n{m.content or m.caption or ''}",
                    reply_markup=cancel_keyboard(),
                )
        else:
            await message.answer("📭 لا توجد رسائل واردة.", reply_markup=cancel_keyboard())

    elif answer.startswith("[ADD_ALIAS]"):
        parts = answer.replace("[ADD_ALIAS]", "", 1).strip().split("|")
        if len(parts) >= 3:
            alias_name = parts[0].strip().lower()
            course_code = parts[1].strip()
            course_name = parts[2].strip()
            ca = await add_alias(alias_name, course_code, course_name)
            await message.answer(f"✅ تم حفظ: '{alias_name}' ← {course_name} ({course_code})", reply_markup=cancel_keyboard())
        else:
            await message.answer("❌ التنسيق: الاسم_البديل | كود_المادة | اسم_المادة", reply_markup=cancel_keyboard())

    elif answer.startswith("[ADD_REPLY]"):
        parts = answer.replace("[ADD_REPLY]", "", 1).strip().split("|")
        if len(parts) >= 2:
            trigger, response = parts[0].strip(), "|".join(parts[1:]).strip()
            ar = await add_autoreply(trigger, response)
            await message.answer(f"✅ تم إضافة رد سريع (رقم {ar.id}): {trigger}", reply_markup=_rm)
        else:
            await message.answer("❌ التنسيق: الكلمة | الرد", reply_markup=_rm)

    elif answer.startswith("[DEL_REPLY]"):
        parts = answer.replace("[DEL_REPLY]", "", 1).strip()
        try:
            rid = int(parts)
            ok = await remove_autoreply(rid)
            await message.answer(f"✅ تم حذف الرد السريع {rid}" if ok else "❌ الرقم غير موجود", reply_markup=_rm)
        except ValueError:
            await message.answer("❌ أرسل رقم الرد.", reply_markup=_rm)

    elif answer.startswith("[LIST_REPLIES]"):
        replies = await get_all_autoreplies()
        if replies:
            lines = [f"{ar.id}: {ar.trigger} ← {ar.response[:50]}" for ar in replies]
            for i in range(0, len(lines), 10):
                chunk = "\n".join(lines[i:i+10])
                await message.answer(f"📋 الردود السريعة:\n{chunk}", reply_markup=_rm)
        else:
            await message.answer("❌ لا توجد ردود سريعة.", reply_markup=_rm)

    elif answer.startswith("[SEND_TO_ALL]"):
        text = answer.replace("[SEND_TO_ALL]", "", 1).strip()
        if not text:
            await message.answer("❌ أرسل نص الرسالة.", reply_markup=_rm)
        else:
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ تأكيد الإرسال", callback_data="broadcast:confirm"),
                 InlineKeyboardButton(text="❌ إلغاء", callback_data="broadcast:cancel")]
            ])
            from aiogram.fsm.context import FSMContext
            await state.update_data(broadcast_content={"type": "text", "text": text})
            await message.answer(
                f"📢 معاينة الرسالة:\n\n{text[:300]}\n\nهل أنت متأكد من إرسالها لكل المستخدمين؟",
                reply_markup=kb,
            )

    elif answer.startswith("[SEND_MSG]"):
        parts = answer.replace("[SEND_MSG]", "", 1).strip().split("|")
        if len(parts) >= 2 and parts[0].strip().isdigit():
            uid = int(parts[0].strip())
            msg = "|".join(parts[1:]).strip()
            user = await get_user(uid)
            uname = user.full_name if user else str(uid)
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ تأكيد الإرسال", callback_data=f"sendmsg:confirm:{uid}"),
                 InlineKeyboardButton(text="❌ إلغاء", callback_data="sendmsg:cancel")]
            ])
            await state.update_data(sendmsg_text=msg)
            await message.answer(
                f"📩 رسالة إلى {uname} ({uid}):\n\n{msg[:300]}\n\nهل أنت متأكد؟",
                reply_markup=kb,
            )
        else:
            await message.answer("❌ التنسيق: user_id | الرسالة", reply_markup=_rm)

    else:
        clean = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL).strip()
        clean = re.sub(r"<[^>]+>", "", clean)
        clean = clean.replace("**", "")
        gen_match = re.search(r"\[Output Generation\].*?->\s*\"?(.*)", clean, re.DOTALL)
        if gen_match:
            clean = gen_match.group(1).strip().rstrip('"')
        else:
            paragraphs = re.split(r"\n\s*\n", clean)
            answer_parts = []
            for p in paragraphs:
                stripped = p.strip()
                if not stripped:
                    continue
                arabic_count = len(re.findall(r"[\u0600-\u06FF]", stripped))
                total = len(stripped)
                arabic_ratio = arabic_count / total if total > 0 else 0
                is_thinking = (
                    re.match(r"^\d+\.\s", stripped)
                    or re.match(r"^-\s", stripped)
                    or stripped.startswith("Here")
                    or stripped.startswith("Let")
                    or stripped.startswith("Wait")
                    or stripped.startswith("I'll")
                    or arabic_ratio < 0.3
                )
                if not is_thinking:
                    answer_parts.append(stripped)
            clean = "\n\n".join(answer_parts) if answer_parts else clean
        await safe_send(message, clean, reply_markup=_rm)


# ─── Admin: إضافة مقال/إعلان ───

@router.message(AdminFilter(), F.text == "📰 إضافة مقال")
async def ai_admin_article_title(message: Message, state: FSMContext) -> None:
    await state.set_state(AIAdminState.waiting_article_title)
    await message.answer(
        "✏️ أرسل عنوان المقال أو الإعلان (مثال: تنويه نتائج الامتحانات):\n\n"
        "أو أرسل كلمة (لا) ليقوم المساعد بتوليد عنوان مناسب.",
        reply_markup=cancel_keyboard(),
    )


@router.message(AIAdminState.waiting_article_title, AdminFilter())
async def ai_admin_article_text_prompt(message: Message, state: FSMContext) -> None:
    title = message.text.strip()
    if title.lower() in ("لا", "لأ", "no"):
        title = ""
    await state.update_data(article_title=title)
    await state.set_state(AIAdminState.waiting_article_text)
    await message.answer(
        "📝 أرسل نص المقال أو الإعلان كاملاً:\n\n"
        "مثال: نقلاً عن م.محمد حموده، تنويه هام... إلخ",
        reply_markup=cancel_keyboard(),
    )


@router.message(AIAdminState.waiting_article_text, AdminFilter())
async def ai_admin_article_save(message: Message, state: FSMContext) -> None:
    text = message.text or message.caption or ""
    if not text or len(text) < 20:
        await message.answer("❌ النص قصير جداً. أرسل المحتوى كاملاً.")
        return

    data = await state.get_data()
    title = data.get("article_title", "")

    # Generate title if not provided
    if not title:
        await message.answer("🤔 جاري توليد عنوان مناسب...")
        gen = await call_gemini(
            f"اقرأ هذا النص واستخرج منه عنواناً مناسباً (جملة واحدة فقط، لا تزد):\n\n{text[:2000]}"
        )
        title = gen.strip().strip('"').strip("'") if gen else "مقال"
        if len(title) > 200:
            title = title[:200]

    article = await add_article(title, text)
    await state.clear()
    await message.answer(
        f"✅ تم حفظ المقال بنجاح:\n\n📰 {article.title}\n📝 {len(text)} حرف\n\n"
        "عندما يسأل الطالب سؤالاً متعلقاً بهذا المقال، سيقوم المساعد بالبحث والإجابة تلقائياً.",
        reply_markup=ai_admin_keyboard(),
    )


@router.message(AdminFilter(), F.text == "📋 عرض المقالات")
async def ai_admin_view_articles(message: Message, state: FSMContext) -> None:
    articles = await get_all_articles()
    if not articles:
        await message.answer("❌ لا توجد مقالات.", reply_markup=ai_admin_keyboard())
        return
    lines = []
    for a in articles:
        c = a.content[:80].replace("\n", " ")
        lines.append(f"🔹 {a.id}: {a.title}\n   📝 {c}…")
    for i in range(0, len(lines), 5):
        chunk = "\n\n".join(lines[i:i+5])
        await message.answer(f"📋 المقالات:\n\n{chunk}")
    await message.answer(
        "لحذف مقال أرسل: حذف [الرقم]\n"
        "لعرض مقال كامل أرسل: عرض [الرقم]\n"
        "مثال: عرض 3",
        reply_markup=ai_admin_keyboard(),
    )


@router.message(AdminFilter(), F.text.startswith("حذف "))
async def ai_admin_delete_article(message: Message, state: FSMContext) -> None:
    text = message.text.strip()
    parts = text.split()
    if len(parts) < 2:
        return
    ids = set()
    for p in parts[1:]:
        try:
            ids.add(int(p))
        except ValueError:
            pass
    if not ids:
        return
    deleted = 0
    for art_id in ids:
        if await delete_article(art_id):
            deleted += 1
    await message.answer(
        f"✅ تم حذف {deleted} من {len(ids)} مقال" if deleted else "❌ لم يتم حذف أي مقال",
        reply_markup=ai_admin_keyboard(),
    )


@router.message(AdminFilter(), F.text.startswith("عرض "))
async def ai_admin_view_article_full(message: Message, state: FSMContext) -> None:
    parts = message.text.strip().split()
    if len(parts) < 2:
        return
    try:
        art_id = int(parts[1])
    except ValueError:
        return
    articles = await get_all_articles()
    target = next((a for a in articles if a.id == art_id), None)
    if not target:
        await message.answer("❌ المقال غير موجود.", reply_markup=ai_admin_keyboard())
        return
    text = f"🔹 {target.id}: {target.title}\n\n{target.content}"
    from aiogram.enums import ParseMode
    if len(text) > 4000:
        for i in range(0, len(text), 4000):
            await message.answer(text[i:i+4000], reply_markup=ai_admin_keyboard() if i == 0 else None)
    else:
        await message.answer(text, reply_markup=ai_admin_keyboard())


# ─── المتطلبات الدراسية (تُستخرج تلقائياً من تحليل ذكي) ───

async def _ai_admin_parse_prereqs(message: Message, state: FSMContext) -> None:
    """Parse prerequisites text and save extracted relationships."""
    text = message.text or ""
    if len(text) < 20:
        await message.answer("❌ النص قصير جداً.")
        return

    await message.answer("🤔 جاري تحليل الشجرة واستخراج العلاقات...")
    await clear_prerequisites()

    prompt = (
        "استخرج من النص التالي علاقات المتطلبات الدراسية ( prerequisite relationships ).\n"
        "النص يصف مواد دراسية و المواد التي تفتحها (تفتح = prerequisite for).\n"
        "أعد النتيجة بهذا التنسيق بالضبط:\n"
        "---\n"
        "المادة: اسم المادة (رمزها)\n"
        "تفتح: اسم المادة المفتوحة (رمزها)\n"
        "---\n"
        "المادة: اسم المادة (رمزها)\n"
        "تفتح: اسم المادة المفتوحة (رمزها)\n"
        "---\n\n"
        f"النص:\n{text}"
    )
    answer = await call_gemini(prompt)
    if not answer:
        await message.answer("⚠️ فشل التحليل.", reply_markup=ai_admin_keyboard())
        await state.clear()
        return

    import re
    pattern = r"المادة:\s*(.+?)\s*\(([^)]+)\)\s*\nتفتح:\s*(.+?)\s*\(([^)]+)\)"
    matches = re.findall(pattern, answer)
    if not matches:
        await message.answer("⚠️ لم أستطع استخراج العلاقات. أرسل النص بشكل أوضح.", reply_markup=ai_admin_keyboard())
        await state.clear()
        return

    count = 0
    for course_name, course_code, prereq_name, prereq_code in matches:
        await add_prerequisite(
            course_code=course_code.strip(),
            course_name=course_name.strip(),
            prerequisite_code=prereq_code.strip(),
            prerequisite_name=prereq_name.strip(),
        )
        count += 1

    await state.clear()
    summary_lines = []
    for course_name, course_code, prereq_name, prereq_code in matches[:20]:
        summary_lines.append(f"🔸 {course_name.strip()} ({course_code.strip()}) ← يحتاج {prereq_name.strip()} ({prereq_code.strip()})")
    summary = "\n".join(summary_lines)
    msg = f"✅ تم حفظ {count} علاقة:\n\n{summary}\n\n"
    if count > 20:
        msg += f"...و {count - 20} علاقة أخرى\n\n"
    msg += "الآن عندما يسأل الطالب عن متطلبات مادة أو مواد تفتحها مادة، سيجيب المساعد تلقائياً."
    await message.answer(msg, reply_markup=ai_admin_keyboard())


# ─── AI send message callbacks ───

@router.callback_query(AdminFilter(), F.data.startswith("sendmsg:confirm:"))
async def ai_sendmsg_confirm(callback: CallbackQuery, state: FSMContext) -> None:
    uid = int(callback.data.split(":")[2])
    data = await state.get_data()
    text = data.get("sendmsg_text", "")
    await callback.message.edit_reply_markup(reply_markup=None)
    try:
        await callback.bot.send_message(chat_id=uid, text=text)
        await callback.message.answer(f"✅ تم إرسال الرسالة إلى {uid}.")
    except Exception as e:
        await callback.message.answer(f"⚠️ فشل الإرسال: {str(e)[:100]}")
    await callback.answer()


@router.callback_query(AdminFilter(), F.data == "sendmsg:cancel")
async def ai_sendmsg_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("❌ تم إلغاء الإرسال.")
    await callback.answer()
