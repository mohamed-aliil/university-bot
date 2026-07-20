import aiohttp
import logging
from config import settings
from typing import List, Tuple
from itertools import cycle

logger = logging.getLogger(__name__)

_key_cycle = None

def _get_keys():
    global _key_cycle
    keys = settings.gemini_keys
    if not keys:
        return None
    if _key_cycle is None:
        _key_cycle = cycle(keys)
    return _key_cycle


async def call_gemini(prompt: str, system_prompt: str = "") -> str | None:
    """
    Send a prompt to Gemini 1.5 Flash with optional system prompt.
    Rotates through configured API keys.
    Returns text response or None on failure.
    """
    keys = settings.gemini_keys
    if not keys:
        return None

    for key in keys:
        url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}]
        }
        if system_prompt:
            payload["system_instruction"] = {"parts": [{"text": system_prompt}]}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.warning("Gemini API error %s for key %s: %s", resp.status, key[:8], body[:200])
                        continue
                    data = await resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        if text:
                            return text.strip()
        except Exception as e:
            logger.exception("Gemini request failed for key %s: %s", key[:8], e)
            continue
    return None


COLLEGE_KEYWORDS = [
    "امتحان", "مادة", "شيت", "محاضرة", "كلية", "جامعة", "معدل", "دراسة",
    "هندسة", "طب", "علوم", "رياضيات", "فيزياء", "كيمياء", "قسم", "تخصص",
    "دكتور", "أستاذ", "محاضر", "نتيجة", "جدول", "منهج", "كتاب", "مرجع",
    "اختبار", "فاينل", "ميد", "كوئيز", "واجب", "تسليم", "بحث", "مشروع",
    "تخرج", "سكشن", "لاب", "معمل", "ساعة", "Credits", "GPA",
    "شهادة", "قبول", "تسجيل", "مقرر", "حذف", "إضافة", "انذار",
    "اشرح", "عرف", "ماهو", "ماهي", "كيف", "متى", "أين", "لماذا",
]

COLLEGE_WORDS_SET = set(COLLEGE_KEYWORDS)


def is_college_question(text: str) -> bool:
    for word in COLLEGE_WORDS_SET:
        if word in text:
            return True
    return False


def similarity(a: str, b: str) -> float:
    a_set = set(a.lower().split())
    b_set = set(b.lower().split())
    if not a_set or not b_set:
        return 0.0
    intersection = a_set & b_set
    return len(intersection) / max(len(a_set), len(b_set))


async def find_best_qa(question: str, qa_list: list) -> Tuple[str | None, str | None, float]:
    best_q = None
    best_a = None
    best_score = 0.0
    for qa in qa_list:
        score = similarity(question, qa.question)
        if score > best_score:
            best_score = score
            best_q = qa.question
            best_a = qa.answer
    if best_score >= 0.4:
        return best_q, best_a, best_score
    return None, None, 0.0
