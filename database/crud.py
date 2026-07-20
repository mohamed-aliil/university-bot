from pathlib import Path
from sqlalchemy import select, delete, func, text
from .database import async_session
from .models import User, Message, Attachment, AutoReply, ReplyLog, Folder, ContentItem, ContentLink, MonitoredChannel, MutedUser, SentNews, AdminNotification, QAPair, PDFContext, _utcnow

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


async def mute_user_notifications(user_id: int, muted: bool = True) -> bool:
    async with async_session() as session:
        if muted:
            exists = await session.execute(select(MutedUser).where(MutedUser.user_id == user_id))
            if not exists.scalar_one_or_none():
                session.add(MutedUser(user_id=user_id))
                await session.commit()
            return True
        else:
            result = await session.execute(delete(MutedUser).where(MutedUser.user_id == user_id))
            await session.commit()
            return result.rowcount > 0


async def is_notifications_muted(user_id: int) -> bool:
    async with async_session() as session:
        result = await session.execute(select(MutedUser).where(MutedUser.user_id == user_id))
        return result.scalar_one_or_none() is not None


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


async def save_or_replace_user_message(
    user_id: int,
    content: str,
    message_type: str = "materials_action",
) -> Message:
    async with async_session() as session:
        existing = (
            await session.execute(
                select(Message).where(Message.user_id == user_id, Message.message_type == "materials_action").order_by(Message.created_at.desc()).limit(1)
            )
        ).scalar_one_or_none()
        if existing:
            existing.content = content
            existing.caption = None
            existing.file_id = None
            existing.file_unique_id = None
            existing.message_type = message_type
            existing.created_at = _utcnow()
            await session.commit()
            await session.refresh(existing)
            return existing
        msg = Message(
            user_id=user_id,
            message_type=message_type,
            content=content,
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
        msgs_count = (await session.execute(select(func.count(Message.id)).where(Message.message_type != "materials_action"))).scalar()
        unread_count = (await session.execute(select(func.count(Message.id)).where(Message.is_read == False, Message.message_type != "materials_action"))).scalar()
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
            select(Message).where(Message.is_read == False, Message.message_type != "materials_action").order_by(Message.created_at.asc())
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
        from sqlalchemy import update
        await session.execute(
            update(Message)
            .where(Message.user_id == user_id, Message.is_read == False)
            .values(is_read=True)
        )
        await session.commit()


async def get_user_messages(user_id: int) -> list[Message]:
    async with async_session() as session:
        result = await session.execute(
            select(Message).where(Message.user_id == user_id, Message.message_type != "materials_action").order_by(Message.created_at.desc())
        )
        return list(result.scalars().all())


async def get_all_user_messages(limit: int = 20) -> list[Message]:
    async with async_session() as session:
        result = await session.execute(
            select(Message).where(Message.message_type == "materials_action").order_by(Message.created_at.desc()).limit(limit)
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


# ─── Materials System (recursive tree) ───

async def add_folder(name: str, parent_id: int = None) -> Folder:
    async with async_session() as session:
        f = Folder(name=name, parent_id=parent_id)
        session.add(f)
        await session.commit()
        await session.refresh(f)
        return f


async def remove_folder(folder_id: int) -> bool:
    async with async_session() as session:
        obj = await session.get(Folder, folder_id)
        if not obj:
            return False
        await session.delete(obj)
        await session.commit()
        return True


async def get_folders(parent_id: int = None) -> list[Folder]:
    async with async_session() as session:
        if parent_id is None:
            result = await session.execute(select(Folder).where(Folder.parent_id.is_(None)).order_by(Folder.name))
        else:
            result = await session.execute(select(Folder).where(Folder.parent_id == parent_id).order_by(Folder.name))
        return list(result.scalars().all())


async def get_folder(folder_id: int) -> Folder | None:
    async with async_session() as session:
        return await session.get(Folder, folder_id)


async def rename_folder(folder_id: int, new_name: str) -> bool:
    async with async_session() as session:
        f = await session.get(Folder, folder_id)
        if not f:
            return False
        f.name = new_name
        await session.commit()
        return True


async def add_content_item(folder_id: int, title: str = None) -> ContentItem:
    async with async_session() as session:
        ci = ContentItem(folder_id=folder_id, title=title)
        session.add(ci)
        await session.commit()
        await session.refresh(ci)
        return ci


async def remove_content_item(item_id: int) -> bool:
    async with async_session() as session:
        obj = await session.get(ContentItem, item_id)
        if not obj:
            return False
        await session.delete(obj)
        await session.commit()
        return True


async def get_content_items(folder_id: int) -> list[ContentItem]:
    async with async_session() as session:
        result = await session.execute(
            select(ContentItem).where(ContentItem.folder_id == folder_id).order_by(ContentItem.id)
        )
        return list(result.scalars().all())


async def get_content_item(item_id: int) -> ContentItem | None:
    async with async_session() as session:
        return await session.get(ContentItem, item_id)


async def add_content_link(content_item_id: int, link: str, channel_username: str = None, channel_message_id: int = None) -> ContentLink:
    async with async_session() as session:
        cl = ContentLink(content_item_id=content_item_id, link=link, channel_username=channel_username, channel_message_id=channel_message_id)
        session.add(cl)
        await session.commit()
        await session.refresh(cl)
        return cl


async def get_content_links(content_item_id: int) -> list[ContentLink]:
    async with async_session() as session:
        result = await session.execute(
            select(ContentLink).where(ContentLink.content_item_id == content_item_id).order_by(ContentLink.created_at)
        )
        return list(result.scalars().all())


async def remove_content_link(link_id: int) -> bool:
    async with async_session() as session:
        obj = await session.get(ContentLink, link_id)
        if not obj:
            return False
        await session.delete(obj)
        await session.commit()
        return True


async def update_content_item_title(item_id: int, title: str) -> bool:
    async with async_session() as session:
        obj = await session.get(ContentItem, item_id)
        if not obj:
            return False
        obj.title = title
        await session.commit()
        return True


MATERIALS_ACTIVE_FILE = Path(__file__).parent.parent / "data" / ".materials_active"


def is_materials_active() -> bool:
    return MATERIALS_ACTIVE_FILE.exists()


def set_materials_active(active: bool) -> None:
    if active:
        MATERIALS_ACTIVE_FILE.touch()
    else:
        MATERIALS_ACTIVE_FILE.unlink(missing_ok=True)


# ─── Monitored Channels ───

async def add_monitored_channel(channel_id: str, channel_username: str = None, title: str = None, monitor_mode: str = "manual", target_folder_id: int = None) -> MonitoredChannel:
    async with async_session() as session:
        mc = MonitoredChannel(
            channel_id=channel_id,
            channel_username=channel_username,
            title=title,
            monitor_mode=monitor_mode,
            target_folder_id=target_folder_id,
        )
        session.add(mc)
        await session.commit()
        await session.refresh(mc)
        return mc


async def get_all_monitored_channels() -> list[MonitoredChannel]:
    async with async_session() as session:
        result = await session.execute(select(MonitoredChannel).order_by(MonitoredChannel.created_at.desc()))
        return list(result.scalars().all())


async def remove_monitored_channel(channel_id: str) -> bool:
    async with async_session() as session:
        result = await session.execute(select(MonitoredChannel).where(MonitoredChannel.channel_id == channel_id))
        mc = result.scalar_one_or_none()
        if mc:
            await session.delete(mc)
            await session.commit()
            return True
        return False


async def get_auto_monitored_channels() -> list[MonitoredChannel]:
    async with async_session() as session:
        result = await session.execute(
            select(MonitoredChannel).where(MonitoredChannel.monitor_mode == "auto").order_by(MonitoredChannel.created_at.desc())
        )
        return list(result.scalars().all())


async def get_monitored_channel_by_username(username: str) -> MonitoredChannel | None:
    async with async_session() as session:
        result = await session.execute(
            select(MonitoredChannel).where(MonitoredChannel.channel_username == username)
        )
        return result.scalar_one_or_none()


async def get_monitored_channel_by_channel_id(channel_id: str) -> MonitoredChannel | None:
    async with async_session() as session:
        result = await session.execute(
            select(MonitoredChannel).where(MonitoredChannel.channel_id == channel_id)
        )
        return result.scalar_one_or_none()


async def save_sent_news(channel_message_id: int, template: str = None, content: str = None) -> SentNews:
    async with async_session() as session:
        sn = SentNews(channel_message_id=channel_message_id, template=template, content=content)
        session.add(sn)
        await session.commit()
        await session.refresh(sn)
        return sn


async def get_recent_sent_news(limit: int = 10) -> list[SentNews]:
    async with async_session() as session:
        result = await session.execute(
            select(SentNews).order_by(SentNews.sent_at.desc()).limit(limit)
        )
        return list(result.scalars().all())


async def delete_sent_news(news_id: int) -> bool:
    async with async_session() as session:
        obj = await session.get(SentNews, news_id)
        if not obj:
            return False
        await session.delete(obj)
        await session.commit()
        return True


async def save_admin_notification(db_message_id: int, admin_id: int, chat_id: int, notification_message_id: int) -> AdminNotification:
    async with async_session() as session:
        an = AdminNotification(db_message_id=db_message_id, admin_id=admin_id, chat_id=chat_id, notification_message_id=notification_message_id)
        session.add(an)
        await session.commit()
        await session.refresh(an)
        return an


async def get_admin_notifications(db_message_id: int) -> list[AdminNotification]:
    async with async_session() as session:
        result = await session.execute(
            select(AdminNotification).where(AdminNotification.db_message_id == db_message_id)
        )
        return list(result.scalars().all())


async def delete_admin_notifications(db_message_id: int) -> None:
    async with async_session() as session:
        await session.execute(
            delete(AdminNotification).where(AdminNotification.db_message_id == db_message_id)
        )
        await session.commit()


async def cleanup_old_data(days: int = 60) -> dict:
    """حذف الرسائل والسجلات الأقدم من 60 يوم."""
    from datetime import datetime, timedelta
    from database.models import LIBYA_TZ
    cutoff = datetime.now(LIBYA_TZ).replace(tzinfo=None) - timedelta(days=days)
    counts = {}
    async with async_session() as session:
        for model, name in [(Message, "messages"), (ReplyLog, "reply_logs")]:
            result = await session.execute(
                select(func.count(model.id)).where(model.created_at < cutoff)
            )
            counts[name] = result.scalar() or 0
            await session.execute(
                delete(model).where(model.created_at < cutoff)
            )
        await session.commit()
    return counts


async def get_db_table_stats() -> dict:
    """إحصائيات حجم الجداول الأساسية."""
    stats = {"rows": {}, "sizes": {}}
    async with async_session() as session:
        result = await session.execute(text("SELECT pg_database_size(current_database())"))
        stats["db_total_bytes"] = result.scalar() or 0

        for model, name, table in [
            (Message, "messages", "messages"),
            (ReplyLog, "reply_logs", "reply_logs"),
            (Attachment, "attachments", "attachments"),
            (User, "users", "users"),
            (AdminNotification, "admin_notifications", "admin_notifications"),
        ]:
            result = await session.execute(select(func.count(model.id)))
            stats["rows"][name] = result.scalar() or 0

            result = await session.execute(text(f"SELECT pg_total_relation_size('{table}')"))
            stats["sizes"][name] = result.scalar() or 0

    return stats


def _fmt_size(bytes_val: int) -> str:
    """تحويل البايت إلى وحدة مناسبة."""
    if bytes_val >= 1073741824:
        return f"{bytes_val / 1073741824:.1f} GB"
    elif bytes_val >= 1048576:
        return f"{bytes_val / 1048576:.1f} MB"
    elif bytes_val >= 1024:
        return f"{bytes_val / 1024:.1f} KB"
    return f"{bytes_val} B"


async def add_qa(question: str, answer: str) -> QAPair:
    async with async_session() as session:
        qa = QAPair(question=question, answer=answer)
        session.add(qa)
        await session.commit()
        await session.refresh(qa)
        return qa


async def delete_qa(qa_id: int) -> bool:
    async with async_session() as session:
        result = await session.execute(select(QAPair).where(QAPair.id == qa_id))
        qa = result.scalar_one_or_none()
        if qa:
            await session.delete(qa)
            await session.commit()
            return True
        return False


async def get_all_qa() -> list[QAPair]:
    async with async_session() as session:
        result = await session.execute(select(QAPair).order_by(QAPair.created_at.desc()))
        return list(result.scalars().all())


async def save_pdf_context(name: str, file_path: str) -> PDFContext:
    async with async_session() as session:
        pdf = PDFContext(name=name, file_path=file_path)
        session.add(pdf)
        await session.commit()
        await session.refresh(pdf)
        return pdf


async def delete_pdf_context(pdf_id: int) -> bool:
    async with async_session() as session:
        result = await session.execute(select(PDFContext).where(PDFContext.id == pdf_id))
        pdf = result.scalar_one_or_none()
        if pdf:
            await session.delete(pdf)
            await session.commit()
            return True
        return False


async def get_all_pdfs() -> list[PDFContext]:
    async with async_session() as session:
        result = await session.execute(select(PDFContext).order_by(PDFContext.created_at.desc()))
        return list(result.scalars().all())
