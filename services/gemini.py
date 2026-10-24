import asyncio
import aiohttp
import logging
import re
import time
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


async def call_gemini(
    prompt: str,
    system_prompt: str = "",
    max_tokens: int = 1024,
    use_groq: bool = True,
    history: list[dict] | None = None,
) -> str | None:
    global LAST_GROQ_ERROR, LAST_GEMINI_ERROR, LAST_CALL_ERROR
    t0 = time.perf_counter()
    effective_system = system_prompt if system_prompt else _MINIMAL_SYSTEM_PROMPT
    try:
        if use_groq:
            groq_keys = settings.groq_keys
            tried = set()
            for _ in groq_keys:
                key = await _pick_best_key(groq_keys, tried)
                if not key:
                    break
                tried.add(key)
                result = await _call_groq(prompt, effective_system, key, max_tokens=max_tokens, history=history)
                if result:
                    LAST_AI_MS["ms"] = (time.perf_counter() - t0) * 1000
                    return result

        # Fallback to Gemini keys (always gets full system prompt)
        for key in settings.gemini_keys:
            result = await _call_gemini(prompt, effective_system, key, max_tokens=max_tokens, history=history)
            if result:
                LAST_AI_MS["ms"] = (time.perf_counter() - t0) * 1000
                return result
    except Exception as e:
        LAST_CALL_ERROR = f"{type(e).__name__}: {str(e)[:250]}"
        logger.exception("call_gemini failed")
    if not (LAST_GROQ_ERROR or LAST_GEMINI_ERROR or LAST_CALL_ERROR):
        LAST_CALL_ERROR = "no Groq/Gemini keys configured or all providers failed silently"
    LAST_AI_MS["ms"] = (time.perf_counter() - t0) * 1000
    return None


LAST_AI_MS: dict = {"ms": 0.0, "model": ""}

# Models that recently got Groq 429 (rate limit): skipped for 25s per (key, model)
_MODEL_COOLDOWN: dict[tuple[str, str], float] = {}

# Models that are permanently deprecated/removed (404) - never retry
_DEPRECATED_MODELS: set[str] = {"openai/gpt-oss-120b", "gpt-oss-120b"}

# Last provider error reason (for diagnostics when all models fail)
LAST_GROQ_ERROR: str = ""
LAST_GEMINI_ERROR: str = ""
LAST_CALL_ERROR: str = ""


# Fallback minimal system prompt when no system_prompt is passed
_MINIMAL_SYSTEM_PROMPT = (
    "أنت المساعد الذكي الرسمي لمنصة «نَافِذَة» الجامعية. أجب بالعربية فقط، بلا تفكير داخلي، وبلا Markdown. "
    "أجب حصرياً على الأسئلة المتعلقة بالجامعة والمواد والمنشورات المعتمدة في نافذة، واعتذر بلطف عن أي سؤال عام خارج نطاق الجامعة. "
    "لا ترسل روابط، ولا تدّعِ إرسال ملفات. كن مختصراً ودقيقاً."
)


def _compact_system_prompt(system_prompt: str, max_chars: int = 5500) -> str:
    """Ensure system_prompt fits within Groq per-request TPM limits (~6k-8k tokens)
    while preserving both the relevant context at the top and the strict rules at the bottom."""
    if not system_prompt or len(system_prompt) <= max_chars:
        return system_prompt
    head_len = int(max_chars * 0.68)
    tail_len = max_chars - head_len
    return (
        system_prompt[:head_len]
        + "\n... [مختصر] ...\n"
        + system_prompt[-tail_len:]
    )


