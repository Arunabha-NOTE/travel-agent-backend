"""Planning session model — tracks multi-step travel planning state per chat."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.chat_room import ChatRoom


PLANNING_STAGES = ["initial", "flights", "hotels", "attractions", "complete"]

DEFAULT_PREFERENCES: dict[str, Any] = {
    "origin": None,
    "destination": None,
    "dates": {"start": None, "end": None, "flexible": False},
    "people": {"adults": None, "children": 0},
    "budget": {"amount": None, "currency": None, "type": "total"},
    "flights": {
        "class": None,
        "airlines_preferred": [],
        "memberships": [],
        "max_stops": None,
        "options_presented": [],
        "selected": None,
    },
    "hotels": {
        "stars": None,
        "brands_preferred": [],
        "memberships": [],
        "options_presented": [],
        "selected": None,
    },
    "attractions": {
        "interests": [],
        "confirmed": [],
        "excluded": [],
    },
}


class PlanningSession(Base):
    """Tracks the current multi-step travel planning stage and accumulated preferences."""

    __tablename__ = "planning_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    chat_room_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_rooms.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    stage: Mapped[str] = mapped_column(String(32), default="initial")
    preferences: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=lambda: dict(DEFAULT_PREFERENCES)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        index=True,
    )

    chat_room: Mapped["ChatRoom"] = relationship(back_populates="planning_session")
