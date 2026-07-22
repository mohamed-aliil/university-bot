from sqlalchemy import Column, Integer, String, BigInteger, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone, timedelta
from .database import Base

LIBYA_TZ = timezone(timedelta(hours=2))

def _utcnow():
    return datetime.now(LIBYA_TZ).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=False)
    username = Column(String(255), nullable=True)
    is_admin = Column(Boolean, default=False)
    is_banned = Column(Boolean, default=False)
    rank = Column(String(50), default="user")
    can_reply = Column(Boolean, default=True)
    can_ban = Column(Boolean, default=False)
    can_manage = Column(Boolean, default=False)
    can_view_logs = Column(Boolean, default=False)
    can_control_bot = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_utcnow)

    messages = relationship("Message", back_populates="user", cascade="all, delete-orphan")


class MutedUser(Base):
    __tablename__ = "muted_users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=_utcnow)


class UserPreference(Base):
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, unique=True, nullable=False, index=True)
    agreed_ai = Column(Boolean, default=False)
    channel_verified = Column(Boolean, default=False)
    channel_verified_at = Column(DateTime, nullable=True)


class BotSetting(Base):
    __tablename__ = "bot_settings"

    key = Column(String(255), primary_key=True)
    value = Column(Text, default="")


class RequiredChannel(Base):
    __tablename__ = "required_channels"

    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_id = Column(String, nullable=False)
    invite_link = Column(String, nullable=False)
    custom_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.user_id"), nullable=False, index=True)
    message_type = Column(String(50), nullable=False)
    content = Column(Text, nullable=True)
    file_id = Column(String(512), nullable=True)
    file_unique_id = Column(String(255), nullable=True)
    caption = Column(Text, nullable=True)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_utcnow)

    user = relationship("User", back_populates="messages")
    attachments = relationship("Attachment", back_populates="message", cascade="all, delete-orphan")


class Attachment(Base):
    __tablename__ = "attachments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False, index=True)
    file_type = Column(String(50), nullable=False)
    file_id = Column(String(512), nullable=False)
    file_unique_id = Column(String(255), nullable=True)
    caption = Column(Text, nullable=True)

    message = relationship("Message", back_populates="attachments")


class AutoReply(Base):
    __tablename__ = "autoreplies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trigger = Column(String(255), nullable=False)
    response = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class NewsTemplate(Base):
    __tablename__ = "news_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), unique=True, nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class SentNews(Base):
    __tablename__ = "sent_news"

    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_message_id = Column(BigInteger, nullable=False)
    template = Column(String(255), nullable=True)
    content = Column(Text, nullable=True)
    sent_at = Column(DateTime, default=_utcnow)


class ReplyLog(Base):
    __tablename__ = "reply_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=True, index=True)
    user_name = Column(String(255), nullable=True)
    admin_id = Column(BigInteger, nullable=False, index=True)
    admin_name = Column(String(255), nullable=True)
    action_type = Column(String(50), default="reply")
    details = Column(Text, nullable=True)
    user_message_id = Column(Integer, nullable=True)
    user_message = Column(Text, nullable=True)
    user_message_type = Column(String(50), default="text")
    admin_reply = Column(Text, nullable=True)
    replied_at = Column(DateTime, default=_utcnow)


class Folder(Base):
    __tablename__ = "folders"
    id = Column(Integer, primary_key=True)
    parent_id = Column(Integer, ForeignKey("folders.id", ondelete="CASCADE"), nullable=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class ContentItem(Base):
    __tablename__ = "content_items"
    id = Column(Integer, primary_key=True)
    folder_id = Column(Integer, ForeignKey("folders.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class ContentLink(Base):
    __tablename__ = "content_links"
    id = Column(Integer, primary_key=True)
    content_item_id = Column(Integer, ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False)
    link = Column(String, nullable=False)
    channel_username = Column(String, nullable=True)
    channel_message_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class MonitoredChannel(Base):
    __tablename__ = "monitored_channels"
    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(String, nullable=False)
    channel_username = Column(String, nullable=True)
    title = Column(String, nullable=True)
    monitor_mode = Column(String, default="manual")  # "manual" or "auto"
    target_folder_id = Column(Integer, ForeignKey("folders.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class AdminNotification(Base):
    __tablename__ = "admin_notifications"

    id = Column(Integer, primary_key=True, autoincrement=True)
    db_message_id = Column(BigInteger, nullable=False, index=True)
    admin_id = Column(BigInteger, nullable=False)
    chat_id = Column(BigInteger, nullable=False)
    notification_message_id = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class QAPair(Base):
    __tablename__ = "qa_pairs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class PDFContext(Base):
    __tablename__ = "pdf_contexts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    file_path = Column(String(512), nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class Article(Base):
    __tablename__ = "articles"
    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class CoursePrerequisite(Base):
    __tablename__ = "course_prerequisites"
    id = Column(Integer, primary_key=True, autoincrement=True)
    course_code = Column(String(50), nullable=False, index=True)
    course_name = Column(String(255), nullable=False)
    prerequisite_code = Column(String(50), nullable=False)
    prerequisite_name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class CourseAlias(Base):
    __tablename__ = "course_aliases"
    id = Column(Integer, primary_key=True, autoincrement=True)
    alias = Column(String(255), nullable=False, index=True, unique=True)
    course_code = Column(String(50), nullable=False)
    course_name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=_utcnow)


class AILog(Base):
    __tablename__ = "ai_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, nullable=False, index=True)
    user_name = Column(String(255), nullable=False)
    action = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=_utcnow)
