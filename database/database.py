from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from config import settings
import os

os.makedirs("data", exist_ok=True)

_url = settings.DATABASE_URL
if _url.startswith("postgresql://") and "+asyncpg" not in _url:
    _url = _url.replace("postgresql://", "postgresql+asyncpg://", 1)
engine = create_async_engine(_url, echo=False, pool_pre_ping=True)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    async with engine.begin() as conn:
        from .models import User, Message, Attachment, NewsTemplate, Folder, ContentItem, ContentLink
        await conn.run_sync(Base.metadata.create_all)
        # Add agreed_ai column if missing (for existing databases)
        try:
            await conn.execute(text("ALTER TABLE users ADD COLUMN agreed_ai BOOLEAN DEFAULT 0"))
        except Exception:
            pass  # Column already exists
