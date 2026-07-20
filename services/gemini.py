import aiohttp
import logging
from config import settings

logger = logging.getLogger(__name__)


async def call_gemini(prompt: str, system_prompt: str = "") -> str | None:
    # Try Groq first (free, generous quota)
    groq_key = settings.GROQ_API_KEY
    if groq_key:
        result = await _call_groq(prompt, system_prompt, groq_key)
        if result:
            return result

    # Fallback to Gemini keys
    for key in settings.gemini_keys:
        result = await _call_gemini(prompt, system_prompt, key)
        if result:
            return result
    return None


async def _call_groq(prompt: str, system_prompt: str, api_key: str) -> str | None:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    MODELS = [
        "openai/gpt-oss-120b",
        "qwen/qwen3.6-27b",
        "openai/gpt-oss-20b",
        "gpt-oss-120b",
        "gpt-oss-20b",
    ]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    for model in MODELS:
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 1024,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        if "decommissioned" in body or "deprecated" in body:
                            logger.warning("Groq model %s deprecated, trying next", model)
                            continue
                        logger.warning("Groq %s error %s: %s", model, resp.status, body[:200])
                        continue
                    data = await resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        text = choices[0].get("message", {}).get("content", "")
                        if text:
                            return text.strip()
        except Exception as e:
            logger.exception("Groq %s failed: %s", model, e)
            continue
    return None


async def _call_gemini(prompt: str, system_prompt: str, api_key: str) -> str | None:
    if system_prompt:
        full_prompt = f"{system_prompt}\n\nالرجاء الرد على ما يلي:\n{prompt}"
    else:
        full_prompt = prompt

    MODELS = ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash"]

    for model in MODELS:
        url = f"https://generativelanguage.googleapis.com/v1/models/{model}:generateContent?key={api_key}"
        payload = {"contents": [{"parts": [{"text": full_prompt}]}]}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload, timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    if resp.status == 429:
                        logger.warning("Quota exceeded for Gemini key")
                        return None
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                        if text:
                            return text.strip()
        except Exception as e:
            logger.exception("Gemini %s failed: %s", model, e)
            continue
    return None
