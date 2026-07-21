import logging
import re
import aiohttp
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from filters import AdminFilter
from database.crud import (add_qa, delete_qa, get_all_qa, save_pdf_context, delete_pdf_context, get_all_pdfs,
                           get_folder, get_content_items, get_folders, get_content_links,
                           add_article, delete_article, get_all_articles, get_all_prerequisites,
                           clear_prerequisites, add_prerequisite, is_ai_active,
                           add_folder, remove_folder, add_content_item, remove_content_item,
                           add_content_link, remove_content_link, ban_user, unban_user, get_user)
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
    waiting_article_title = State()
    waiting_article_text = State()
    waiting_prereqs = State()


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
        await message.answer("🛑 المساعد الذكي متوقف حالياً. حاول لاحقاً.", reply_markup=main_keyboard())
        return
    await state.set_state(AIState.waiting_for_question)
    await state.update_data(history=[])
    await message.answer(
        "مرحباً بك في نَافِذَة الـ AI!\n"
        "أنا نموذج ذكاء اصطناعي مُطوّر لبوت نَافِذَة، أعمل على معالجة أسئلتك ومساعدتك في كافة استفساراتك الجامعية خطوة بخطوة.\n"
        "تفضل بكتابة سؤالك وسأجيبك فوراً!\n\n"
        "أو استخدم 🔙 رجوع للعودة.",
        reply_markup=ai_user_keyboard(),
    )


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
        err_msg = str(e)[:200] or "خطأ غير معروف"
        try:
            await message.answer(
                f"⚠️ حدث خطأ: {err_msg}\n\nحاول مرة أخرى أو استخدم 🔙 رجوع.",
                reply_markup=ai_user_keyboard(),
            )
        except Exception:
            pass
        for admin_id in settings.admin_ids:
            try:
                await message.bot.send_message(admin_id, f"⚠️ خطأ في AI:\n<code>{tb[:3500]}</code>")
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
    if len(materials_context) > 3000:
        materials_context = materials_context[:3000] + "\n... (يوجد المزيد)"

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
        "أنت مساعد ذكي خاص بـ\"نَافِذَة\" — وهي منصة كلية. "
        "اسمك \"مساعد نافذة\". عندما يُسأل من أنت، قل: \"أنا مساعد نافذة الذكي، هنا لمساعدتك في كل ما يخص الكلية والمواد الدراسية.\"\n\n"
        "تتحدث بالعربية بأسلوب ودود ومفيد.\n\n"
        "ممنوع استخدام ** أو * أو أي تنسيق Markdown في ردك — اكتب نص فقط.\n"
        "ممنوع كتابة أي تفكير داخلي أو تحليل بالإنگليزية — جاوب مباشرة بالعربية فقط ولا تكتب anything in English.\n\n"
        f"{history_note}"
        f"📚 قاعدة المعرفة (الأسئلة والأجوبة):\n{qa_context}\n\n"
        f"📁 المواد المتاحة:\n{materials_context}\n\n"
        f"📰 المقالات والتنويهات:\n{articles_context}\n\n"
        f"🔗 شجرة المتطلبات الدراسية:\n{prereqs_context}\n\n"
        "📌 تعليمات:\n"
        "- أنت تفهم الأسئلة بطبيعة — الطالب يسأل بأي صيغة، وأنت تفهم قصده حتى لو فيه أخطاء إملائية.\n"
        "- صحح الأخطاء الإملائية البسيطة وافهم السؤال.\n"
        "- أي سؤال عن مواد كلية، متطلبات، شيتات، ملخصات، كتب، امتحانات — استخدم الشجرة الكاملة للمواد بالأسفل.\n"
        "- الشجرة تبين لك كل مجلد وكل ملف وروابطه — ابحث فيها جيداً قبل الرد.\n"
        "- المقالات والتنويهات المحفوظة تحتوي إعلانات رسمية — اعتمد عليها بالإجابة عن المواعيد والإعلانات.\n"
        "- المواد والروابط الموجودة في الشجرة — إذا سألك عن مادة اذكر اسم المادة والروابط (t.me/...) في ردك. الـ links اللي تكتبها في الرد، النظام بيحولها تلقائياً كملفات.\n"
        "- إذا كانت الإجابة موجودة، جاوب بثقة.\n"
        "- إذا السؤال عن شيء خارج الكلية، جاوب طبيعي.\n"
        "- **الأهم**: إذا ما لقيت الإجابة في السياق أو المستخدم طلب شيء يحتاج مشرف (تسجيل، تغيير، إضافة، استفسار خاص، شكوى، طلب مادة غير موجودة)، "
        "قل حرفياً: 'سأبلغ المشرفين 📢' وأخبرهم بالطلب."
    )

    user_prompt = q

    answer = await call_gemini(user_prompt, system_prompt=system_prompt)
    if answer:
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
            except Exception:
                pass
        # Strip Telegram links from displayed text (files already forwarded)
        clean_answer = re.sub(r"https?://t\.me/\S+", "", answer).strip()
        # Remove content inside <think> tags (reasoning output) first
        clean_answer = re.sub(r"<think>.*?</think>", "", clean_answer, flags=re.DOTALL).strip()
        # Then strip any remaining HTML tags
        clean_answer = re.sub(r"<[^>]+>", "", clean_answer)
        # Strip markdown bold markers ** **
        clean_answer = clean_answer.replace("**", "")
        # Strip CoT: find [Output Generation] marker (most reliable for this model)
        gen_match = re.search(r"\[Output Generation\].*?->\s*\"?(.*)", clean_answer, re.DOTALL)
        if gen_match:
            clean_answer = gen_match.group(1).strip().rstrip('"')
        else:
            # Fallback: find last termination marker
            for marker in ["Proceeds.", "Ready.", "All good.", "Output matches"]:
                idx = clean_answer.rfind(marker)
                if idx != -1:
                    after = clean_answer[idx + len(marker):].strip()
                    if after:
                        clean_answer = after
                        break
            else:
                # Last resort: strip from first Arabic char
                m = re.search(r"[\u0600-\u06FF]", clean_answer)
                if m:
                    clean_answer = clean_answer[m.start():].strip()
        # Clean up double spaces / empty lines
        clean_answer = re.sub(r"\n{3,}", "\n\n", clean_answer)
        if clean_answer:
            await message.answer(clean_answer, reply_markup=ai_user_keyboard())
        # Save to history
        history.append({"user": q, "assistant": answer})
        await state.update_data(history=history)
        # Notify admins if needed
        needs_admin = (
            "سأبلغ المشرفين" in answer
            or "📢" in answer
            or "إشعار المشرفين" in answer
        )
        # Also check user question for direct requests
        user_needs_admin = any(w in q for w in [
            "قول للمشرف", "بلغ المشرف", "كلم المشرف", "شكوى",
            "دير", "سوي", "اعمل", "غير", "ضيف", "زيد", "نقص",
            "ابلغ", "المشرفين", "للإدارة", "الادارة",
        ])
        if needs_admin or user_needs_admin:
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
        err_msg = str(e)[:300] or "خطأ غير معروف"
        await message.answer(f"⚠️ حدث خطأ: {err_msg}", reply_markup=cancel_keyboard())
        for admin_id in settings.admin_ids:
            try:
                await message.bot.send_message(admin_id, f"⚠️ خطأ في AI:\n<code>{tb[:3500]}</code>")
            except Exception:
                pass


