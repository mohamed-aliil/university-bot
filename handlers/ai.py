import logging
import re
import asyncio
import time
import aiohttp
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardMarkup, ReplyKeyboardMarkup
from filters import AdminFilter
from database.crud import (add_qa, update_qa, delete_qa, get_all_qa, save_pdf_context, delete_pdf_context, get_all_pdfs,
                           get_folder, get_content_items, get_folders, get_content_links,
                           add_article, update_article, delete_article, get_all_articles, get_all_prerequisites,
                             clear_prerequisites, add_prerequisite, is_ai_active, is_ai_silent, set_ai_active,
                             add_folder, remove_folder, rename_folder, add_content_item, remove_content_item,
                             update_content_item_title, add_content_link, remove_content_link, update_content_link,
                             ban_user, unban_user, get_user, add_alias,
                             get_all_aliases, has_agreed_ai, set_agreed_ai, log_ai_action,
                             add_autoreply, remove_autoreply, get_all_autoreplies, get_all_users, get_all_materials,
                             get_stats, get_all_user_messages, get_admin_permissions, save_admin_action)
from keyboards.reply import ai_admin_keyboard, ai_qa_keyboard, ai_articles_keyboard, ai_user_keyboard, main_keyboard, cancel_keyboard, smart_mode_keyboard, agreement_keyboard
from services.gemini import call_gemini, call_groq_vision
from services.ai_context import get_cached_context, clear_ai_context
from config import settings

logger = logging.getLogger(__name__)
router = Router()

MAX_MSG_LEN = 4000  # Leave room for safety

LINK_REGEX = re.compile(r"(?:https?://)?t\.me/(c/)?([a-zA-Z_]\w+|\d+)/(\d+)")


def _resolve_channel_chat_id(ch: str, is_private_c: bool = False) -> int | str:
    """Convert stored channel_username or regex group into a valid Bot API chat_id."""
    ch = (ch or "").strip()
    if ch.startswith("-100") and ch[4:].isdigit():
        return int(ch)
    if ch.startswith("-") and ch[1:].isdigit():
        return int(ch)
    if ch.isdigit():
        return int(f"-100{ch}")
    if is_private_c and ch.lstrip("-").isdigit():
        return int(f"-100{ch.lstrip('-')}")
    return ch if ch.startswith("@") else f"@{ch}"


def _extract_pdf_text(file_path: str) -> str:
    """Extract readable text from a PDF file using PyMuPDF (fitz), with a .txt sidecar cache."""
    import os
    if not file_path:
        return ""
    txt_cache = f"{file_path}.txt"
    if os.path.exists(txt_cache):
        try:
            with open(txt_cache, "r", encoding="utf-8", errors="ignore") as tf:
                cached = tf.read().strip()
            if cached:
                return cached
        except Exception:
            pass
    if not os.path.exists(file_path):
        return ""
    try:
        import fitz
        pages_text = []
        with fitz.open(file_path) as doc_pdf:
            for page in doc_pdf:
                t = page.get_text()
                if t:
                    pages_text.append(t.strip())
        full_text = "\n".join(pages_text).strip()
        if full_text:
            try:
                with open(txt_cache, "w", encoding="utf-8") as tf:
                    tf.write(full_text)
            except Exception:
                pass
        return full_text
    except Exception as e:
        logger.warning("AI: fitz PDF extraction failed for %s: %s", file_path, e)
        return ""


def _normalize_ar(text: str) -> str:
    """Normalize Arabic/English text for keyword matching."""
    if not text:
        return ""
    t = text.lower()
    t = re.sub(r"[\u064B-\u065F\u0640]", "", t)  # strip tashkeel & tatweel
    t = re.sub(r"[أإآ]", "ا", t)
    t = t.replace("ة", "ه").replace("ى", "ي")
    return t


_DIALECT_SYNONYMS: dict[str, list[str]] = {
    "قداش": ["كم", "عدد", "درجه", "وحدات", "نسبه", "ساعات", "معدل"],
    "بكم": ["كم", "درجه", "وحدات", "ساعات"],
    "امتي": ["متي", "موعد", "تاريخ", "وقت", "امتحان", "جدول"],
    "امتا": ["متي", "موعد", "تاريخ", "وقت", "امتحان", "جدول"],
    "فوقاش": ["متي", "موعد", "تاريخ", "وقت"],
    "وين": ["مكان", "قاعه", "مدرج", "قسم", "موقع"],
    "شن": ["ما", "ماذا", "شروط", "متطلبات"],
    "شنو": ["ما", "ماذا", "شروط", "متطلبات"],
    "شني": ["ما", "ماذا", "شروط", "متطلبات"],
    "يفتح": ["تفتح", "متطلب", "تمهيدي"],
    "تفتحلي": ["تفتح", "متطلب", "مواد"],
    "يحتاج": ["تحتاج", "متطلب", "قبلي"],
    "تحتاج": ["متطلب", "قبلي", "تفتح"],
    "سيمستر": ["فصل", "دراسي", "سمستر", "خريف", "ربيع"],
    "سمستر": ["فصل", "دراسي", "سيمستر", "خريف", "ربيع"],
    "ترم": ["فصل", "دراسي", "سمستر"],
    "تنزيل": ["تسجيل", "مواد", "وحدات", "منظومه", "اضافه"],
    "منظومه": ["تسجيل", "تنزيل", "نتائج", "مواد"],
    "اسقاط": ["سحب", "حذف", "انسحاب", "وقف", "قيد"],
    "شيت": ["شيتات", "ملف", "ملفات", "محاضرات", "منهج"],
    "شيتات": ["شيت", "ملف", "ملفات", "محاضرات", "منهج"],
    "ملخص": ["شيت", "ملفات", "محاضرات", "مراجعه"],
    "نصفي": ["ميد", "اعمال", "سنه", "امتحان", "درجات"],
    "ميد": ["نصفي", "اعمال", "سنه", "امتحان"],
    "فاينل": ["نهائي", "امتحان", "درجات"],
    "فاينال": ["نهائي", "امتحان", "درجات"],
    "طاح": ["رسوب", "اعاده", "انذار", "نجاح"],
    "رسبت": ["رسوب", "اعاده", "انذار", "فصل"],
    "صفي": ["نجاح", "اجتياز", "تخرج", "وحدات"],
    "كالكولس": ["رياضيات", "تفاضل", "تكامل", "حسبان", "math", "ma"],
    "كالكلس": ["رياضيات", "تفاضل", "تكامل", "حسبان", "math", "ma"],
    "حسبان": ["رياضيات", "تفاضل", "تكامل", "كالكولس"],
    "سي": ["برمجه", "حاسوب", "c++", "cs"],
    "بلس": ["برمجه", "حاسوب", "c++", "cs"],
    "بروجرامينج": ["برمجه", "حاسوب", "cs"],
    "داتا": ["هياكل", "تراكيب", "بيانات", "data"],
    "ديسكريت": ["متقطعه", "رياضيات", "discrete"],
    "فيزيا": ["فيزياء", "طبيعه", "phys", "ph"],
    "طبيعه": ["فيزياء", "فيزيا", "ph"],
    "سيركت": ["دوائر", "كهربائيه", "ee"],
    "استاتيكا": ["ميكانيكا", "استاتيكا", "ge"],
    "داينميكا": ["ميكانيكا", "ديناميكا", "ge"],
    "انجليزي": ["انجليزيه", "لغه", "en"],
    "انقلش": ["انجليزيه", "لغه", "en"],
}


def _extract_query_keywords(q: str, history: list[dict], alias_items: list[tuple[str, str, str]]) -> set[str]:
    """Extract normalized keywords from user question, recent 5 turns (user + assistant), dialect synonyms, and matched course aliases."""
    combined = q or ""
    for turn in (history or [])[-5:]:
        combined += " " + (turn.get("user") or "")
        combined += " " + (turn.get("assistant") or "")[:250]
    norm = _normalize_ar(combined)
    words = {w for w in re.findall(r"[\w\u0600-\u06FF]{2,}", norm) if len(w) >= 2}
    stop_words = {
        "من", "في", "على", "الى", "عن", "مع", "هل", "ما", "ماذا", "كيف",
        "اللي", "هذا", "هذه", "ان", "كان", "لو", "او", "ام", "كل", "بس",
        "فيه", "فيها", "عندي", "نبي", "ابغي", "اريد", "ممكن", "سؤال", "يا",
        "نافذه", "بوت", "الجامعه", "الكليه", "طالب", "طلبه", "شن", "شنو", "شني",
        "مساعد", "الذكي", "حاليا", "بيانات", "معلومه", "استفسار", "تتوفر", "لدي",
    }
    keywords = words - stop_words
    expanded = set(keywords)
    for w in list(words):
        for syn in _DIALECT_SYNONYMS.get(w, ()):
            expanded.add(_normalize_ar(syn))
    for alias, code, cname in (alias_items or []):
        na = _normalize_ar(alias)
        if na and na in norm:
            for extra in re.findall(r"[\w\u0600-\u06FF]{2,}", _normalize_ar(f"{code} {cname}")):
                expanded.add(extra)
    return expanded


