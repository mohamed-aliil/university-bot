from pathlib import Path
from sqlalchemy import select, delete, func
from .database import async_session
from .models import User, Message, Attachment, AutoReply, ReplyLog

BOT_ACTIVE_FILE = Path(__file__).parent.parent / "data" / ".bot_active"


def is_bot_active() -> bool:
    return BOT_ACTIVE_FILE.exists()


def set_bot_active(active: bool) -> None:
    BOT_ACTIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if active:
        BOT_ACTIVE_FILE.touch()
    else:
        BOT_ACTIVE_FILE.unlink(missing_ok=True)

async def get_user(user_id: int) -> User | None:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        return result.scalar_one_or_none()


async def create_user(user_id: int, full_name: str, username: str | None = None) -> User:
    async with async_session() as session:
        user = User(user_id=user_id, full_name=full_name, username=username)
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def update_user(user_id: int, **kwargs) -> User | None:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one_or_none()
        if user:
            for key, value in kwargs.items():
                setattr(user, key, value)
            await session.commit()
            await session.refresh(user)
        return user


async def get_or_create_user(user_id: int, full_name: str, username: str | None = None) -> User:
    user = await get_user(user_id)
    if user:
        if user.full_name != full_name or user.username != username:
            await update_user(user_id, full_name=full_name, username=username)
        return user
    return await create_user(user_id, full_name, username)


async def is_banned(user_id: int) -> bool:
    user = await get_user(user_id)
    return user.is_banned if user else False


async def ban_user(user_id: int) -> bool:
    user = await update_user(user_id, is_banned=True)
    return user is not None


async def unban_user(user_id: int) -> bool:
    user = await update_user(user_id, is_banned=False)
    return user is not None


async def unban_all_users() -> int:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.is_banned == True))
        banned_users = list(result.scalars().all())
        count = len(banned_users)
        for user in banned_users:
            user.is_banned = False
        await session.commit()
        return count


async def get_all_users() -> list[User]:
    async with async_session() as session:
        result = await session.execute(select(User))
        return list(result.scalars().all())


async def get_all_admins() -> list[User]:
    async with async_session() as session:
        result = await session.execute(select(User).where(User.is_admin == True))
        return list(result.scalars().all())


async def save_message(
    user_id: int,
    message_type: str,
    content: str | None = None,
    file_id: str | None = None,
    file_unique_id: str | None = None,
    caption: str | None = None,
) -> Message:
    async with async_session() as session:
        msg = Message(
            user_id=user_id,
            message_type=message_type,
            content=content,
            file_id=file_id,
            file_unique_id=file_unique_id,
            caption=caption,
        )
        session.add(msg)
        await session.commit()
        await session.refresh(msg)
        return msg


async def save_attachment(
    message_id: int,
    file_type: str,
    file_id: str,
    file_unique_id: str | None = None,
    caption: str | None = None,
) -> Attachment:
    async with async_session() as session:
        att = Attachment(
            message_id=message_id,
            file_type=file_type,
            file_id=file_id,
            file_unique_id=file_unique_id,
            caption=caption,
        )
        session.add(att)
        await session.commit()
        await session.refresh(att)
        return att


RANK_PERMISSIONS = {
    "super_admin": {"can_reply": True, "can_ban": True, "can_manage": True, "can_view_logs": True, "can_control_bot": True},
    "admin": {"can_reply": True, "can_ban": True, "can_manage": True, "can_view_logs": True, "can_control_bot": False},
    "moderator": {"can_reply": True, "can_ban": False, "can_manage": True, "can_view_logs": False, "can_control_bot": False},
}


def get_rank_permissions(rank: str) -> dict:
    return RANK_PERMISSIONS.get(rank, {"can_reply": False, "can_ban": False, "can_manage": False, "can_view_logs": False, "can_control_bot": False})


async def set_admin(user_id: int, is_admin: bool = True, rank: str = "moderator") -> bool:
    kwargs = {"is_admin": is_admin}
    if is_admin:
        user = await get_user(user_id)
        if user is None:
            return False
        kwargs["rank"] = rank
        perms = get_rank_permissions(rank)
        kwargs.update(perms)
    else:
        kwargs["rank"] = "user"
        kwargs["can_reply"] = False
        kwargs["can_ban"] = False
        kwargs["can_manage"] = False
    user = await update_user(user_id, **kwargs)
    return user is not None


async def set_permission(user_id: int, perm: str, value: bool) -> bool:
    user = await update_user(user_id, **{perm: value})
    return user is not None


async def get_admin_permissions(user_id: int) -> dict | None:
    user = await get_user(user_id)
    if not user:
        return None
    return {
        "can_reply": user.can_reply,
        "can_ban": user.can_ban,
        "can_manage": user.can_manage,
        "can_view_logs": user.can_view_logs,
        "can_control_bot": user.can_control_bot,
        "rank": user.rank or "admin",
    }


async def is_admin_user(user_id: int) -> bool:
    user = await get_user(user_id)
    return user.is_admin if user else False


