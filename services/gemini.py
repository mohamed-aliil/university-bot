import aiohttp
import logging
from config import settings

logger = logging.getLogger(__name__)


async def call_gemini(prompt: str, system_prompt: str = "") -> str | None:
    keys = settings.gemini_keys
    if not keys:
        return None

    if system_prompt:
        full_prompt = f"{system_prompt}\n\nالرجاء الرد على ما يلي:\n{prompt}"
    else:
        full_prompt = prompt

    MODELS = [
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-1.5-flash-002",
        "gemini-2.0-flash-lite",
    ]

    for key in keys:
        for model in MODELS:
            for version in ("v1beta", "v1"):
                url = f"https://generativelanguage.googleapis.com/{version}/models/{model}:generateContent?key={key}"
                payload = {"contents": [{"parts": [{"text": full_prompt}]}]}
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            url, json=payload, timeout=aiohttp.ClientTimeout(total=30)
                        ) as resp:
                            if resp.status != 200:
                                body = await resp.text()
                                logger.warning(
                                    "Gemini %s/%s error %s: %s",
                                    version, model, resp.status, body[:100],
                                )
                                continue
                            data = await resp.json()
                            candidates = data.get("candidates", [])
                            if candidates:
                                text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                                if text:
                                    return text.strip()
                except Exception as e:
                    logger.exception("Gemini %s/%s failed: %s", version, model, e)
                    continue
    return None