def _select_relevant_context(q: str, history: list[dict], ctx: dict, max_articles_chars: int = 32000, compact: bool = False) -> dict:
    """Prioritize articles, Q&A, materials, prerequisites, and PDFs that match the student's question."""
    keywords = _extract_query_keywords(q, history, ctx.get("alias_items", []))

    def _score_text(title_or_q: str, body: str) -> int:
        if not keywords:
            return 0
        nt = _normalize_ar(title_or_q)
        nb = _normalize_ar(body)
        score = 0
        for kw in keywords:
            if kw in nt:
                score += 4
            if kw in nb:
                score += 1
        return score

    qa_limit = 900 if compact else 10000
    mat_limit = 900 if compact else 12000
    pre_limit = 600 if compact else 8000
    pdf_limit = 600 if compact else 12000

    # 1) Prioritize Q&A pairs
    qa_items = ctx.get("qa_items") or []
    if qa_items:
        scored_qa = sorted(
            enumerate(qa_items),
            key=lambda pair: (_score_text(pair[1][0], pair[1][1]), -pair[0]),
            reverse=True,
        )
        qa_lines = [f"س: {qq}\nج: {aa}" for _, (qq, aa) in scored_qa]
        qa_context = "\n\n".join(qa_lines)
        if len(qa_context) > qa_limit:
            qa_context = qa_context[:qa_limit] + "\n... (بقية الأسئلة الشائعة)"
    else:
        qa_context = ctx.get("qa", "لا توجد أسئلة مضافة بعد.")[:qa_limit]

    # 2) Prioritize Articles (full content for matched articles first!)
    article_items = ctx.get("article_items") or []
    if article_items:
        all_titles = "، ".join(f"[{aid}] {title}" for aid, title, _ in article_items)
        if compact and len(all_titles) > 400:
            all_titles = all_titles[:400] + "..."
        scored_arts = sorted(
            article_items,
            key=lambda item: (_score_text(item[1], item[2]), item[0]),
            reverse=True,
        )
        art_blocks = [f"📌 فهرس عناوين المقالات: {all_titles}\n"]
        used_chars = len(art_blocks[0])
        per_art_max = 1800 if compact else 12000
        for aid, title, content in scored_arts:
            clean_c = (content or "").strip()
            block = f"---\n📰 مقال ({aid}) {title}:\n{clean_c[:per_art_max]}\n"
            if used_chars + len(block) > max_articles_chars:
                remaining = max_articles_chars - used_chars
                if remaining > 250:
                    art_blocks.append(block[:remaining] + "...")
                break
            art_blocks.append(block)
            used_chars += len(block)
        articles_context = "\n".join(art_blocks)
    else:
        articles_context = "لا توجد مقالات مضافة بعد."

    # 3) Filter/prioritize Materials tree when in compact mode
    raw_materials = ctx.get("materials", "لا توجد مواد بعد.")
    if compact and len(raw_materials) > mat_limit and keywords:
        mat_lines = raw_materials.splitlines()
        matched_mat = [ln for ln in mat_lines if any(kw in _normalize_ar(ln) for kw in keywords)]
        if matched_mat:
            materials_context = "\n".join(matched_mat)[:mat_limit]
        else:
            materials_context = raw_materials[:mat_limit] + "\n..."
    else:
        materials_context = raw_materials[:mat_limit]

    # 4) Filter/prioritize Prerequisites when in compact mode
    raw_prereqs = ctx.get("prereqs", "لا توجد متطلبات دراسية محفوظة.")
    if compact and len(raw_prereqs) > pre_limit and keywords:
        pre_lines = raw_prereqs.splitlines()
        matched_pre = [ln for ln in pre_lines if any(kw in _normalize_ar(ln) for kw in keywords)]
        if matched_pre:
            prereqs_context = "\n".join(matched_pre)[:pre_limit]
        else:
            prereqs_context = raw_prereqs[:pre_limit] + "\n..."
    else:
        prereqs_context = raw_prereqs[:pre_limit]

    # 5) Prioritize PDF texts
    pdf_items = ctx.get("pdf_items") or []
    if pdf_items:
        scored_pdfs = sorted(
            pdf_items,
            key=lambda item: _score_text(item[0], item[1]),
            reverse=True,
        )
        pdf_blocks = ["📚 الملفات السياقية (PDF):"]
        used_pdf = 0
        for pname, ptext in scored_pdfs:
            snippet = (ptext or "").strip()[: (500 if compact else 6000)]
            block = f"\n📄 ملف ({pname}):\n{snippet}\n"
            if used_pdf + len(block) > pdf_limit:
                break
            pdf_blocks.append(block)
            used_pdf += len(block)
        pdf_context = "\n".join(pdf_blocks) + "\n"
    else:
        pdf_context = (ctx.get("pdf", "") or "")[:pdf_limit]

    aliases_context = ctx.get("aliases", "")
    if compact and len(aliases_context) > 400:
        aliases_context = aliases_context[:400]

    return {
        "qa": qa_context,
        "materials": materials_context,
        "articles": articles_context,
        "pdf": pdf_context,
        "prereqs": prereqs_context,
        "aliases": aliases_context,
    }


# In-memory guard: exactly ONE background AI answer per user at a time (no races)
_user_busy: set[int] = set()
# Duplicate-question guard: reply only once for the same text within 20s
_last_question: dict[tuple[int, str], float] = {}
# Persistent per-user and per-admin conversation memory (keeps last 8 turns even if user navigates away)
_USER_CHAT_HISTORY: dict[int, list[dict]] = {}
_ADMIN_CHAT_HISTORY: dict[int, list[dict]] = {}


async def _build_static_context() -> dict:
    try:
        qa_list = await get_all_qa()
    except Exception as e:
        logger.error("AI: get_all_qa failed: %s", e)
        qa_list = []
    qa_items = [(qa.question, qa.answer) for qa in qa_list]
    qa_context = "\n".join(
        f"س: {qa.question}\nج: {qa.answer}" for qa in qa_list
    ) if qa_list else "لا توجد أسئلة مضافة بعد."

    async def build_tree(parent_id: int | None, indent: int = 0, depth: int = 0, folders=None, parent_path: str = "") -> str:
        if depth > 10:
            return ""
        prefix = "  " * indent + "• "
        lines = []
        children = [f for f in folders if (f.parent_id == parent_id if parent_id is not None else f.parent_id is None)]
        for f in children:
            cur_path = f"{parent_path} / {f.name}" if parent_path else f.name
            folder_note = f" ({f.reply_text[:120]})" if getattr(f, "reply_text", None) else ""
            lines.append(f"{prefix}📁 {f.name}{folder_note}")
            child = await build_tree(f.id, indent + 1, depth + 1, folders, cur_path)
            if child:
                lines.append(child)
            items = [i for i in item_list if i.folder_id == f.id]
            for item in items:
                links = [l for l in link_list if l.content_item_id == item.id]
                title = item.title or "محتوى"
                status_str = f" ({len(links)} ملف مرفق)" if links else " (بدون ملفات مرفقة حالياً)"
                lines.append(f"{'  ' * (indent+1)}• 📄 [ID:{item.id}] {cur_path} / {title}{status_str}")
        return "\n".join(lines)

    try:
        materials_data = await get_all_materials()
        folder_list = list(materials_data["folders"])
        item_list = list(materials_data["items"])
        link_list = list(materials_data["links"])
        materials_context = await build_tree(None, folders=folder_list) if folder_list else "لا توجد مواد بعد."
    except Exception as e:
        logger.error("AI: build_tree failed: %s", e)
        materials_context = "حدث خطأ أثناء بناء شجرة المواد."
    if len(materials_context) > 12000:
        materials_context = materials_context[:12000] + "\n... (يوجد المزيد)"

    try:
        articles_list = await get_all_articles()
    except Exception as e:
        logger.error("AI: get_all_articles failed: %s", e)
        articles_list = []
    article_items = [(a.id, a.title, a.content) for a in articles_list]
    articles_context = ""
    for a in articles_list:
        c = a.content[:12000]
        articles_context += f"\nعنوان: {a.title}\nمحتوى: {c}\n"
    if len(articles_context) > 40000:
        articles_context = articles_context[:40000] + "\n... (محتوى إضافي)"

    try:
        prereqs_list = await get_all_prerequisites()
    except Exception as e:
        logger.error("AI: get_all_prerequisites failed: %s", e)
        prereqs_list = []

    # Load PDF context files using PyMuPDF (fitz) instead of raw binary decode
    pdf_items: list[tuple[str, str]] = []
    try:
        pdfs = await get_all_pdfs()
        pdf_context = ""
        for p in pdfs:
            extracted = _extract_pdf_text(p.file_path)
            if extracted:
                pdf_items.append((p.name, extracted))
                pdf_context += f"\n📄 {p.name}:\n{extracted[:4000]}\n"
            else:
                pdf_context += f"\n📄 {p.name}: (لا يوجد نص مستخرج)\n"
        if pdfs:
            pdf_context = "📚 الملفات السياقية:\n" + pdf_context + "\n"
    except Exception as e:
        logger.warning("AI: get_all_pdfs failed: %s", e)
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
    alias_items = [(a.alias, a.course_code, a.course_name) for a in aliases_list]
    aliases_context = ""
    for a in aliases_list:
        aliases_context += f"- '{a.alias}' ← {a.course_name} ({a.course_code})\n"
    if aliases_list:
        aliases_context = "📌 الأسماء البديلة للمواد (المستخدمون يسألون بها):\n" + aliases_context

    return {
        "qa": qa_context,
        "qa_items": qa_items,
        "materials": materials_context,
        "articles": articles_context,
        "article_items": article_items,
        "pdf": pdf_context,
        "pdf_items": pdf_items,
        "prereqs": prereqs_context,
        "aliases": aliases_context,
        "alias_items": alias_items,
    }


def _clear_context_cache() -> None:
    clear_ai_context()


async def get_static_context() -> dict:
    return await get_cached_context(_build_static_context)


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


@router.message(AdminFilter(), F.text == "🤖 نَافِذَة الـ AI")
async def ai_admin_panel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("🤖 نَافِذَة الـ AI:", reply_markup=ai_admin_keyboard())


# ─── QA folder ───

@router.message(AdminFilter(), F.text == "📚 الأسئلة")
async def ai_qa_folder(message: Message) -> None:
    await message.answer("📚 إدارة الأسئلة:", reply_markup=ai_qa_keyboard())


# ─── Articles folder ───

@router.message(AdminFilter(), F.text == "📰 المقالات")
async def ai_articles_folder(message: Message) -> None:
    await message.answer("📰 إدارة المقالات:", reply_markup=ai_articles_keyboard())


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
    extracted = _extract_pdf_text(dest)
    pdf = await save_pdf_context(name, dest)
    if extracted:
        try:
            art_title = f"📄 ملف سياقي: {name}"
            arts = await get_all_articles()
            ex_art = next((a for a in arts if a.title == art_title), None)
            if ex_art:
                await update_article(ex_art.id, content=extracted[:15000])
            else:
                await add_article(art_title, extracted[:15000])
        except Exception:
            pass
    await state.clear()
    await message.answer(f"✅ تم رفع {name} واستخراج النص وحفظه في ذاكرة الـ AI بنجاح.", reply_markup=ai_admin_keyboard())


async def index_single_sheet_message(bot, msg_obj, folder_name: str, item_title: str) -> str | None:
    """Extract text/PDF/image content from a channel sheet post and save/update it as an AI Article."""
    if not msg_obj:
        return None
    parts_extracted: list[str] = []
    txt = (getattr(msg_obj, "text", None) or getattr(msg_obj, "caption", None) or "").strip()
    if txt:
        parts_extracted.append(f"وصف المنشور:\n{txt}")

    doc = getattr(msg_obj, "document", None)
    if doc and (doc.file_name or "").lower().endswith(".pdf") and (doc.file_size or 0) < 18_000_000:
        try:
            import fitz
            finfo = await bot.get_file(doc.file_id)
            fbytes_io = await bot.download_file(finfo.file_path)
            raw_pdf = fbytes_io.read()
            pages = []
            with fitz.open(stream=raw_pdf, filetype="pdf") as pdf_doc:
                for p in pdf_doc:
                    pt = p.get_text()
                    if pt and pt.strip():
                        pages.append(pt.strip())
            pdf_str = "\n".join(pages).strip()
            if pdf_str:
                parts_extracted.append(f"محتوى ملف PDF ({doc.file_name}):\n{pdf_str[:8000]}")
        except Exception as e:
            logger.warning("index_single_sheet_message PDF extract failed for %s/%s: %s", folder_name, item_title, e)

    photo_list = getattr(msg_obj, "photo", None)
    if photo_list and not parts_extracted:
        try:
            import base64
            ph = photo_list[-2] if len(photo_list) >= 2 else photo_list[-1]
            finfo = await bot.get_file(ph.file_id)
            fbytes_io = await bot.download_file(finfo.file_path)
            b64 = base64.b64encode(fbytes_io.read()).decode()
            if len(b64) < 15_000_000:
                vis_text = await call_groq_vision("استخرج كل النصوص والعناوين والأسئلة الموجودة في صورة هذا الشيت الدراسي بالعربية بدقة:", b64)
                if vis_text:
                    parts_extracted.append(f"محتوى صورة الشيت:\n{vis_text[:4000]}")
        except Exception as e:
            logger.warning("index_single_sheet_message photo extract failed: %s", e)

    if not parts_extracted:
        return None

    art_title = f"📘 شيت: {folder_name} / {item_title}"
    body = f"المادة أو المجلد: {folder_name}\nاسم الشيت: {item_title}\n\n" + "\n\n".join(parts_extracted)
    all_arts = await get_all_articles()
    existing = next((a for a in all_arts if a.title == art_title), None)
    if existing:
        merged = existing.content
        for p_ext in parts_extracted:
            if p_ext[:120] not in merged:
                merged = (merged + "\n\n" + p_ext)[:15000]
        await update_article(existing.id, content=merged)
    else:
        await add_article(art_title, body[:15000])
    return art_title