async def _call_groq(
    prompt: str,
    system_prompt: str,
    api_key: str,
    max_tokens: int = 800,
    history: list[dict] | None = None,
) -> str | None:
    global LAST_GROQ_ERROR, LAST_GEMINI_ERROR, LAST_CALL_ERROR
    compact_sys = _compact_system_prompt(system_prompt, max_chars=5200)
    capped_max_tokens = min(max_tokens, 900)

    MODELS = [
        "openai/gpt-oss-20b",
        "qwen/qwen3.6-27b",
    ]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    key_id = api_key[:12]

    for model in MODELS:
        if model in _DEPRECATED_MODELS:
            continue
        # Skip models that hit rate limit recently (25s cooldown for this key)
        if time.monotonic() - _MODEL_COOLDOWN.get((key_id, model), 0.0) < 25.0:
            logger.info("Skipping %s for key %s (on 429 cooldown)", model, key_id[:8])
            continue

        cur_sys = compact_sys
        for attempt in range(2):
            messages = []
            if cur_sys:
                messages.append({"role": "system", "content": cur_sys})
            if history:
                for turn in history[-5:]:
                    u_msg = (turn.get("user") or "").strip()[:250]
                    a_msg = (turn.get("assistant") or "").strip()[:350]
                    if u_msg:
                        messages.append({"role": "user", "content": u_msg})
                    if a_msg:
                        messages.append({"role": "assistant", "content": a_msg})
            messages.append({"role": "user", "content": prompt})
            payload = {
                "model": model,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": capped_max_tokens,
            }
            try:
                await _wait_for_rate_limit(api_key)
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        json=payload,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=40),
                    ) as resp:
                        if resp.status == 429:
                            body = await resp.text()
                            LAST_GROQ_ERROR = f"429 rate limit: {body[:120]}"
                            # If 429 is due to request token size (TPM), shrink once and retry same model
                            if attempt == 0 and len(cur_sys) > 3000 and ("tokens" in body.lower() or "tpm" in body.lower() or "too large" in body.lower()):
                                logger.warning("Groq 429 TPM on %s — shrinking prompt to 2800 chars and retrying", model)
                                cur_sys = _compact_system_prompt(cur_sys, max_chars=2800)
                                continue
                            _MODEL_COOLDOWN[(key_id, model)] = time.monotonic()
                            logger.warning("Groq 429 for %s: %s — switching model now", model, body[:100])
                            break  # Switch to next model (e.g. qwen/qwen3.6-27b)
                        if resp.status != 200:
                            body = await resp.text()
                            if resp.status == 404:
                                _DEPRECATED_MODELS.add(model)
                                logger.warning("Groq model %s not found (404) — marked deprecated permanently", model)
                                break
                            if "decommissioned" in body or "deprecated" in body:
                                _DEPRECATED_MODELS.add(model)
                                logger.warning("Groq model %s deprecated, trying next", model)
                                break
                            if resp.status in (413, 400) and ("too large" in body.lower() or "context_length" in body.lower() or "tokens" in body.lower()):
                                if len(cur_sys) > 3000 and attempt == 0:
                                    logger.warning("Groq model %s payload too large, compacting system_prompt and retrying", model)
                                    cur_sys = _compact_system_prompt(cur_sys, max_chars=2800)
                                    continue
                                logger.warning("Groq model %s request too large — trying next model", model)
                                break
                            LAST_GROQ_ERROR = f"HTTP {resp.status}: {body[:150]}"
                            logger.warning("Groq %s error %s: %s", model, resp.status, body[:200])
                            break  # Try next model
                        data = await resp.json()
                        choices = data.get("choices", [])
                        if choices:
                            text = choices[0].get("message", {}).get("content", "")
                            if text:
                                text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
                                logger.info("Groq model %s used successfully (tokens: %s)", model,
                                             choices[0].get("usage", {}).get("total_tokens", "?"))
                                LAST_AI_MS["model"] = model
                                return text.strip()
            except asyncio.TimeoutError:
                logger.warning("Groq %s timeout (attempt %d/2)", model, attempt + 1)
                if attempt < 1:
                    await asyncio.sleep(1)
                    continue
            except Exception as e:
                LAST_GROQ_ERROR = f"{type(e).__name__}: {str(e)[:200]}"
                logger.exception("Groq %s failed: %s", model, e)
                break  # Non-retryable error, try next model
    LAST_GROQ_ERROR = LAST_GROQ_ERROR or "all Groq models failed"
    return None