async def _ai_admin_chat_message(message: Message, state: FSMContext) -> None:
    q = message.text or message.caption or ""
    if not q:
        return

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
        "- [DEL_FOLDER] ID\n"
        "- [DEL_ITEM] ID\n"
        "- [DEL_LINK] ID\n"
        "- [LIST_FOLDERS] ← عرض المجلدات والمواد\n"
        "- [BAN] user_id ← حظر مستخدم\n"
        "- [UNBAN] user_id ← إلغاء حظر\n"
        "- [VIEW_MESSAGES] ← عرض رسائل التواصل الواردة\n\n"
        "إذا المشرف أعطى أمر مثل 'ضيف سؤال', 'دير هكي', 'حذف مقال 3', "
        "استخدم الأمر المناسب من فوق.\n"
        "إذا كان مجرد كلام أو محادثة، رد طبيعي بدون أكواد.\n\n"
        f"الأسئلة المحفوظة: {qa_context}\n"
        f"المقالات: {art_context}\n"
        f"المتطلبات الدراسية: {prereq_count} علاقة\n"
        f"المجلدات:\n{folders_tree[:2000]}"
    )

    answer = await call_gemini(q, system_prompt=admin_system_prompt)
    if not answer:
        await message.answer("⚠️ فشل.", reply_markup=cancel_keyboard())
        return

    if answer.startswith("[ADD_QA]"):
        parts = answer.replace("[ADD_QA]", "", 1).strip().split("|")
        if len(parts) >= 2:
            qq, aa = parts[0].strip(), "|".join(parts[1:]).strip()
            qa = await add_qa(qq, aa)
            await message.answer(f"✅ تم إضافة سؤال/جواب (رقم {qa.id})", reply_markup=cancel_keyboard())
        else:
            await message.answer("❌ التنسيق خطأ. استخدم: السؤال | الجواب", reply_markup=cancel_keyboard())

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

    else:
        clean = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL).strip()
        clean = re.sub(r"<[^>]+>", "", clean)
        clean = clean.replace("**", "")
        gen_match = re.search(r"\[Output Generation\].*?->\s*\"?(.*)", clean, re.DOTALL)
        if gen_match:
            clean = gen_match.group(1).strip().rstrip('"')
        else:
            m = re.search(r"[\u0600-\u06FF]", clean)
            if m:
                clean = clean[m.start():].strip()
        await message.answer(clean, reply_markup=cancel_keyboard())


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
        "لحذف مقال أرسل: حذف [الرقم]\nمثال: حذف 3\nأو لحذف عدة: حذف 3 5 7",
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