@router.message(AdminFilter(), F.text == "🔍 تحليل شيتات القناة للـ AI")
async def ai_analyze_channel_sheets(message: Message) -> None:
    status_msg = await message.answer("⏳ جاري فحص وتحليل الشيتات والملفات المربوطة من القنوات وتحويلها إلى مقالات معرفية للـ AI...")
    try:
        mats = await get_all_materials()
        folders_by_id = {f.id: f for f in mats["folders"]}

        def _get_fpath(fid: int | None) -> str:
            names = []
            cur = fid
            depth = 0
            while cur is not None and depth < 10:
                fo = folders_by_id.get(cur)
                if not fo:
                    break
                names.append(fo.name)
                cur = fo.parent_id
                depth += 1
            return " / ".join(reversed(names)) if names else "عام"

        all_arts = await get_all_articles()
        existing_titles = {a.title for a in all_arts}

        analyzed_count = 0
        skipped_existing = 0
        failed_count = 0
        catalog_lines: list[str] = []

        for item in mats["items"]:
            fpath = _get_fpath(item.folder_id)
            ititle = (item.title or "محتوى").strip()
            item_links = [l for l in mats["links"] if l.content_item_id == item.id]
            if not item_links:
                continue
            catalog_lines.append(f"• المادة/المجلد: {fpath} — الشيت: {ititle} [ID:{item.id}] (عدد الملفات: {len(item_links)})")
            art_title = f"📘 شيت: {fpath} / {ititle}"
            if art_title in existing_titles:
                skipped_existing += 1
                continue
            # Analyze the first 2 links of this sheet item
            item_indexed = False
            for lnk in item_links[:2]:
                fid = None
                mid = None
                if lnk.channel_username and lnk.channel_message_id:
                    fid = _resolve_channel_chat_id(lnk.channel_username)
                    mid = int(lnk.channel_message_id)
                elif lnk.link:
                    m = LINK_REGEX.search(lnk.link)
                    if m:
                        fid = _resolve_channel_chat_id(m.group(2), is_private_c=bool(m.group(1)))
                        mid = int(m.group(3))
                if not fid or not mid:
                    continue
                try:
                    fwd = await message.bot.forward_message(
                        chat_id=message.chat.id,
                        from_chat_id=fid,
                        message_id=mid,
                    )
                    res_title = await index_single_sheet_message(message.bot, fwd, fpath, ititle)
                    try:
                        await fwd.delete()
                    except Exception:
                        pass
                    if res_title:
                        item_indexed = True
                except Exception as exc:
                    logger.warning("Sheet analyze forward failed (%s/%s): %s", fid, mid, exc)
                await asyncio.sleep(0.25)
            if item_indexed:
                analyzed_count += 1
            else:
                failed_count += 1

        # Also save/update a master catalog article of all sheets so AI always knows every sheet by course
        if catalog_lines:
            cat_title = "📚 الفهرس الشامل لشيتات وملفات المواد في القنوات"
            cat_body = "قائمة بجميع الشيتات والملفات المتوفرة حالياً في البوت حسب المادة والمجلد:\n\n" + "\n".join(catalog_lines)
            all_arts_now = await get_all_articles()
            ex_cat = next((a for a in all_arts_now if a.title == cat_title), None)
            if ex_cat:
                await update_article(ex_cat.id, content=cat_body[:15000])
            else:
                await add_article(cat_title, cat_body[:15000])

        await status_msg.edit_text(
            f"✅ اكتمل تحليل شيتات القناة وحفظها في ذاكرة المقالات للـ AI!\n\n"
            f"📘 شيتات جديدة تم استخراج محتواها (PDF/نص/صور): {analyzed_count}\n"
            f"✔️ شيتات محللة مسبقاً: {skipped_existing}\n"
            f"📚 إجمالي الشيتات المفهرسة في الفهرس الشامل: {len(catalog_lines)}\n\n"
            f"الآن عندما يسأل أي طالب عن موضوع داخل هذه الشيتات، سيجيب الـ AI من محتواها مباشرة!",
            parse_mode=None,
        )
    except Exception as e:
        logger.exception("ai_analyze_channel_sheets error")
        await status_msg.edit_text(f"⚠️ حدث خطأ أثناء التحليل: {str(e)[:200]}", parse_mode=None)


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
        prev_hist = _USER_CHAT_HISTORY.get(message.from_user.id, [])
        await state.update_data(history=prev_hist)
        await message.answer(
            "مرحباً بك في نَافِذَة الـ AI!\n"
            "أنا نموذج ذكاء اصطناعي مُطوّر لبوت نَافِذَة، أعمل على معالجة أسئلتك ومساعدتك في كافة استفساراتك الجامعية خطوة بخطوة (وأتذكر سياق محادثتك الجارية).\n"
            "تفضل بكتابة سؤالك وسأجيبك فوراً!\n\n"
            "💡 للبدء في موضوع جديد تماماً أرسل: محادثة جديدة\n"
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
    q = (message.text or "").strip()
    uid = message.from_user.id
    now = time.monotonic()
    # Duplicate guard: same question text within 20s is a resend/spam echo → ignore
    if q:
        if len(_last_question) > 500:
            stale = [k for k, ts in _last_question.items() if now - ts > 60.0]
            for k in stale:
                _last_question.pop(k, None)
        key = (uid, q)
        if key in _last_question and now - _last_question[key] < 20.0:
            logger.info("Dropping duplicate question from %s: %r", uid, q[:50])
            return
        _last_question[key] = now
    # Memory guard: one AI answer per user at a time — no FSM race window
    if uid in _user_busy:
        await message.answer(
            "⏳ لقد استلمت رسالتك، أفكر في سؤالك الآن...\n"
            "اكتب سؤالك بعد الانتهاء أو اضغط 🔙 رجوع.",
            reply_markup=ai_user_keyboard(),
        )
        return
    _user_busy.add(uid)
    await state.update_data(ai_busy=True)
    await message.bot.send_chat_action(message.chat.id, "typing")
    asyncio.create_task(_ai_bg_question(message, state))


async def _ai_bg_question(message: Message, state: FSMContext) -> None:
    try:
        await _ai_user_question(message, state)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.exception("AI user question error")
        from database.crud import save_error, save_error_db
        save_error("ai_user_question", tb[:1500])
        await save_error_db("ai_user_question", str(e)[:500], user_id=message.from_user.id, traceback=tb[:2000])
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
    finally:
        try:
            _user_busy.discard(message.from_user.id)
        except Exception:
            pass
        try:
            await state.update_data(ai_busy=False)
        except Exception:
            pass


def _ai_notify_keyboard():
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    builder = InlineKeyboardBuilder()
    builder.button(text="📨 إرسال للمشرفين", callback_data="ai_notify:yes")
    builder.button(text="❌ لا ترسل", callback_data="ai_notify:no")
    builder.adjust(1, 1)
    return builder.as_markup()


@router.callback_query(AIState.waiting_for_question, F.data == "ai_notify:yes")
async def ai_notify_yes_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    from types import SimpleNamespace
    from database.crud import save_message
    from handlers.messages import forward_to_admins
    history: list = data.get("history", [])
    q = data.get("pending_notify_q") or ""
    ai_context = "\n".join(
        f"المستخدم: {turn['user']}\nالمساعد: {turn['assistant']}"
        for turn in history[-5:]
    )
    content = f"[طلب AI]\n{q}\n\nسجل المحادثة:\n{ai_context}"
    msg = await save_message(user_id=callback.from_user.id, message_type="text", content=content)
    fake = SimpleNamespace(
        from_user=callback.from_user,
        text=content,
        caption=None, photo=None, video=None, document=None, audio=None,
        voice=None, sticker=None, animation=None, video_note=None,
        bot=callback.bot,
        chat=callback.message.chat,
    )
    await forward_to_admins(fake, "text", msg.id)
    await state.update_data(pending_admin_notify=False, pending_notify_q=None)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        "✅ تم إبلاغ المشرفين، سيردون عليك قريباً إن شاء الله.",
        reply_markup=ai_user_keyboard(),
    )


@router.callback_query(AIState.waiting_for_question, F.data == "ai_notify:no")
async def ai_notify_no_cb(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.update_data(pending_admin_notify=False, pending_notify_q=None)
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(
        "حسناً، لن أرسل أي شيء. كمّل أسئلتك وأنا معك.",
        reply_markup=ai_user_keyboard(),
    )


_COT_MARKER_PATTERNS = (
    r"\[Output Generation\][^\n]*",
    r"\[[Ff]inal [Rr]esponse\][^\n]*",
    r"\[[Oo]utput\][^\n]*",
    r"##?\s*[Ff]inal [Aa]nswer[^\n]*",
    r"##?\s*[Oo]utput[^\n]*",
)


_COT_ENG_PATTERNS = re.compile(
    r"\b(the user|user is asking|let's think|i should|i need to|first,|step \d|in arabic|system prompt|final answer|wait,|looking at the context)\b",
    re.IGNORECASE,
)


def _strip_cot(answer: str) -> str:
    """Remove internal chain-of-thought reasoning from an AI reply, keeping
    the final answer intact (including course codes, numbers, and bullet lists)."""
    text = re.sub(r"<think>.*?</think>", "", answer, flags=re.DOTALL)
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL)
    text = re.sub(r"<output>(.*?)</output>", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"</?[a-zA-Z][^>]*>", "", text)
    text = text.replace("**", "").strip()

    # 1) Cut at LAST explicit output marker (nested [Output Generation] blocks)
    last_marker = None
    for pat in _COT_MARKER_PATTERNS:
        matches = list(re.finditer(pat, text, re.DOTALL))
        if matches:
            m = matches[-1]
            if last_marker is None or m.start() > last_marker:
                last_marker = m.start()
    if last_marker is not None:
        seg = text[last_marker:]
        arrow = re.search(r"->\s*\"?(.*)$", seg, re.DOTALL) or re.search(r":\s*\"?(.*)$", seg, re.DOTALL)
        if arrow and arrow.group(1).strip():
            text = arrow.group(1).strip().rstrip('"')
        else:
            text = text.split("->", 1)[-1].strip() if "->" in seg else seg

    # 2) Remove duplicate repeated answer blocks (model sometimes outputs same answer twice)
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if len(paras) > 1:
        first = paras[0]
        last = paras[-1]
        if first and last:
            common = set(first) & set(last)
            similarity = len(common) / max(len(set(first)), len(set(last)))
            if similarity > 0.85:
                text = last

    # 3) Drop only English meta-thinking lines while keeping Arabic, course codes, and [FORWARD]
    lines = re.split(r"\n+", text)
    kept = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if s.upper().startswith("[FORWARD]"):
            kept.append(s)
            continue
        arabic = len(re.findall(r"[\u0600-\u06FF]", s))
        latin = len(re.findall(r"[a-zA-Z]", s))
        total = len(s)
        if arabic > 0 and not _COT_ENG_PATTERNS.search(s):
            kept.append(s)
        elif arabic == 0 and _COT_ENG_PATTERNS.search(s):
            continue
        elif arabic == 0 and latin > 45 and total > 60:
            # Long pure-English reasoning line
            continue
        else:
            kept.append(s)
    if kept:
        text = "\n".join(kept)
    return re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]{2,}", " ", text)).strip()


