from sqlalchemy import select, delete
from database.database import async_session
from database.models import NewsTemplate

DEFAULT_TEMPLATES = ["نقلاً من", "خاص", "عاجل", "مصدر موثوق"]


async def load_templates() -> list[str]:
    async with async_session() as session:
        result = await session.execute(select(NewsTemplate).order_by(NewsTemplate.id))
        rows = list(result.scalars().all())
        if not rows:
            for name in DEFAULT_TEMPLATES:
                session.add(NewsTemplate(name=name))
            await session.commit()
            return list(DEFAULT_TEMPLATES)
        return [r.name for r in rows]


async def add_template(name: str) -> bool:
    async with async_session() as session:
        existing = await session.execute(select(NewsTemplate).where(NewsTemplate.name == name))
        if existing.scalar_one_or_none():
            return False
        session.add(NewsTemplate(name=name))
        await session.commit()
        return True


async def remove_template(name: str) -> bool:
    async with async_session() as session:
        result = await session.execute(select(NewsTemplate).where(NewsTemplate.name == name))
        t = result.scalar_one_or_none()
        if not t:
            return False
        await session.delete(t)
        await session.commit()
        return True
