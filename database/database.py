from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from config import settings
import os

os.makedirs("data", exist_ok=True)

_url = settings.DATABASE_URL
if _url.startswith("postgresql://") and "+asyncpg" not in _url:
    _url = _url.replace("postgresql://", "postgresql+asyncpg://", 1)

_connect_args = {}
if _url.startswith("postgresql+asyncpg"):
    import re as _re
    _m = _re.search(r"(?:\?|&)sslmode=([a-z]+)", _url)
    if _m:
        _connect_args["ssl"] = _m.group(1)
        _url = _re.sub(r"[?&]sslmode=[a-z]+", "", _url)

    if "pooler.supabase.com" in _url:
        _connect_args["statement_cache_size"] = 0

engine = create_async_engine(_url, echo=False, pool_pre_ping=False, connect_args=_connect_args)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    async with engine.begin() as conn:
        from .models import User, Message, Attachment, NewsTemplate, Folder, ContentItem, ContentLink, UserPreference, BotSetting, RequiredChannel, AILog, ErrorLog
        await conn.run_sync(Base.metadata.create_all)
        # Lightweight migrations for existing tables (new content-item fields)
        from sqlalchemy import text as _sql
        if _url.startswith("postgresql+asyncpg"):
            for col, ctype in (
                ("content_type", "VARCHAR(20) DEFAULT 'post'"),
                ("text_body", "TEXT"),
                ("file_id", "VARCHAR(512)"),
                ("file_kind", "VARCHAR(50)"),
            ):
                await conn.execute(_sql(f"ALTER TABLE content_items ADD COLUMN IF NOT EXISTS {col} {ctype}"))