async def _ai_user_question(message: Message, state: FSMContext) -> None:
    q = (message.text or message.caption or "").strip()
    if not q:
        return

    if not is_ai_active():
        await state.clear()
        await message.answer("🛑 المساعد الذكي متوقف حالياً.", reply_markup=main_keyboard())
        return

    if q in ("محادثة جديدة", "موضوع جديد", "امسح المحادثة", "مسح المحادثة"):
        _USER_CHAT_HISTORY.pop(message.from_user.id, None)
        await state.update_data(history=[], pending_admin_notify=False, pending_notify_q=None)
        await message.answer("🔄 تم بدء محادثة جديدة تماماً! تفضل بكتابة سؤالك.", reply_markup=ai_user_keyboard())
        return

    data = await state.get_data()
    history: list[dict] = data.get("history") or list(_USER_CHAT_HISTORY.get(message.from_user.id, []))

    try:
        uname = message.from_user.full_name or message.from_user.username or str(message.from_user.id)
        await log_ai_action(message.from_user.id, uname, f"❓ سؤال: {q[:80]}")
    except Exception:
        pass

    # Check if AI previously offered to notify admins and user is confirming
    if data.get("pending_admin_notify"):
        confirm_words = ["نعم", "اي", "أي", "ايه", "أيه", "تمام", "طيب", "باهي", "ايوه", "ih", "is", "ok", "yes", "aye", "go ahead", "ابشر", "هات", "ارسل", "ابعت"]
        if any(w in q.lower() for w in confirm_words):
            await message.answer(
                "حسناً، هل تريد مني إرسال طلبك إلى المشرفين الآن؟",
                reply_markup=_ai_notify_keyboard(),
            )
            return
        await state.update_data(pending_admin_notify=False, pending_notify_q=None)
        # fall through to normal AI processing

    # Build static context and prioritize items relevant to the student's question
    try:
        raw_ctx = await get_static_context()
        ctx = _select_relevant_context(q, history, raw_ctx, max_articles_chars=32000)
        qa_context = ctx["qa"]
        materials_context = ctx["materials"]
        articles_context = ctx["articles"]
        pdf_context = ctx["pdf"]
        prereqs_context = ctx["prereqs"]
        aliases_context = ctx["aliases"]
    except Exception as e:
        logger.error("AI: get_static_context failed: %s", e)
        qa_context = "لا توجد أسئلة مضافة بعد."
        materials_context = "لا توجد مواد بعد."
        articles_context = "لا توجد مقالات مضافة بعد."
        pdf_context = ""
        prereqs_context = "لا توجد متطلبات دراسية محفوظة."
        aliases_context = ""

    def _compose_system_prompt(c: dict, hist_turns: int = 8) -> str:
        h_lines = []
        for turn in history[-hist_turns:]:
            h_lines.append(f"الطالب: {turn['user'][:200]}")
            h_lines.append(f"مساعد نافذة: {turn['assistant'][:300]}")
        h_ctx = "\n".join(h_lines)
        h_note = f"\n💬 سجل المحادثة السابقة:\n{h_ctx}\n" if h_ctx else ""
        return (
            "أنت «مساعد نَافِذَة الذكي» — المساعد الجامعي الرسمي المعتمد لطلاب الجامعة عبر منصة «نَافِذَة».\n"
            "شخصيتك: سلس جداً، ودود، قريب من الطالب، تفهم جميع اللهجات العربية (وخاصة اللهجة الليبية الدارجة ومصطلحات الطلبة مثل: قداش، امتى، شن يفتح، شن يحتاج، سيمستر، تنزيل، تصفية، شيتات، نصفي، فاينل، وأسماء المواد المكتوبة بالعربي أو الإنجليزي مثل كالكولس، سي بلس، ديسكريت، فيزيا) وترد بأسلوب واضح، مرتب، ومريح، وفي نفس الوقت أنت على قدر عالٍ من المسؤولية والأمانة العلمية.\n\n"
            "📂 البيانات الرسمية المعتمدة في «نَافِذَة»:\n"
            f"{c['aliases']}\n"
            f"📰 أولاً: المقالات والمنشورات الرسمية:\n{c['articles']}\n\n"
            f"📚 ثانياً: الأسئلة الشائعة:\n{c['qa']}\n\n"
            f"📁 ثالثاً: شجرة المواد الدراسية والشيتات:\n{c['materials']}\n\n"
            f"🔗 رابعاً: شجرة المتطلبات الدراسية:\n{c['prereqs']}\n\n"
            f"{c['pdf']}\n"
            f"{h_note}\n"
            "🚫 قواعد المسؤولية والانضباط الصارمة (إلزامية 100%):\n"
            "1. الترابط السياقي وفهم المحادثة المستمرة (آخر 3 إلى 6 رسائل):\n"
            "   - انتبه جيداً لرسائل الطالب السابقة وردودك عليها! إذا أرسل الطالب سؤالاً قصيراً أو مكملاً لنفس الموضوع (مثل: باهي، وكم وحداتها؟، وعندها شيتات؟، شن تفتح؟، ابعتهم ليا، قصدي الثانية)، اربطه مباشرة بنفس المادة أو الموضوع الذي كنتم تتحدثون عنه في الرسائل السابقة.\n"
            "2. الفهم الذكي للهجات والسلاسة في الحوار:\n"
            "   - افهم قصد الطالب مهما كانت لهجته أو أخطاؤه الإملائية، ورتّب إجابتك بشكل منظم وواضح باستخدام النقاط (•) عند الحاجة بدون تعقيد.\n"
            "   - في التحية أو الشكر (السلام عليكم، شن الجو، صحيت، بارك الله فيك، منور)، رد بلطف وروح طيبة وعرّف بنفسك كمساعد منصة «نَافِذَة».\n"
            "3. الأمانة التامة والمسؤولية (ممنوع الفتوى أو التخمين):\n"
            "   - مصدرك الوحيد للحقائق والأرقام والدرجات والتواريخ واللوائح والمتطلبات هو البيانات المرفقة أعلاه فقط.\n"
            "   - إياك أن تعطي الطالب معلومة غير متأكد منها أو غير موجودة في البيانات أعلاه!\n"
            "4. عند عدم توفر المعلومة في بيانات «نَافِذَة»:\n"
            "   - إذا سأل الطالب سؤالاً جامعياً لا يوجد جوابه في البيانات أعلاه، اعتذر بصدق ومسؤولية وقل:\n"
            "     «لا تتوفر لدي معلومة مؤكدة حول هذا الاستفسار في بيانات نَافِذَة حالياً. هل تريدني أن أبلغ المشرفين بهذا الطلب؟»\n"
            "5. النطاق الحصري للجامعة و«نَافِذَة»:\n"
            "   - يُمنع الإجابة على أي مواضيع خارج الدراسة والجامعة ومنصة «نَافِذَة» (مثل: طبخ، رياضة، سياسة، ترفيه، أو أسئلة عامة). اعتذر بلطف:\n"
            "     «عذراً، أنا المساعد الذكي الخاص بمنصة نَافِذَة، ومهمتي الإجابة فقط على الاستفسارات المتعلقة بالجامعة والمواد الدراسية والمنشورات المعتمدة في البوت.»\n"
            "6. إرسال الشيتات والملفات الدراسية آلياً بدقة تامة (ممنوع إرسال شيتات مواد أخرى):\n"
            "   - إذا قال الطالب 'نبي شيتات' أو 'ابعتلي شيتات' دون أن يحدد اسم المادة (لا في رسالته الحالية ولا في الرسائل السابقة)، لا ترسل أي شيت عشوائي! بل اسأله بلطف: «أي مادة تبي شيتاتها بالضبط؟» واذكر له المواد المتوفرة.\n"
            "   - أما إذا حدد الطالب اسم المادة، فاذكر له الشيتات الخاصة بهذه المادة فقط، واكتب في سطر منفصل في نهاية ردك رقم الـ ID الدقيق لكل شيت مطلوب من هذه المادة حصراً كما يظهر في شجرة المواد أعلاه بهذا الشكل:\n"
            "     [FORWARD] ID:15 | ID:16\n"
            "   - إياك أن تضع في [FORWARD] شيتات تابعة لمادة أخرى غير التي طلبها الطالب! ولا تكتب أي رابط في ردك.\n"
            "7. اكتب بالعربية مباشرة بدون رموز Markdown (** أو * أو #) وبدون كتابة أي تفكير داخلي.\n"
        )

    user_prompt = q

    try:
        await message.bot.send_chat_action(message.chat.id, "typing")
    except Exception:
        pass

    answer = None
    if settings.gemini_keys:
        system_prompt = _compose_system_prompt(ctx, hist_turns=8)
        answer = await call_gemini(user_prompt, system_prompt=system_prompt, max_tokens=2048, use_groq=False, history=history[-6:])
    if not answer:
        groq_ctx = _select_relevant_context(
            q, history, raw_ctx if "raw_ctx" in locals() else {}, max_articles_chars=2100, compact=True
        )
        groq_system_prompt = _compose_system_prompt(groq_ctx, hist_turns=5)
        answer = await call_gemini(user_prompt, system_prompt=groq_system_prompt, max_tokens=800, use_groq=True, history=history[-5:])
    if answer:
        # Forward actual files: strictly only items belonging to the requested course/ID!
        forwarded = set()
        sent_files = 0
        requested_items = []
        try:
            from database.crud import get_all_materials
            materials_data = await get_all_materials()
            folders_by_id = {f.id: f for f in materials_data["folders"]}

            def _item_folder_path(fid: int | None) -> str:
                names = []
                cur = fid
                d = 0
                while cur is not None and d < 10:
                    fo = folders_by_id.get(cur)
                    if not fo:
                        break
                    names.append(fo.name)
                    cur = fo.parent_id
                    d += 1
                return " / ".join(reversed(names))

            wanted_ids: set[int] = set()
            wanted_paths: set[str] = set()
            wanted_bare_titles: set[str] = set()

            for m in re.finditer(r"\[FORWARD\]\s*([^\n]+)", answer, re.IGNORECASE):
                for part in re.split(r"\||,|؛|;", m.group(1)):
                    t = part.strip().lstrip("•📄").strip()
                    if not t:
                        continue
                    # Extract [ID:15] or ID:15
                    id_matches = re.findall(r"(?:\[?ID\s*:\s*|\bID\s*)(\d+)\]?", t, re.IGNORECASE)
                    if id_matches:
                        for id_str in id_matches:
                            wanted_ids.add(int(id_str))
                        continue
                    if t.isdigit():
                        wanted_ids.add(int(t))
                        continue
                    # Clean out any parenthetical status text like (1 ملف مرفق)
                    t_clean = re.sub(r"\(\d+\s*ملف.*?\)", "", t).strip()
                    if "/" in t_clean:
                        wanted_paths.add(_normalize_ar(t_clean))
                    else:
                        wanted_bare_titles.add(_normalize_ar(t_clean))

            # Extract course/folder keywords from student's current query + last 2 turns
            recent_q_context = _normalize_ar(
                q + " " + " ".join((turn.get("user") or "") + " " + (turn.get("assistant") or "")[:150] for turn in history[-2:])
            )
            matched_items_to_send = []

            for item in materials_data["items"]:
                title = (item.title or "").strip()
                if not title:
                    continue
                fpath = _item_folder_path(item.folder_id)
                norm_title = _normalize_ar(title)
                norm_fpath = _normalize_ar(fpath)
                norm_full = _normalize_ar(f"{fpath} / {title}")

                is_match = False
                if item.id in wanted_ids:
                    is_match = True
                elif norm_full in wanted_paths:
                    is_match = True
                elif any(wp in norm_full or norm_full in wp for wp in wanted_paths if len(wp) > 5):
                    is_match = True
                elif norm_title in wanted_bare_titles:
                    # CRITICAL GUARD: If AI only output a generic title like "شيت 1",
                    # ONLY match this item if its parent folder name matches the student's conversation!
                    folder_words = [w for w in re.findall(r"[\w\u0600-\u06FF]{2,}", norm_fpath) if len(w) >= 2]
                    if folder_words and any(fw in recent_q_context for fw in folder_words):
                        is_match = True
                    elif sum(1 for it2 in materials_data["items"] if _normalize_ar(it2.title or "") == norm_title) == 1:
                        # Unique title across the entire bot
                        is_match = True

                if is_match:
                    matched_items_to_send.append((item, f"{fpath} / {title}" if fpath else title))

            for item, display_name in matched_items_to_send:
                item_links = [l for l in materials_data["links"] if l.content_item_id == item.id]
                if not item_links:
                    requested_items.append(display_name)
                    continue
                for link in item_links:
                    ch = link.channel_username
                    mid = link.channel_message_id
                    key = f"{ch}/{mid}/{link.link}"
                    if key in forwarded:
                        continue
                    forwarded.add(key)
                    ok = False
                    if ch and mid:
                        try:
                            fid = _resolve_channel_chat_id(ch)
                            await message.bot.copy_message(
                                chat_id=message.chat.id,
                                from_chat_id=fid,
                                message_id=int(mid),
                            )
                            ok = True
                        except Exception as exc:
                            logger.warning("copy_message channel failed (%s/%s) for user %s: %s", ch, mid, message.chat.id, exc)
                    if not ok and link.link:
                        try:
                            m = LINK_REGEX.search(link.link)
                            if m:
                                is_priv = bool(m.group(1))
                                ch2, mid2 = m.group(2), int(m.group(3))
                                fid2 = _resolve_channel_chat_id(ch2, is_private_c=is_priv)
                                await message.bot.copy_message(
                                    chat_id=message.chat.id,
                                    from_chat_id=fid2,
                                    message_id=mid2,
                                )
                                ok = True
                        except Exception as exc:
                            logger.warning("copy_message link failed (%s) for user %s: %s", link.link, message.chat.id, exc)
                    if ok:
                        sent_files += 1
        except Exception as exc:
            logger.warning("forward_items_from_answer failed: %s", exc)

        # Strip CoT and internal markers
        clean_answer = _strip_cot(answer)
        lines = clean_answer.splitlines()
        deduped = []
        prev = None
        for line in lines:
            s = line.strip()
            if s and s == prev:
                continue
            deduped.append(line)
            prev = s
        clean_answer = "\n".join(deduped)
        # Remove the internal [FORWARD] ... or [SAVE_ALIAS] ... instruction lines from the user reply
        clean_answer = re.sub(r"\[FORWARD\][^\n]*\n?", "", clean_answer, flags=re.IGNORECASE)
        clean_answer = re.sub(r"\[SAVE_ALIAS\][^\n]*\n?", "", clean_answer, flags=re.IGNORECASE)
        # Remove t.me links one more time after filtering
        clean_answer = re.sub(r"https?://t\.me/\S+", "", clean_answer).strip()
        clean_answer = re.sub(r"[ \t]{2,}", " ", clean_answer)
        clean_answer = re.sub(r"\n{3,}", "\n\n", clean_answer)

        # Honesty guard: if the user asked for sheets/files but nothing was forwarded
        asked_files = any(w in (q or "") for w in ["شيت", "شيتات", "شوية ملفات", "ملف", "ملفات", "سلایدات", "سلايدات", "محاضرات", "امتحانات", "pdf", "PDF", "روابط", "رابط"])
        if asked_files and sent_files == 0:
            for phrase in ["أرسلت لك الروابط", "أرسلت لك الملفات", "إليك الروابط", "إليك الملفات", "هذه الروابط", "المصادر اللي فوق", "الروابط التالية", "الروابط اللي بعتلك", "أقدم لك الروابط", "أرسلت لك بعض الروابط", "ستجد الروابط"]:
                clean_answer = clean_answer.replace(phrase, "")
            if requested_items:
                names = "، ".join(requested_items[:3])
                clean_answer = (clean_answer + f"\n\nملاحظة: ملفات ({names}) غير مرفقة حالياً في البوت.").strip()
            else:
                clean_answer = clean_answer.strip()
        elif sent_files > 0:
            clean_answer = clean_answer.strip()

        # Normalize admin notification offer phrases
        had_notify_offer = False
        for phrase in ["سأبلغ المشرفين", "سأخبر المشرفين", "سأبلغ الإدارة", "سأخبر الإدارة", "إلى المشافظين"]:
            if phrase in clean_answer:
                clean_answer = clean_answer.replace(phrase, "هل تريدني أن أبلغ المشرفين بهذا الطلب؟")
                had_notify_offer = True
        if "📢" in clean_answer:
            clean_answer = clean_answer.replace("📢", "").strip()
        if (
            had_notify_offer
            or ("هل تريد" in clean_answer and ("المشرفين" in clean_answer or "الإدارة" in clean_answer))
            or (re.search(r"أبلغ|إبلاغ|تحويل", clean_answer) and re.search(r"المشرفين|الإدارة", clean_answer))
        ):
            had_notify_offer = True
            await state.update_data(pending_admin_notify=True, pending_notify_q=q)

        # Save to history (keep clean answer without internal tags)
        history.append({"user": q, "assistant": clean_answer or answer})
        if len(history) > 12:
            history = history[-12:]
        _USER_CHAT_HISTORY[message.from_user.id] = list(history[-8:])
        await state.update_data(history=history)

        if clean_answer:
            if had_notify_offer:
                await safe_send(message, clean_answer, reply_markup=_ai_notify_keyboard())
            else:
                await safe_send(message, clean_answer, reply_markup=ai_user_keyboard())

        if not had_notify_offer and any(w in q for w in ["قول للمشرف", "بلغ المشرف", "كلم المشرف", "ابلغ المشرف", "حول للمشرف"]):
            await state.update_data(pending_admin_notify=True, pending_notify_q=q)
            await message.answer(
                "حسناً، هل تريد مني إرسال طلبك إلى المشرفين الآن؟",
                reply_markup=_ai_notify_keyboard(),
            )
    else:
        from services.gemini import LAST_GROQ_ERROR, LAST_GEMINI_ERROR, LAST_CALL_ERROR
        reason = (LAST_GROQ_ERROR or LAST_GEMINI_ERROR or LAST_CALL_ERROR or "فشل غير معروف")[:300]
        logger.error("AI reply failed for user %s: %s", message.from_user.id, reason)
        from database.crud import save_error_db
        try:
            await save_error_db("ai_user_question_empty", reason, user_id=message.from_user.id)
        except Exception:
            pass
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
        "📬 أرسل صوراً للتحليل، أو ملفات PDF كسياق علمي، أو متطلبات لاستخراج العلاقات، أو أي نص للمحادثة والأوامر.\n\n"
        "🔙 رجوع",
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
        from database.crud import save_error, save_error_db
        save_error("ai_smart_image", str(e)[:500])
        await save_error_db("ai_smart_image", str(e)[:500], user_id=message.from_user.id)
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
    pdf_text = _extract_pdf_text(dest)
    if pdf_text.strip():
        try:
            art_title = f"📄 ملف سياقي: {name}"
            arts = await get_all_articles()
            ex_art = next((a for a in arts if a.title == art_title), None)
            if ex_art:
                await update_article(ex_art.id, content=pdf_text[:15000])
            else:
                await add_article(art_title, pdf_text[:15000])
        except Exception:
            pass
    else:
        pdf_text = "لم يتم استخراج نص من هذا PDF."

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
        "🤖 محادثة ذكية وموسعة مع مساعد المشرفين!\n\n"
        "تقدر تحكي معاه باللهجة الليبية أو الفصحى وتطلب منه عدة أوامر في رسالة واحدة، مثل:\n"
        "• إضافة أو تعديل أو حذف أسئلة ومقالات (أو صياغة إعلان ونشره فوراً)\n"
        "• إدارة شجرة المواد والمجلدات والروابط والمتطلبات والأسماء البديلة\n"
        "• معرفة إحصائيات البوت، البحث عن أي طالب، أو عرض سجل نشاط المستخدمين\n"
        "• عرض رسائل التواصل غير المقروءة، إضافة ردود سريعة، أو إرسال إشعار لطالب/للجميع\n\n"
        "أو استخدم ❌ إلغاء للخروج.",
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
        from database.crud import save_error, save_error_db
        save_error("ai_admin_chat", tb[:1500])
        await save_error_db("ai_admin_chat", str(e)[:300], user_id=message.from_user.id, traceback=tb[:2000])
        err_msg = str(e)[:300] or "خطأ غير معروف"
        await message.answer(f"⚠️ حدث خطأ: {err_msg}", reply_markup=cancel_keyboard())
        for admin_id in settings.admin_ids:
            try:
                await message.bot.send_message(admin_id, f"⚠️ خطأ في AI:\n{tb[:3500]}", parse_mode=None)
            except Exception:
                pass