async def _call_gemini(
    prompt: str,
    system_prompt: str,
    api_key: str,
    max_tokens: int = 1024,
    history: list[dict] | None = None,
) -> str | None:
    hist_block = ""
    if history:
        h_lines = []
        for turn in history[-6:]:
            if turn.get("user"):
                h_lines.append(f"المستخدم: {turn['user'][:300]}")
            if turn.get("assistant"):
                h_lines.append(f"المساعد: {turn['assistant'][:400]}")
        if h_lines:
            hist_block = "\n\nسياق المحادثة الجارية:\n" + "\n".join(h_lines)
    if system_prompt:
        full_prompt = f"{system_prompt}{hist_block}\n\nالرجاء الرد على رسالة المستخدم الحالية (مع ربطها بسياق المحادثة الجارية إن كانت تكملة لنفس الموضوع):\n{prompt}"
    else:
        full_prompt = f"{hist_block}\n\n{prompt}".strip()

    MODELS = ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash"]

    for model in MODELS:
        url = f"https://generativelanguage.googleapis.com/v1/models/{model}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.2},
        }
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
                            LAST_AI_MS["model"] = model
                            return text.strip()
        except Exception as e:
            logger.exception("Gemini %s failed: %s", model, e)
            continue
    return None


async def call_gemini_stream(
    prompt: str,
    on_chunk,
    system_prompt: str = "",
    max_tokens: int = 1024,
) -> str | None:
    """Streaming variant: `on_chunk(text_delta)` is called as data arrives.
    Falls back to non-streaming Groq, then Gemini keys."""
    t0 = time.perf_counter()
    buffer = []
    try:
        groq_keys = settings.groq_keys
        tried: set[str] = set()
        for _ in groq_keys:
            key = await _pick_best_key(groq_keys, tried)
            if not key:
                break
            tried.add(key)
            result = await _call_groq_stream(prompt, system_prompt, key, on_chunk, max_tokens)
            if result is not None:
                buffer.append(result)
                LAST_AI_MS["ms"] = (time.perf_counter() - t0) * 1000
                return "".join(buffer)

        # Fallback to Gemini keys (generative API also supports streaming)
        for key in settings.gemini_keys:
            result = await _call_gemini_stream(prompt, system_prompt, key, on_chunk, max_tokens)
            if result is not None:
                buffer.append(result)
                LAST_AI_MS["ms"] = (time.perf_counter() - t0) * 1000
                return "".join(buffer)
    except Exception:
        logger.exception("call_gemini_stream failed")
    LAST_AI_MS["ms"] = (time.perf_counter() - t0) * 1000
    return None


async def _call_groq_stream(prompt: str, system_prompt: str, api_key: str, on_chunk, max_tokens: int = 800) -> str | None:
    compact_sys = _compact_system_prompt(system_prompt, max_chars=5500)
    messages = []
    if compact_sys:
        messages.append({"role": "system", "content": compact_sys})
    messages.append({"role": "user", "content": prompt})

    MODELS = [
        "openai/gpt-oss-20b",
        "qwen/qwen3.6-27b",
    ]
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    key_id = api_key[:12]

    for model in MODELS:
        if model in _DEPRECATED_MODELS:
            continue
        if time.monotonic() - _MODEL_COOLDOWN.get((key_id, model), 0.0) < 25.0:
            logger.info("Skipping %s (on 429 cooldown)", model)
            continue
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": min(max_tokens, 900),
            "stream": True,
        }
        for attempt in range(2):
            try:
                await _wait_for_rate_limit(api_key)
                full = []
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        json=payload,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=60),
                    ) as resp:
                        if resp.status == 429:
                            body = await resp.text()
                            _MODEL_COOLDOWN[(key_id, model)] = time.monotonic()
                            logger.warning("Groq 429 stream %s: %s — switching model now", model, body[:100])
                            break  # No sleep-retry same model: go to next one
                        if resp.status != 200:
                            body = await resp.text()
                            if "decommissioned" in body or "deprecated" in body:
                                break
                            logger.warning("Groq stream %s error %s: %s", model, resp.status, body[:200])
                            break
                        async for line in resp.content:
                            line = line.decode("utf-8", errors="ignore").strip()
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                break
                            import json
                            try:
                                chunk = json.loads(data)
                            except Exception:
                                continue
                            choices = chunk.get("choices") or []
                            if not choices:
                                continue
                            delta = (choices[0].get("delta") or {}).get("content")
                            if delta:
                                full.append(delta)
                                try:
                                    await on_chunk(delta)
                                except Exception:
                                    pass
                text = "".join(full).strip()
                if text:
                    LAST_AI_MS["model"] = model
                    return text
                break
            except asyncio.TimeoutError:
                logger.warning("Groq stream %s timeout (attempt %d/3)", model, attempt + 1)
                if attempt < 2:
                    await asyncio.sleep(1)
                    continue
            except Exception as e:
                logger.exception("Groq stream %s failed: %s", model, e)
                break
    return None