# ─── Admin: المتطلبات الدراسية ───

@router.message(AdminFilter(), F.text == "🔗 المتطلبات الدراسية")
async def ai_admin_prereqs_start(message: Message, state: FSMContext) -> None:
    await message.answer(
        "🔗 أرسل شجرة المتطلبات الدراسية كما هي (نصاً)، وسأقوم باستخراج العلاقات وحفظها.\n\n"
        "مثال:\n"
        "مقدمة في تقنية المعلومات (ITGS111)\n"
        "تفتح: مقدمة في هندسة البرمجيات (ITGS213)\n\n"
        "أو أرسل (عرض) لرؤية المحفوظ، أو (مسح) لحذف الكل.",
        reply_markup=cancel_keyboard(),
    )
    await state.set_state(AIAdminState.waiting_prereqs)


@router.message(AdminFilter(), AIAdminState.waiting_prereqs, F.text.lower().strip() == "عرض")
async def ai_admin_prereqs_view(message: Message, state: FSMContext) -> None:
    await state.clear()
    prereqs = await get_all_prerequisites()
    if not prereqs:
        await message.answer("❌ لا توجد متطلبات دراسية محفوظة.", reply_markup=ai_admin_keyboard())
        return
    lines = []
    for p in prereqs:
        lines.append(f"🔸 {p.course_name} ({p.course_code}) ← يحتاج {p.prerequisite_name} ({p.prerequisite_code})")
    for i in range(0, len(lines), 15):
        chunk = "\n".join(lines[i:i+15])
        await message.answer(f"🔗 المتطلبات الدراسية:\n\n{chunk}", reply_markup=ai_admin_keyboard())
    await message.answer(f"📊 المجموع: {len(prereqs)} علاقة", reply_markup=ai_admin_keyboard())


@router.message(AdminFilter(), AIAdminState.waiting_prereqs, F.text.lower().strip() == "مسح")
async def ai_admin_prereqs_clear(message: Message, state: FSMContext) -> None:
    await state.clear()
    await clear_prerequisites()
    await message.answer("✅ تم مسح جميع المتطلبات الدراسية.", reply_markup=ai_admin_keyboard())


@router.message(AdminFilter(), AIAdminState.waiting_prereqs)
async def ai_admin_prereqs_parse(message: Message, state: FSMContext) -> None:
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
    await message.answer(
        f"✅ تم حفظ {count} علاقة prerequisite بنجاح.\n\n"
        "الآن عندما يسأل الطالب عن متطلبات مادة أو مواد تفتحها مادة، سيجيب المساعد تلقائياً.",
        reply_markup=ai_admin_keyboard(),
    )

async def _call_groq_vision(prompt: str, image_b64: str) -> str | None:
    keys = settings.groq_keys
    if not keys:
        return None
    api_key = keys[0]
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