async def _get_admin_role_info(uid: int) -> dict:
    """Return role and granular permissions for an admin user."""
    if uid in settings.admin_ids:
        return {
            "is_super": True,
            "rank": "super_admin",
            "rank_label": "🚀 سوبر أدمن (صلاحيات كاملة)",
            "can_reply": True,
            "can_ban": True,
            "can_manage": True,
            "can_view_logs": True,
            "can_control_bot": True,
        }
    perms = await get_admin_permissions(uid)
    if not perms:
        return {
            "is_super": False,
            "rank": "moderator",
            "rank_label": "🔰 مراقب",
            "can_reply": True,
            "can_ban": False,
            "can_manage": False,
            "can_view_logs": False,
            "can_control_bot": False,
        }
    rank = perms.get("rank", "admin")
    is_super = rank == "super_admin" or bool(perms.get("can_control_bot", False))
    labels = {
        "super_admin": "🚀 سوبر أدمن (صلاحيات كاملة)",
        "admin": "👑 مشرف",
        "moderator": "🔰 مراقب",
    }
    return {
        "is_super": is_super,
        "rank": rank,
        "rank_label": labels.get(rank, "👑 مشرف"),
        "can_reply": bool(perms.get("can_reply", True)),
        "can_ban": bool(perms.get("can_ban", False)) or is_super,
        "can_manage": bool(perms.get("can_manage", False)) or is_super,
        "can_view_logs": bool(perms.get("can_view_logs", False)) or is_super,
        "can_control_bot": is_super,
    }


