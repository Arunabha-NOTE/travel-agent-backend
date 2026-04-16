"""Itinerary API — fetch the latest generated itinerary for a chat room."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Any

from app.api.deps import get_current_user, get_db
from app.core import ResourceNotFoundError, get_logger
from app.models.chat_itinerary import ChatItinerary
from app.models.chat_room import ChatRoom
from app.models.user import User

logger = get_logger(__name__)

router = APIRouter(prefix="/chats", tags=["itinerary"])


class ItineraryResponse(BaseModel):
    """Response schema for a chat itinerary."""

    id: int
    chat_room_id: int
    itinerary_data: dict[str, Any]
    generated_at: datetime
    updated_at: datetime


@router.get("/{chat_id}/itinerary", response_model=ItineraryResponse)
async def get_itinerary(
    chat_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the latest generated travel itinerary for a chat room.

    Returns 404 if no itinerary has been generated yet for this chat.
    """
    # Verify chat ownership
    chat_result = await db.execute(
        select(ChatRoom).where(
            and_(
                ChatRoom.id == chat_id,
                ChatRoom.user_id == current_user.id,
                ChatRoom.archived_at.is_(None),
            )
        )
    )
    if not chat_result.scalars().first():
        raise ResourceNotFoundError(resource="ChatRoom", resource_id=chat_id)

    # Fetch itinerary
    result = await db.execute(
        select(ChatItinerary).where(ChatItinerary.chat_room_id == chat_id)
    )
    itinerary = result.scalars().first()

    if itinerary is None:
        raise ResourceNotFoundError(resource="ChatItinerary", resource_id=chat_id)

    return ItineraryResponse(
        id=itinerary.id,
        chat_room_id=itinerary.chat_room_id,
        itinerary_data=itinerary.itinerary_data,
        generated_at=itinerary.generated_at,
        updated_at=itinerary.updated_at,
    )
