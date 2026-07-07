from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from config import settings
import os

os.makedirs("data", exist_ok=True)

engine = create_async_engine(settings.DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    async with engine.begin() as conn:
        from .models import User, Message, Attachment, NewsTemplate, Subject, Section, ContentType, StudyMaterial
        await conn.run_sync(Base.metadata.create_all)