async def _call_gemini_stream(prompt: str, system_prompt: str, api_key: str, on_chunk, max_tokens: int = 1024) -> str | None:
    if system_prompt:
        full_prompt = f"{system_prompt}\n\nالرجاء الرد على ما يلي:\n{prompt}"
    else:
        full_prompt = prompt

    MODELS = ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash"]

    for model in MODELS:
        url = f"https://generativelanguage.googleapis.com/v1/models/{model}:streamGenerateContent?alt=sse&key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        try:
            full = []
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, json=payload, timeout=aiohttp.ClientTimeout(total=30)
                ) as resp:
                    if resp.status == 429:
                        return None
                    if resp.status != 200:
                        continue
                    async for raw_line in resp.content:
                        line = raw_line.decode("utf-8", errors="ignore").strip()
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data:
                            continue
                        import json
                        try:
                            chunk = json.loads(data)
                        except Exception:
                            continue
                        parts = ((chunk.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
                        text = "".join(p.get("text", "") for p in parts)
                        if text:
                            full.append(text)
                            try:
                                await on_chunk(text)
                            except Exception:
                                pass
            text = "".join(full).strip()
            if text:
                LAST_AI_MS["model"] = model
                return text
        except Exception as e:
            logger.exception("Gemini stream %s failed: %s", model, e)
            continue
    return None


async def call_groq_vision(prompt: str, image_b64: str) -> str | None:
    """Analyze an image using Groq's vision models."""
    groq_keys = settings.groq_keys
    MODELS = [
        "qwen/qwen3.6-27b",
        "meta-llama/llama-4-scout-17b-16e-instruct",
    ]
    headers_tmpl = {"Content-Type": "application/json"}

    for api_key in groq_keys:
        for model in MODELS:
            for attempt in range(3):
                try:
                    await _wait_for_rate_limit(api_key)
                    headers = {**headers_tmpl, "Authorization": f"Bearer {api_key}"}
                    payload = {
                        "model": model,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": prompt},
                                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                                ],
                            }
                        ],
                        "max_tokens": 2048,
                    }
                    async with aiohttp.ClientSession() as session:
                        async with session.post(
                            "https://api.groq.com/openai/v1/chat/completions",
                            json=payload, headers=headers,
                            timeout=aiohttp.ClientTimeout(total=60),
                        ) as resp:
                            if resp.status == 429:
                                logger.warning("Groq vision 429 for %s key=%s (attempt %d/3)", model, api_key[:8], attempt + 1)
                                if attempt < 2:
                                    await asyncio.sleep(2 ** attempt)
                                    continue
                                break
                            if resp.status != 200:
                                body = await resp.text()
                                logger.warning("Groq vision %s key=%s error %s: %s", model, api_key[:8], resp.status, body[:300])
                                continue  # Try next model on same key
                            data = await resp.json()
                            choices = data.get("choices", [])
                            if choices:
                                text = choices[0].get("message", {}).get("content", "")
                                if text:
                                    # Strip reasoning/thinking tags
                                    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
                                    logger.info("Groq vision %s success (key=%s)", model, api_key[:8])
                                    return text.strip()
                except asyncio.TimeoutError:
                    logger.warning("Groq vision %s timeout (attempt %d/3)", model, attempt + 1)
                    if attempt < 2:
                        await asyncio.sleep(1)
                        continue
                except Exception as e:
                    logger.warning("Groq vision %s failed: %s", model, e)
                    continue  # Try next model
    logger.error("Groq vision ALL models/keys exhausted")
    return None
