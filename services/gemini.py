import asyncio
import aiohttp
import logging
from config import settings

logger = logging.getLogger(__name__)

# Token bucket rate limiters per API key: 30 tokens max, refill 0.5/sec (30 RPM)
_tokens: dict[str, float] = {}
_last_refill: dict[str, float] = {}
_rate_lock = asyncio.Lock()

async def _wait_for_rate_limit(api_key: str) -> None:
    """Allow burst of 30 requests, then throttle to 0.5 req/sec."""
    import time
    while True:
        async with _rate_lock:
            now = time.monotonic()
            tokens = _tokens.get(api_key, 30.0)
            last = _last_refill.get(api_key, now)
            tokens = min(30.0, tokens + (now - last) * 0.5)
            if tokens >= 1.0:
                _tokens[api_key] = tokens - 1.0
                _last_refill[api_key] = now
                return
            wait = (1.0 - tokens) / 0.5
        # Don't hold the lock while sleeping — other keys/requests can proceed
        logger.debug("Rate limit: waiting %.2fs for key %s...", wait, api_key[:8])
        await asyncio.sleep(wait / 2)  # Recheck halfway to be responsive

async def _pick_best_key(groq_keys: list[str], exclude: set[str] | None = None) -> str | None:
    """Pick the Groq key with the most available tokens (load balancing)."""
    candidates = [k for k in groq_keys if k not in (exclude or set())]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    import time
    async with _rate_lock:
        def _tokens_for(k: str) -> float:
            now = time.monotonic()
            t = _tokens.get(k, 30.0)
            last = _last_refill.get(k, now)
            return min(30.0, t + (now - last) * 0.5)
        best = max(candidates, key=_tokens_for)
    return best


async def call_gemini(prompt: str, system_prompt: str = "") -> str | None:
    try:
        groq_keys = settings.groq_keys
        # Load balance: pick key with most available tokens
        tried = set()
        for _ in groq_keys:
            key = await _pick_best_key(groq_keys, tried)
            if not key:
                break
            tried.add(key)
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
