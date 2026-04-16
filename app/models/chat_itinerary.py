from __future__ import annotations

from datetime import datetime
from typing import Any, TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, func
import uuid
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.chat_room import ChatRoom


class ChatItinerary(Base):
    """Stores the latest generated travel itinerary for a chat room."""

    __tablename__ = "chat_itineraries"
    __table_args__ = (Index("ix_chat_itineraries_room_id", "chat_room_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    chat_room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_rooms.id", ondelete="CASCADE"),
        unique=True,
    )
    itinerary_data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        index=True,
    )

    chat_room: Mapped["ChatRoom"] = relationship(back_populates="itinerary")
