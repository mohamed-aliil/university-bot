import asyncio
import time
from functools import wraps

# Tiny TTL cache for hot DB reads executed on every user message.
# Avoiding 3-5 Supabase round-trips per message makes normal users as fast
# as admins (who skip these checks).

_registry: dict[str, tuple] = {}
_lock = asyncio.Lock()


def ttl_cache(name: str, ttl: float = 10.0, max_size: int = 2048):
    """Decorator: cache an async function result for `ttl` seconds by args."""
    def deco(fn):
        key_prefix = name

        @wraps(fn)
        async def wrapper(*args, **kwargs):
            key = (key_prefix, args, frozenset(kwargs.items()))
            now = time.monotonic()
            entry = _registry.get(key)
            if entry and now - entry[0] < ttl:
                return entry[1]
            result = await fn(*args, **kwargs)
            _registry[key] = (now, result)
            if len(_registry) > max_size:
                # crude eviction: drop oldest third
                sorted_items = sorted(_registry.items(), key=lambda kv: kv[1][0])
                for k, _ in sorted_items[: max_size // 3]:
                    _registry.pop(k, None)
            return result
        return wrapper
    return deco


def invalidate_cache(name: str | None = None):
    """Drop all cached entries, or only those for the given cache name."""
    global _registry
    if name is None:
        _registry = {}
        return
    drop = [k for k in _registry if k[0] == name]
    for k in drop:
        _registry.pop(k, None)


def peek_cache(name: str):
    """Return the currently-cached value for the first entry named `name`
    (any args), or None when not cached. For in-place patching."""
    for k, entry in _registry.items():
        if k[0] == name:
            return entry[1]
    return None


def patch_cache(name: str, value) -> None:
    """Replace the cached value for all entries named `name`."""
    for k in list(_registry.keys()):
        if k[0] == name:
            _registry[k] = (time.monotonic(), value)