async def add_autoreply(trigger: str, response: str) -> AutoReply:
    async with async_session() as session:
        ar = AutoReply(trigger=trigger, response=response)
        session.add(ar)
        await session.commit()
        await session.refresh(ar)
        return ar


async def remove_autoreply(reply_id: int) -> bool:
    async with async_session() as session:
        result = await session.execute(select(AutoReply).where(AutoReply.id == reply_id))
        ar = result.scalar_one_or_none()
        if ar:
            await session.delete(ar)
            await session.commit()
            return True
        return False


async def get_all_autoreplies() -> list[AutoReply]:
    async with async_session() as session:
        result = await session.execute(select(AutoReply))
        return list(result.scalars().all())


async def get_stats() -> dict:
    async with async_session() as session:
        users_count = (await session.execute(select(func.count(User.id)))).scalar()
        banned_count = (await session.execute(select(func.count(User.id)).where(User.is_banned == True))).scalar()
        msgs_count = (await session.execute(select(func.count(Message.id)))).scalar()
        unread_count = (await session.execute(select(func.count(Message.id)).where(Message.is_read == False))).scalar()
        admins_count = (await session.execute(select(func.count(User.id)).where(User.is_admin == True))).scalar()
        replies_count = (await session.execute(select(func.count(AutoReply.id)))).scalar()
        return {
            "users": users_count or 0,
            "banned": banned_count or 0,
            "messages": msgs_count or 0,
            "unread": unread_count or 0,
            "admins": admins_count or 0,
            "replies": replies_count or 0,
        }


async def get_unread_messages() -> list[Message]:
    async with async_session() as session:
        result = await session.execute(
            select(Message).where(Message.is_read == False).order_by(Message.created_at.asc())
        )
        return list(result.scalars().all())


async def mark_message_read(message_id: int) -> None:
    async with async_session() as session:
        result = await session.execute(select(Message).where(Message.id == message_id))
        msg = result.scalar_one_or_none()
        if msg:
            msg.is_read = True
            await session.commit()


async def mark_user_messages_read(user_id: int) -> None:
    async with async_session() as session:
        result = await session.execute(
            select(Message).where(Message.user_id == user_id, Message.is_read == False)
        )
        msgs = list(result.scalars().all())
        for msg in msgs:
            msg.is_read = True
        await session.commit()


async def get_user_messages(user_id: int) -> list[Message]:
    async with async_session() as session:
        result = await session.execute(
            select(Message).where(Message.user_id == user_id).order_by(Message.created_at.desc())
        )
        return list(result.scalars().all())


async def save_reply_log(
    user_id: int,
    user_name: str,
    admin_id: int,
    admin_name: str,
    user_message_id: int,
    user_message: str | None,
    user_message_type: str,
    admin_reply: str,
    action_type: str = "reply",
    details: str | None = None,
) -> ReplyLog:
    async with async_session() as session:
        log = ReplyLog(
            user_id=user_id,
            user_name=user_name,
            admin_id=admin_id,
            admin_name=admin_name,
            user_message_id=user_message_id,
            user_message=user_message,
            user_message_type=user_message_type,
            admin_reply=admin_reply,
            action_type=action_type,
            details=details,
        )
        session.add(log)
        await session.commit()
        await session.refresh(log)
        return log


async def save_admin_action(
    admin_id: int,
    admin_name: str,
    action_type: str,
    details: str | None = None,
    target_id: int | None = None,
    target_name: str | None = None,
) -> ReplyLog:
    async with async_session() as session:
        log = ReplyLog(
            user_id=target_id,
            user_name=target_name,
            admin_id=admin_id,
            admin_name=admin_name,
            action_type=action_type,
            details=details,
            admin_reply=details,
        )
        session.add(log)
        await session.commit()
        await session.refresh(log)
        return log


async def get_reply_logs(admin_id: int | None = None, limit: int = 30) -> list[ReplyLog]:
    async with async_session() as session:
        query = select(ReplyLog).order_by(ReplyLog.replied_at.desc())
        if admin_id:
            query = query.where(ReplyLog.admin_id == admin_id)
        result = await session.execute(query.limit(limit))
        return list(result.scalars().all())


async def reset_all_data() -> dict:
    from config import settings
    async with async_session() as session:
        counts = {}
        result = await session.execute(select(func.count(Message.id)))
        counts["messages"] = result.scalar() or 0
        await session.execute(delete(Message))

        result = await session.execute(select(func.count(Attachment.id)))
        counts["attachments"] = result.scalar() or 0
        await session.execute(delete(Attachment))

        result = await session.execute(select(func.count(AutoReply.id)))
        counts["replies"] = result.scalar() or 0
        await session.execute(delete(AutoReply))

        result = await session.execute(select(func.count(ReplyLog.id)))
        counts["logs"] = result.scalar() or 0
        await session.execute(delete(ReplyLog))

        result = await session.execute(select(func.count(User.id)))
        total_users = result.scalar() or 0
        await session.execute(
            delete(User).where(User.user_id.notin_(settings.admin_ids)),
        )
        kept = len([aid for aid in settings.admin_ids])
        counts["users_deleted"] = total_users - kept
        counts["users_kept"] = kept

        await session.commit()
        return counts
