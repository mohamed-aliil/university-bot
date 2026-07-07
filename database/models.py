from sqlalchemy import Column, Integer, String, BigInteger, Boolean, Text, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from .database import Base


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
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    messages = relationship("Message", back_populates="user", cascade="all, delete-orphan")


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
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

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
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class NewsTemplate(Base):
    __tablename__ = "news_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), unique=True, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


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
    replied_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class Folder(Base):
    __tablename__ = "folders"
    id = Column(Integer, primary_key=True)
    parent_id = Column(Integer, ForeignKey("folders.id", ondelete="CASCADE"), nullable=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class ContentItem(Base):
    __tablename__ = "content_items"
    id = Column(Integer, primary_key=True)
    folder_id = Column(Integer, ForeignKey("folders.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=True)
    link = Column(String, nullable=False)
    channel_username = Column(String, nullable=True)
    channel_message_id = Column(BigInteger, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
