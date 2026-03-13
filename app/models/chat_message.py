from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.chat_room import ChatRoom


class MessageSenderRole(str, enum.Enum):
    """Supported message sender roles for chat-style conversations."""

    user = "user"
    assistant = "assistant"
    system = "system"
    tool = "tool"


class ChatMessage(Base):
    """Stores individual messages within a chat room."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_room_created", "chat_room_id", "created_at"),
        Index("ix_chat_messages_room_sender", "chat_room_id", "sender_role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    chat_room_id: Mapped[int] = mapped_column(
        ForeignKey("chat_rooms.id", ondelete="CASCADE"),
        index=True,
    )
    sender_role: Mapped[MessageSenderRole] = mapped_column(
        Enum(MessageSenderRole, name="message_sender_role", validate_strings=True),
        index=True,
    )
    sender_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text)
    message_metadata: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )

    chat_room: Mapped["ChatRoom"] = relationship(back_populates="messages")