async def _ai_admin_chat_message(message: Message, state: FSMContext) -> None:
    q = message.text or message.caption or ""
    if not q:
        return

    try:
        await message.bot.send_chat_action(message.chat.id, "typing")
    except Exception:
        pass

    uid = message.from_user.id
    role_info = await _get_admin_role_info(uid)

    data = await state.get_data()
    admin_history: list[dict] = data.get("admin_history") or list(_ADMIN_CHAT_HISTORY.get(uid, []))

    current_state = await state.get_state()
    _in_smart = current_state == AIAdminState.smart_mode.state
    _rm = None if _in_smart else cancel_keyboard()

    qa_list, articles_list, prereqs_list, materials = await asyncio.gather(
        get_all_qa(), get_all_articles(), get_all_prerequisites(), get_all_materials()
    )
    qa_context = "\n".join(
        f"{qa.id}: س: {qa.question[:60]} → ج: {qa.answer[:60]}"
        for qa in qa_list[-20:]
    ) if qa_list else "لا يوجد"

    art_context = "\n".join(
        f"{a.id}: {a.title[:50]} ({len(a.content)} حرف)"
        for a in articles_list[-10:]
    ) if articles_list else "لا يوجد"

    prereq_count = len(prereqs_list)

    # Build folders/tree context for admin (from one fetch, no recursion)
    folders_by_parent: dict = {}
    for f in materials["folders"]:
        folders_by_parent.setdefault(f.parent_id, []).append(f)
    items_by_folder: dict = {}
    for it in materials["items"]:
        items_by_folder.setdefault(it.folder_id, []).append(it)

    lines: list[str] = []

    def _walk(parent_id, indent: int) -> None:
        for f in folders_by_parent.get(parent_id, []):
            lines.append(f"{'  ' * indent}• {f.name} (ID: {f.id})")
            for it in items_by_folder.get(f.id, []):
                lines.append(f"{'  ' * (indent+1)}📄 {it.title or 'محتوى'} (ID: {it.id})")
            _walk(f.id, indent + 1)

    _walk(None, 0)
    folders_tree = "\n".join(lines)

    # Build aliases context
    try:
        admin_aliases = await get_all_aliases()
    except Exception:
        admin_aliases = []
    aliases_str = "\n".join(f"'{a.alias}' ← {a.course_name} ({a.course_code})" for a in admin_aliases) or "لا يوجد"

    # Build conversation history
    history_lines = []
    for turn in admin_history[-5:]:
        history_lines.append(f"المشرف: {turn['user'][:200]}")
        history_lines.append(f"المساعد: {turn['assistant'][:300]}")
    history_context = "\n".join(history_lines)
    history_note = f"\nسجل المحادثة الجارية مع المشرف:\n{history_context}\n" if history_context else ""

    admin_system_prompt = (
        f"أنت المساعد الإداري الذكي لمنصة «نَافِذَة». تتحدث الآن مع: {role_info['rank_label']}.\n"
        "تفهم اللهجة الليبية والفصحى بطلاقة، وتربط كلام المشرف بآخر 3-5 رسائل في المحادثة الجارية.\n"
        "ممنوع استخدام ** أو * أو أي تنسيق Markdown في ردك — اكتب نصاً عربياً واضحاً فقط، وبدون أي تفكير داخلي بالإنجليزية.\n\n"
        "⚡ الأوامر البرمجية المتاحة (اكتب كل أمر في سطر مستقل يبدأ بالكود، ويمكنك تنفيذ عدة أوامر معاً في نفس الرد):\n"
        "- [ADD_SHEET] اسم_المجلد_أو_رقمه | اسم_الشيت | الرابط1 الرابط2 ... ← (أسهل طريقة!) إضافة شيت مع روابطه مباشرة داخل مجلد موجود أو جديد\n"
        "- [ANALYZE_SHEETS] ← تحليل واستخراج محتوى جميع شيتات القنوات وحفظها كمقالات معرفية للـ AI\n"
        "- [ADD_FOLDER] اسم المجلد | ID_المجلد_الأب (0 للرئيسي)\n"
        "- [ADD_ITEM] ID_المجلد | عنوان المادة\n"
        "- [ADD_LINK] ID_العنصر | رابط t.me/...\n"
        "- [RENAME_FOLDER] ID | الاسم_الجديد\n"
        "- [RENAME_ITEM] ID | العنوان_الجديد\n"
        "- [UPDATE_LINK] ID | الرابط_الجديد\n"
        "- [DEL_FOLDER] ID\n"
        "- [DEL_ITEM] ID\n"
        "- [DEL_LINK] ID\n"
        "- [LIST_FOLDERS] ← عرض شجرة المجلدات والمواد\n"
        "- [ADD_QA] السؤال | الجواب ← إضافة سؤال/جواب\n"
        "- [EDIT_QA] الرقم | السؤال_الجديد | الجواب_الجديد ← تعديل سؤال/جواب موجود\n"
        "- [DEL_QA] الرقم1 الرقم2 ... ← حذف أسئلة بأرقامها\n"
        "- [LIST_QA] ← عرض كل الأسئلة\n"
        "- [ADD_ARTICLE] العنوان | المحتوى ← إضافة مقال أو إعلان\n"
        "- [EDIT_ARTICLE] الرقم | العنوان_الجديد | المحتوى_الجديد ← تعديل مقال موجود\n"
        "- [DEL_ARTICLE] الرقم ← حذف مقال برقمه\n"
        "- [LIST_ARTICLES] ← عرض كل المقالات\n"
        "- [ADD_PREREQ] كود_المادة | اسم_المادة | كود_المتطلب | اسم_المتطلب\n"
        "- [ADD_ALIAS] الاسم_البديل | كود_المادة | اسم_المادة ← حفظ اسم بديل لمادة\n"
        "- [VIEW_MESSAGES] ← عرض رسائل التواصل الواردة غير المقروءة\n"
        "- [SEND_MSG] معرف_أو_يوزر_أو_اسم_الطالب | الرسالة ← إرسال رسالة لمستخدم معين (مع زر تأكيد)\n"
        "- [SEND_TO_ALL] الرسالة ← إرسال إذاعة لكل المستخدمين (مع زر تأكيد)\n"
        "- [ADD_REPLY] الكلمة | الرد ← إضافة رد تلقائي سريع\n"
        "- [DEL_REPLY] الرقم ← حذف رد سريع\n"
        "- [LIST_REPLIES] ← عرض كل الردود السريعة\n"
        "- [BAN] user_id ← حظر مستخدم\n"
        "- [UNBAN] user_id ← إلغاء حظر\n"
        "- [SEARCH_USER] نص_البحث ← البحث عن مستخدم بالاسم أو المعرف أو اليوزر\n"
        "- [STATS] ← عرض إحصائيات البوت الشاملة\n"
        "- [USER_LOGS] user_id_أو_0_للكل ← عرض آخر سجلات نشاط المستخدمين\n"
        "- [AI_TOGGLE] on_أو_off ← تشغيل أو إيقاف المساعد الذكي للطلاب (للسوبر أدمن فقط)\n"
        "- [CLEAR_PREREQS] ← مسح المتطلبات الدراسية بالكامل (للسوبر أدمن فقط)\n\n"
        f"🔐 صلاحيات هذا المشرف الحالية: سوبر={role_info['is_super']} | إدارة_محتوى={role_info['can_manage']} | رد_تواصل={role_info['can_reply']} | حظر={role_info['can_ban']} | سجلات={role_info['can_view_logs']}.\n"
        "إذا طلب المشرف أمراً خارج صلاحيات رتبته، اعتذر له بلطف ووضّح أن هذا الأمر مخصص للسوبر أدمن أو يحتاج صلاحية إضافية.\n\n"
        f"الأسئلة المحفوظة: {qa_context}\n"
        f"المقالات: {art_context}\n"
        f"المتطلبات الدراسية: {prereq_count} علاقة\n"
        f"الأسماء البديلة:\n{aliases_str}\n"
        f"المجلدات:\n{folders_tree[:3000]}"
        f"{history_note}"
    )

    answer = await call_gemini(q, system_prompt=admin_system_prompt, use_groq=False, history=admin_history[-5:])
    if not answer:
        answer = await call_gemini(q, system_prompt=admin_system_prompt, use_groq=True, history=admin_history[-5:])
    if not answer:
        await message.answer("⚠️ فشل الحصول على رد من الذكاء الاصطناعي.", reply_markup=_rm)
        return

    clean_full = _strip_cot(answer)

    # Save to history (keep last 6)
    admin_history.append({"user": q, "assistant": clean_full or answer})
    admin_history = admin_history[-6:]
    _ADMIN_CHAT_HISTORY[uid] = list(admin_history)
    await state.update_data(admin_history=admin_history)

    cmd_pattern = re.compile(
        r"^\[(ADD_SHEET|ANALYZE_SHEETS|ADD_QA|EDIT_QA|DEL_QA|LIST_QA|ADD_ARTICLE|EDIT_ARTICLE|DEL_ARTICLE|LIST_ARTICLES|"
        r"CLEAR_PREREQS|ADD_PREREQ|ADD_FOLDER|ADD_ITEM|ADD_LINK|DEL_FOLDER|DEL_ITEM|DEL_LINK|"
        r"RENAME_FOLDER|RENAME_ITEM|UPDATE_LINK|LIST_FOLDERS|BAN|UNBAN|VIEW_MESSAGES|"
        r"STATS|SEARCH_USER|USER_LOGS|AI_TOGGLE|ADD_ALIAS|ADD_REPLY|DEL_REPLY|LIST_REPLIES|"
        r"SEND_TO_ALL|SEND_MSG)\]\s*(.*)$",
        re.IGNORECASE,
    )

    commands_to_run: list[tuple[str, str]] = []
    chat_lines: list[str] = []
    for raw_line in (clean_full or answer).splitlines():
        sline = raw_line.strip().lstrip("•-* ").strip()
        m = cmd_pattern.match(sline)
        if m:
            commands_to_run.append((m.group(1).upper(), m.group(2).strip()))
        else:
            chat_lines.append(raw_line)

    if not commands_to_run:
        await safe_send(message, clean_full or answer, reply_markup=_rm)
        return

    # Permission enforcement per command category
    super_only_cmds = {"AI_TOGGLE", "CLEAR_PREREQS"}
    manage_cmds = {
        "ADD_SHEET", "ADD_FOLDER", "ADD_ITEM", "ADD_LINK", "RENAME_FOLDER", "RENAME_ITEM",
        "UPDATE_LINK", "DEL_FOLDER", "DEL_ITEM", "DEL_LINK",
        "ADD_QA", "EDIT_QA", "DEL_QA", "ADD_ARTICLE", "EDIT_ARTICLE", "DEL_ARTICLE",
        "ADD_PREREQ", "ADD_ALIAS", "DEL_REPLY", "SEND_TO_ALL",
    }
    moderator_blocked_cmds = {
        "DEL_FOLDER", "DEL_ITEM", "DEL_LINK", "DEL_QA", "DEL_ARTICLE", "SEND_TO_ALL",
        "CLEAR_PREREQS", "AI_TOGGLE",
    }
    ban_cmds = {"BAN", "UNBAN", "SEARCH_USER"}
    logs_cmds = {"STATS", "USER_LOGS"}
    reply_cmds = {"VIEW_MESSAGES", "SEND_MSG", "ADD_REPLY", "LIST_REPLIES"}

    # If the AI also included a helpful note alongside the commands, send it first
    note_text = "\n".join(chat_lines).strip()
    if note_text and len(note_text) > 3:
        await safe_send(message, note_text, reply_markup=_rm)

    for cmd, arg in commands_to_run:
        if cmd in super_only_cmds and not role_info["is_super"]:
            await message.answer(f"⛔ عذراً، الأمر [{cmd}] مخصص للسوبر أدمن فقط.", reply_markup=_rm)
            continue
        if role_info["rank"] == "moderator" and cmd in moderator_blocked_cmds and not role_info["is_super"]:
            await message.answer(f"⛔ عذراً، الأمر [{cmd}] غير متاح لرتبة مراقب.", reply_markup=_rm)
            continue
        if cmd in manage_cmds and not role_info["can_manage"]:
            await message.answer(f"⛔ عذراً، ليس لديك صلاحية إدارة المحتوى لتنفيذ [{cmd}].", reply_markup=_rm)
            continue
        if cmd in ban_cmds and not role_info["can_ban"]:
            await message.answer(f"⛔ عذراً، ليس لديك صلاحية الحظر وإدارة المستخدمين لتنفيذ [{cmd}].", reply_markup=_rm)
            continue
        if cmd in logs_cmds and not role_info["can_view_logs"]:
            await message.answer(f"⛔ عذراً، ليس لديك صلاحية عرض السجلات والإحصائيات لتنفيذ [{cmd}].", reply_markup=_rm)
            continue
        if cmd in reply_cmds and not (role_info["can_reply"] or role_info["can_manage"]):
            await message.answer(f"⛔ عذراً، ليس لديك صلاحية الرد والتواصل لتنفيذ [{cmd}].", reply_markup=_rm)
            continue

        if cmd == "ADD_SHEET":
            parts = [p.strip() for p in arg.split("|")]
            if len(parts) < 2:
                await message.answer("❌ التنسيق: [ADD_SHEET] اسم_المجلد | اسم_الشيت | الرابط", reply_markup=_rm)
                continue
            folder_ref = parts[0]
            sheet_title = parts[1]
            links_raw = " ".join(parts[2:]) if len(parts) >= 3 else ""

            mats = await get_all_materials()
            target_folder = None
            if folder_ref.isdigit():
                target_folder = next((f for f in mats["folders"] if f.id == int(folder_ref)), None)
            if not target_folder:
                nf = _normalize_ar(folder_ref)
                target_folder = next((f for f in mats["folders"] if _normalize_ar(f.name) == nf), None)
            if not target_folder:
                nf = _normalize_ar(folder_ref)
                target_folder = next((f for f in mats["folders"] if nf in _normalize_ar(f.name) or _normalize_ar(f.name) in nf), None)
            if not target_folder:
                target_folder = await add_folder(folder_ref, None)

            existing_item = next(
                (it for it in mats["items"] if it.folder_id == target_folder.id and _normalize_ar(it.title or "") == _normalize_ar(sheet_title)),
                None,
            )
            item_obj = existing_item or await add_content_item(target_folder.id, sheet_title)

            added_links = 0
            for m_lnk in LINK_REGEX.finditer(links_raw):
                is_priv = bool(m_lnk.group(1))
                ch_part, msg_id_part = m_lnk.group(2), int(m_lnk.group(3))
                resolved_chat = _resolve_channel_chat_id(ch_part, is_private_c=is_priv)
                full_url = m_lnk.group(0)
                if not full_url.startswith("http"):
                    full_url = "https://" + full_url
                await add_content_link(item_obj.id, full_url, str(resolved_chat), msg_id_part)
                added_links += 1
                try:
                    fwd = await message.bot.forward_message(
                        chat_id=message.chat.id,
                        from_chat_id=resolved_chat,
                        message_id=msg_id_part,
                    )
                    await index_single_sheet_message(message.bot, fwd, target_folder.name, item_obj.title or sheet_title)
                    try:
                        await fwd.delete()
                    except Exception:
                        pass
                except Exception:
                    pass

            await save_admin_action(
                uid,
                message.from_user.full_name or "مشرف",
                "add_content",
                f"📄 عبر AI: {sheet_title} في مجلد {target_folder.name} ({added_links} رابط)",
            )
            await message.answer(
                f"✅ تم حفظ الشيت وتحليل محتواه للـ AI بنجاح!\n"
                f"📂 المجلد: {target_folder.name} (ID: {target_folder.id})\n"
                f"📄 الشيت: {item_obj.title} (ID: {item_obj.id})\n"
                f"🔗 الروابط المرفقة الآن: {added_links}",
                reply_markup=_rm,
                parse_mode=None,
            )

        elif cmd == "ANALYZE_SHEETS":
            await ai_analyze_channel_sheets(message)

        elif cmd == "ADD_QA":
            parts = arg.split("|")
            if len(parts) >= 2:
                qq, aa = parts[0].strip(), "|".join(parts[1:]).strip()
                qa = await add_qa(qq, aa)
                await message.answer(f"✅ تم إضافة سؤال/جواب (رقم {qa.id}):\n📌 {qq}", reply_markup=_rm)
            else:
                await message.answer("❌ التنسيق: [ADD_QA] السؤال | الجواب", reply_markup=_rm)

        elif cmd == "EDIT_QA":
            parts = arg.split("|")
            if len(parts) >= 3 and parts[0].strip().isdigit():
                qid = int(parts[0].strip())
                qq, aa = parts[1].strip(), "|".join(parts[2:]).strip()
                ok = await update_qa(qid, question=qq, answer=aa)
                await message.answer(f"✅ تم تعديل السؤال #{qid} بنجاح." if ok else f"❌ السؤال #{qid} غير موجود.", reply_markup=_rm)
            else:
                await message.answer("❌ التنسيق: [EDIT_QA] الرقم | السؤال | الجواب", reply_markup=_rm)

        elif cmd == "DEL_QA":
            ids = {int(t) for t in arg.replace(",", " ").split() if t.isdigit()}
            if not ids:
                await message.answer("❌ أرسل أرقام الأسئلة للحذف.", reply_markup=_rm)
            else:
                deleted = sum([1 for qa_id in ids if await delete_qa(qa_id)])
                await message.answer(f"✅ تم حذف {deleted} من {len(ids)} سؤال.", reply_markup=_rm)

        elif cmd == "LIST_QA":
            qas = await get_all_qa()
            if qas:
                for i in range(0, len(qas), 10):
                    chunk = "\n".join(f"🔹 {qa.id}: 📌 {qa.question[:55]}\n   💬 {qa.answer[:65]}" for qa in qas[i:i+10])
                    await message.answer(f"📋 الأسئلة المحفوظة:\n\n{chunk}", reply_markup=_rm, parse_mode=None)
            else:
                await message.answer("❌ لا توجد أسئلة محفوظة.", reply_markup=_rm)

        elif cmd == "ADD_ARTICLE":
            parts = arg.split("|")
            if len(parts) >= 2:
                title, content = parts[0].strip(), "|".join(parts[1:]).strip()
                art = await add_article(title, content)
                await message.answer(f"✅ تم إضافة المقال (#{art.id}): {art.title}", reply_markup=_rm, parse_mode=None)
            else:
                await message.answer("❌ التنسيق: [ADD_ARTICLE] العنوان | المحتوى", reply_markup=_rm)

        elif cmd == "EDIT_ARTICLE":
            parts = arg.split("|")
            if len(parts) >= 3 and parts[0].strip().isdigit():
                aid = int(parts[0].strip())
                title, content = parts[1].strip(), "|".join(parts[2:]).strip()
                ok = await update_article(aid, title=title, content=content)
                await message.answer(f"✅ تم تعديل المقال #{aid} بنجاح." if ok else f"❌ المقال #{aid} غير موجود.", reply_markup=_rm)
            else:
                await message.answer("❌ التنسيق: [EDIT_ARTICLE] الرقم | العنوان | المحتوى", reply_markup=_rm)

        elif cmd == "DEL_ARTICLE":
            try:
                art_id = int(arg.split()[0])
                ok = await delete_article(art_id)
                await message.answer(f"✅ تم حذف المقال #{art_id}" if ok else "❌ المقال غير موجود.", reply_markup=_rm)
            except (ValueError, IndexError):
                await message.answer("❌ أرسل رقم المقال.", reply_markup=_rm)

        elif cmd == "LIST_ARTICLES":
            arts = await get_all_articles()
            if arts:
                out_lines = [f"🔹 {art.id}: {art.title} ({len(art.content)} حرف)" for art in arts]
                await safe_send(message, "📰 المقالات المحفوظة:\n\n" + "\n".join(out_lines), reply_markup=_rm)
            else:
                await message.answer("❌ لا توجد مقالات.", reply_markup=_rm)

        elif cmd == "CLEAR_PREREQS":
            await clear_prerequisites()
            await message.answer("✅ تم مسح المتطلبات الدراسية.", reply_markup=_rm)

        elif cmd == "ADD_PREREQ":
            parts = arg.split("|")
            if len(parts) >= 4:
                cc, cn, pc, pn = [p.strip() for p in parts[:4]]
                await add_prerequisite(course_code=cc, course_name=cn, prerequisite_code=pc, prerequisite_name=pn)
                await message.answer(f"✅ تم إضافة متطلب: {cn} ({cc}) ← يحتاج {pn} ({pc})", reply_markup=_rm, parse_mode=None)
            else:
                await message.answer("❌ التنسيق: كود_المادة | اسم_المادة | كود_المتطلب | اسم_المتطلب", reply_markup=_rm)

        elif cmd == "ADD_FOLDER":
            parts = arg.split("|")
            name = parts[0].strip()
            parent_id = None
            if len(parts) >= 2 and parts[1].strip().isdigit():
                pid = int(parts[1].strip())
                parent_id = pid if pid != 0 else None
            f = await add_folder(name, parent_id)
            await message.answer(f"✅ تم إضافة مجلد: {f.name} (ID: {f.id})", reply_markup=_rm, parse_mode=None)

        elif cmd == "ADD_ITEM":
            parts = arg.split("|")
            if len(parts) >= 1 and parts[0].strip().isdigit():
                fid = int(parts[0].strip())
                title = parts[1].strip() if len(parts) >= 2 else None
                ci = await add_content_item(fid, title)
                await message.answer(f"✅ تم إضافة مادة: {ci.title or 'محتوى'} (ID: {ci.id})", reply_markup=_rm, parse_mode=None)
            else:
                await message.answer("❌ التنسيق: ID_المجلد | عنوان المادة", reply_markup=_rm)

        elif cmd == "ADD_LINK":
            parts = arg.split("|")
            if len(parts) >= 2 and parts[0].strip().isdigit():
                iid = int(parts[0].strip())
                link = parts[1].strip()
                cl = await add_content_link(iid, link)
                await message.answer(f"✅ تم إضافة رابط (ID: {cl.id})", reply_markup=_rm)
            else:
                await message.answer("❌ التنسيق: ID_العنصر | الرابط", reply_markup=_rm)

        elif cmd == "DEL_FOLDER":
            try:
                fid = int(arg.split()[0])
                ok = await remove_folder(fid)
                await message.answer(f"✅ تم حذف المجلد {fid}" if ok else "❌ المجلد غير موجود", reply_markup=_rm)
            except (ValueError, IndexError):
                await message.answer("❌ أرسل رقم المجلد.", reply_markup=_rm)

        elif cmd == "DEL_ITEM":
            try:
                iid = int(arg.split()[0])
                ok = await remove_content_item(iid)
                await message.answer(f"✅ تم حذف المادة {iid}" if ok else "❌ المادة غير موجودة", reply_markup=_rm)
            except (ValueError, IndexError):
                await message.answer("❌ أرسل رقم المادة.", reply_markup=_rm)

        elif cmd == "DEL_LINK":
            try:
                lid = int(arg.split()[0])
                ok = await remove_content_link(lid)
                await message.answer(f"✅ تم حذف الرابط {lid}" if ok else "❌ الرابط غير موجود", reply_markup=_rm)
            except (ValueError, IndexError):
                await message.answer("❌ أرسل رقم الرابط.", reply_markup=_rm)

        elif cmd == "RENAME_FOLDER":
            parts = arg.split("|")
            if len(parts) >= 2 and parts[0].strip().isdigit():
                fid = int(parts[0].strip())
                new_name = parts[1].strip()
                ok = await rename_folder(fid, new_name)
                await message.answer(f"✅ تم إعادة تسمية المجلد {fid} إلى {new_name}" if ok else "❌ المجلد غير موجود", reply_markup=_rm, parse_mode=None)
            else:
                await message.answer("❌ التنسيق: ID | الاسم_الجديد", reply_markup=_rm)

        elif cmd == "RENAME_ITEM":
            parts = arg.split("|")
            if len(parts) >= 2 and parts[0].strip().isdigit():
                iid = int(parts[0].strip())
                title = parts[1].strip()
                ok = await update_content_item_title(iid, title)
                await message.answer(f"✅ تم تحديث عنوان المادة {iid} إلى {title}" if ok else "❌ المادة غير موجودة", reply_markup=_rm, parse_mode=None)
            else:
                await message.answer("❌ التنسيق: ID | العنوان_الجديد", reply_markup=_rm)

        elif cmd == "UPDATE_LINK":
            parts = arg.split("|")
            if len(parts) >= 2 and parts[0].strip().isdigit():
                lid = int(parts[0].strip())
                new_link = parts[1].strip()
                ok = await update_content_link(lid, new_link)
                await message.answer(f"✅ تم تحديث الرابط {lid}" if ok else "❌ الرابط غير موجود", reply_markup=_rm)
            else:
                await message.answer("❌ التنسيق: ID | الرابط_الجديد", reply_markup=_rm)

        elif cmd == "LIST_FOLDERS":
            if folders_tree:
                await safe_send(message, f"📂 المجلدات والمواد:\n{folders_tree}", reply_markup=_rm)
            else:
                await message.answer("❌ لا توجد مجلدات.", reply_markup=_rm)

        elif cmd == "BAN":
            try:
                uid = int(arg.split()[0])
                ok = await ban_user(uid)
                await message.answer(f"✅ تم حظر المستخدم {uid}" if ok else "❌ المستخدم غير موجود", reply_markup=_rm)
            except (ValueError, IndexError):
                await message.answer("❌ أرسل رقم المستخدم.", reply_markup=_rm)

        elif cmd == "UNBAN":
            try:
                uid = int(arg.split()[0])
                ok = await unban_user(uid)
                await message.answer(f"✅ تم إلغاء حظر المستخدم {uid}" if ok else "❌ المستخدم غير موجود", reply_markup=_rm)
            except (ValueError, IndexError):
                await message.answer("❌ أرسل رقم المستخدم.", reply_markup=_rm)

        elif cmd == "VIEW_MESSAGES":
            from database.crud import get_unread_messages
            msgs = await get_unread_messages()
            if msgs:
                for m in msgs[:10]:
                    u = await get_user(m.user_id)
                    uname = u.full_name if u else f"ID: {m.user_id}"
                    await message.answer(
                        f"💬 من: {uname}\n🆔 {m.user_id}\n{m.content or m.caption or ''}",
                        reply_markup=_rm,
                        parse_mode=None,
                    )
            else:
                await message.answer("📭 لا توجد رسائل تواصل غير مقروءة حالياً.", reply_markup=_rm)

        elif cmd == "STATS":
            st = await get_stats()
            qas_count = len(await get_all_qa())
            arts_count = len(await get_all_articles())
            await message.answer(
                f"📊 إحصائيات منصة نَافِذَة:\n\n"
                f"👤 المستخدمون: {st['users']}\n"
                f"👑 المشرفون: {st['admins']}\n"
                f"🚫 المحظورون: {st['banned']}\n"
                f"💬 إجمالي الرسائل: {st['messages']} (غير مقروء: {st['unread']})\n"
                f"⚡ الردود السريعة: {st['replies']}\n"
                f"📚 أسئلة الـ AI: {qas_count}\n"
                f"📰 مقالات الـ AI: {arts_count}\n"
                f"🔗 العلاقات الدراسية: {prereq_count}",
                reply_markup=_rm,
                parse_mode=None,
            )

        elif cmd == "SEARCH_USER":
            q_search = arg.lstrip("@").strip().lower()
            all_u = await get_all_users()
            matched = [
                u for u in all_u
                if q_search in str(u.user_id)
                or (u.full_name and q_search in u.full_name.lower())
                or (u.username and q_search in u.username.lower())
            ]
            if matched:
                u_lines = [
                    f"👤 {u.full_name} (@{u.username or 'بدون'}) — ID: {u.user_id}"
                    + (" [محظور 🚫]" if u.is_banned else "")
                    + (" [مشرف 👑]" if u.is_admin else "")
                    for u in matched[:15]
                ]
                await safe_send(message, "🔍 نتائج البحث عن المستخدمين:\n\n" + "\n".join(u_lines), reply_markup=_rm)
            else:
                await message.answer(f"❌ لم يتم العثور على مستخدم يطابق: {arg}", reply_markup=_rm, parse_mode=None)

        elif cmd == "USER_LOGS":
            target_uid = int(arg) if arg.isdigit() and int(arg) != 0 else None
            msgs = await get_all_user_messages(limit=30)
            if target_uid:
                msgs = [m for m in msgs if m.user_id == target_uid]
            if msgs:
                log_lines = []
                for m in msgs[:15]:
                    u = await get_user(m.user_id)
                    uname = u.full_name if u else str(m.user_id)
                    log_lines.append(f"👤 {uname} ({m.user_id}) [{m.created_at.strftime('%m-%d %H:%M')}]:\n   {(m.content or m.caption or '')[:100]}")
                await safe_send(message, "📋 سجلات المستخدمين:\n\n" + "\n\n".join(log_lines), reply_markup=_rm)
            else:
                await message.answer("📋 لا توجد سجلات مطابقة.", reply_markup=_rm)

        elif cmd == "AI_TOGGLE":
            turn_on = arg.lower() in ("on", "true", "1", "تشغيل", "تفعيل", "شغل")
            set_ai_active(turn_on)
            await message.answer(
                "🟢 تم تشغيل نَافِذَة الـ AI للمستخدمين." if turn_on else "🔴 تم إيقاف نَافِذَة الـ AI للمستخدمين.",
                reply_markup=_rm,
            )

        elif cmd == "ADD_ALIAS":
            parts = arg.split("|")
            if len(parts) >= 3:
                alias_name = parts[0].strip().lower()
                course_code = parts[1].strip()
                course_name = parts[2].strip()
                await add_alias(alias_name, course_code, course_name)
                await message.answer(f"✅ تم حفظ الاسم البديل: '{alias_name}' ← {course_name} ({course_code})", reply_markup=_rm, parse_mode=None)
            else:
                await message.answer("❌ التنسيق: الاسم_البديل | كود_المادة | اسم_المادة", reply_markup=_rm)

        elif cmd == "ADD_REPLY":
            parts = arg.split("|")
            if len(parts) >= 2:
                trigger, response = parts[0].strip(), "|".join(parts[1:]).strip()
                ar = await add_autoreply(trigger, response)
                await message.answer(f"✅ تم إضافة رد سريع (رقم {ar.id}): {trigger}", reply_markup=_rm, parse_mode=None)
            else:
                await message.answer("❌ التنسيق: الكلمة | الرد", reply_markup=_rm)

        elif cmd == "DEL_REPLY":
            try:
                rid = int(arg.split()[0])
                ok = await remove_autoreply(rid)
                await message.answer(f"✅ تم حذف الرد السريع {rid}" if ok else "❌ الرقم غير موجود", reply_markup=_rm)
            except (ValueError, IndexError):
                await message.answer("❌ أرسل رقم الرد.", reply_markup=_rm)

        elif cmd == "LIST_REPLIES":
            replies = await get_all_autoreplies()
            if replies:
                r_lines = [f"{ar.id}: {ar.trigger} ← {ar.response[:50]}" for ar in replies]
                await safe_send(message, "📋 الردود السريعة:\n\n" + "\n".join(r_lines), reply_markup=_rm)
            else:
                await message.answer("❌ لا توجد ردود سريعة.", reply_markup=_rm)

        elif cmd == "SEND_TO_ALL":
            if not arg:
                await message.answer("❌ أرسل نص الرسالة.", reply_markup=_rm)
            else:
                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                kb = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ تأكيد الإرسال", callback_data="broadcast:confirm"),
                     InlineKeyboardButton(text="❌ إلغاء", callback_data="broadcast:cancel")]
                ])
                await state.update_data(broadcast_content={"type": "text", "text": arg})
                await message.answer(
                    f"📢 معاينة الرسالة:\n\n{arg[:300]}\n\nهل أنت متأكد من إرسالها لكل المستخدمين؟",
                    reply_markup=kb,
                    parse_mode=None,
                )

        elif cmd == "SEND_MSG":
            parts = arg.split("|")
            if len(parts) >= 2:
                target_ref = parts[0].strip()
                msg = "|".join(parts[1:]).strip()
                target_user = None
                target_uid = None
                if target_ref.isdigit():
                    target_uid = int(target_ref)
                    target_user = await get_user(target_uid)
                else:
                    q_ref = target_ref.lstrip("@").lower()
                    all_u = await get_all_users()
                    target_user = next(
                        (u for u in all_u if (u.username and u.username.lower() == q_ref) or (u.full_name and q_ref in u.full_name.lower())),
                        None,
                    )
                    if target_user:
                        target_uid = target_user.user_id
                if target_uid:
                    uname = target_user.full_name if target_user else str(target_uid)
                    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✅ تأكيد الإرسال", callback_data=f"sendmsg:confirm:{target_uid}"),
                         InlineKeyboardButton(text="❌ إلغاء", callback_data="sendmsg:cancel")]
                    ])
                    await state.update_data(sendmsg_text=msg)
                    await message.answer(
                        f"📩 رسالة إلى {uname} ({target_uid}):\n\n{msg[:300]}\n\nهل أنت متأكد؟",
                        reply_markup=kb,
                        parse_mode=None,
                    )
                else:
                    await message.answer(f"❌ لم يتم العثور على المستخدم: {target_ref}", reply_markup=_rm, parse_mode=None)
            else:
                await message.answer("❌ التنسيق: معرف_أو_اسم_المستخدم | الرسالة", reply_markup=_rm)


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

    try:
        await message.bot.send_chat_action(message.chat.id, "typing")
    except Exception:
        pass

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
    answer = await call_gemini(prompt, max_tokens=4096)
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
        await callback.bot.send_message(chat_id=uid, text=text, parse_mode=None)
        await callback.message.answer(f"✅ تم إرسال الرسالة إلى {uid}.")
    except Exception as e:
        await callback.message.answer(f"⚠️ فشل الإرسال: {str(e)[:100]}", parse_mode=None)
    await callback.answer()


@router.callback_query(AdminFilter(), F.data == "sendmsg:cancel")
async def ai_sendmsg_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer("❌ تم إلغاء الإرسال.")
    await callback.answer()
