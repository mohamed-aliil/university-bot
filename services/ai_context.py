import asyncio
import time

# Shared in-memory cache for the AI static context (QA, materials tree,
# articles, prerequisites, aliases). Rebuilt at most every CONTEXT_TTL seconds
# instead of on every user question (which caused 60+ sequential DB queries per
# question and made the bot "hang then burst"). Any CRUD mutation calls
# clear_ai_context() so the next question is accurate.
_CONTEXT_TTL = 300  # seconds

_context_lock = asyncio.Lock()
_context_cache: dict = {}
_context_ts: float = 0.0


def clear_ai_context() -> None:
    """Force the static AI context to be rebuilt on the next question."""
    global _context_ts
    _context_ts = 0.0


async def get_cached_context(builder) -> dict:
    """Return cached context, calling builder() at most once per TTL window."""
    import time
    global _context_ts
    now = time.monotonic()
    if _context_ts and now - _context_ts < _CONTEXT_TTL:
        return _context_cache
    async with _context_lock:
        now = time.monotonic()
        if _context_ts and now - _context_ts < _CONTEXT_TTL:
            return _context_cache
        data = await builder()
        _context_cache.update(data)
        _context_ts = now
        return _context_cache