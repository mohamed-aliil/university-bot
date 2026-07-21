import asyncio
import aiohttp
import logging
from config import settings

logger = logging.getLogger(__name__)

# Simple rate limiter: track last request time per API key
_last_req_time: dict[str, float] = {}
_rate_lock = asyncio.Lock()

async def _wait_for_rate_limit(api_key: str) -> None:
    """Ensure max 30 requests/minute per API key (2s between requests)."""
    async with _rate_lock:
        import time
        now = time.monotonic()
        last = _last_req_time.get(api_key, 0)
        elapsed = now - last
        min_gap = 2.0  # 30 RPM = 1 req per 2 seconds
        if elapsed < min_gap:
            wait = min_gap - elapsed
            logger.debug("Rate limit: waiting %.2fs for key %s...", wait, api_key[:8])
            await asyncio.sleep(wait)
        _last_req_time[api_key] = time.monotonic()


async def call_gemini(prompt: str, system_prompt: str = "") -> str | None:
    try:
        # Try Groq keys first (free, generous quota)
        groq_keys = settings.groq_keys
        for key in groq_keys:
            result = await _call_groq(prompt, system_prompt, key)
            if result:
                return result

        # Fallback to Gemini keys
        for key in settings.gemini_keys:
            result = await _call_gemini(prompt, system_prompt, key)
            if result:
                return result
    except Exception:
        logger.exception("call_gemini failed")
    return None


async def _call_groq(prompt: str, system_prompt: str, api_key: str) -> str | None:
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    MODELS = [
        "openai/gpt-oss-120b",
        "qwen/qwen3.6-27b",
        "gpt-oss-120b",
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
        for attempt in range(3):  # Retry up to 3 times on 429
            try:
                await _wait_for_rate_limit(api_key)
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        json=payload,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=30),
                    ) as resp:
                        if resp.status == 429:
                            body = await resp.text()
                            logger.warning("Groq 429 for %s (attempt %d/3): %s", model, attempt + 1, body[:100])
                            if attempt < 2:
                                wait = 2 ** attempt  # 1s, 2s
                                logger.info("Retrying %s in %ds...", model, wait)
                                await asyncio.sleep(wait)
                                continue
                            break  # Give up on this model after 3 attempts
                        if resp.status != 200:
                            body = await resp.text()
                            if "decommissioned" in body or "deprecated" in body:
                                logger.warning("Groq model %s deprecated, trying next", model)
                                break  # Try next model
                            logger.warning("Groq %s error %s: %s", model, resp.status, body[:200])
                            break  # Try next model
                        data = await resp.json()
                        choices = data.get("choices", [])
                        if choices:
                            text = choices[0].get("message", {}).get("content", "")
                            if text:
                                logger.info("Groq model %s used successfully (tokens: %s)", model,
                                             choices[0].get("usage", {}).get("total_tokens", "?"))
                                return text.strip()
            except asyncio.TimeoutError:
                logger.warning("Groq %s timeout (attempt %d/3)", model, attempt + 1)
                if attempt < 2:
                    await asyncio.sleep(1)
                    continue
            except Exception as e:
                logger.exception("Groq %s failed: %s", model, e)
                break  # Non-retryable error, try next model
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
