import aiohttp
import logging
from config import settings

logger = logging.getLogger(__name__)


async def call_gemini(prompt: str, system_prompt: str = "") -> str | None:
    """
    Send a prompt to Gemini 1.5 Flash with optional system prompt.
    Rotates through configured API keys.
    Returns text response or None on failure.
    """
    keys = settings.gemini_keys
    if not keys:
        return None

    if system_prompt:
        full_prompt = f"{system_prompt}\n\nالرجاء الرد على ما يلي:\n{prompt}"
    else:
        full_prompt = prompt

    for key in keys:
        url = f"https://generativelanguage.googleapis.com/v1/models/gemini-1.5-flash:generateContent?key={key}"
        payload = {
            "contents": [{"parts": [{"text": full_prompt}]}]
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.warning("Gemini API error %s for key %s: %s", resp.status, key[:8], body[:300])
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
