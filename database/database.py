from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
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
        from .models import User, Message, Attachment, NewsTemplate, Folder, ContentItem, ContentLink, UserPreference, BotSetting
        await conn.run_sync(Base.metadata.create_all)
