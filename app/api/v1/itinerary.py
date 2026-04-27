"""Itinerary API — fetch the latest generated itinerary for a chat room."""

from __future__ import annotations

import uuid
from datetime import datetime
from time import perf_counter
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core import ResourceNotFoundError, get_logger
from app.models.chat_itinerary import ChatItinerary
from app.models.chat_room import ChatRoom
from app.models.user import User

logger = get_logger(__name__)

router = APIRouter(prefix="/chats", tags=["itinerary"])


class ShareStatusRequest(BaseModel):
    """Request schema for share status toggle."""

    is_public: bool


class ShareStatusResponse(BaseModel):
    """Response schema for share status toggle."""

    chat_id: uuid.UUID
    is_public: bool


class ItineraryResponse(BaseModel):
    """Response schema for a chat itinerary."""

    id: int
    chat_room_id: uuid.UUID
    itinerary_data: dict[str, Any]
    generated_at: datetime
    updated_at: datetime


@router.get("/{chat_id}/itinerary", response_model=ItineraryResponse)
async def get_itinerary(
    chat_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the latest generated travel itinerary for a chat room.

    Returns 404 if no itinerary has been generated yet for this chat.
    """
    started_at = perf_counter()
    logger.info(
        "Itinerary fetch started",
        chat_id=chat_id,
        user_id=current_user.id,
    )

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
        elapsed_ms = round((perf_counter() - started_at) * 1000, 2)
        logger.warning(
            "Itinerary fetch chat not found",
            chat_id=chat_id,
            user_id=current_user.id,
            elapsed_ms=elapsed_ms,
        )
        raise ResourceNotFoundError(resource="ChatRoom", resource_id=chat_id)

    # Fetch itinerary
    result = await db.execute(
        select(ChatItinerary).where(ChatItinerary.chat_room_id == chat_id)
    )
    itinerary = result.scalars().first()

    if itinerary is None:
        elapsed_ms = round((perf_counter() - started_at) * 1000, 2)
        logger.info(
            "Itinerary fetch empty",
            chat_id=chat_id,
            user_id=current_user.id,
            elapsed_ms=elapsed_ms,
        )
        raise ResourceNotFoundError(resource="ChatItinerary", resource_id=chat_id)

    itinerary_days = 0
    itinerary_activities = 0
    if isinstance(itinerary.itinerary_data, dict):
        raw_days = itinerary.itinerary_data.get("days")
        if isinstance(raw_days, list):
            itinerary_days = len([day for day in raw_days if isinstance(day, dict)])
            for day in raw_days:
                if not isinstance(day, dict):
                    continue
                activities = day.get("activities")
                if isinstance(activities, list):
                    itinerary_activities += len(
                        [
                            activity
                            for activity in activities
                            if isinstance(activity, dict)
                        ]
                    )

    elapsed_ms = round((perf_counter() - started_at) * 1000, 2)
    logger.info(
        "Itinerary fetch completed",
        chat_id=chat_id,
        user_id=current_user.id,
        itinerary_id=itinerary.id,
        days=itinerary_days,
        activities=itinerary_activities,
        updated_at=str(itinerary.updated_at),
        elapsed_ms=elapsed_ms,
    )

    return ItineraryResponse(
        id=itinerary.id,
        chat_room_id=itinerary.chat_room_id,
        itinerary_data=itinerary.itinerary_data,
        generated_at=itinerary.generated_at,
        updated_at=itinerary.updated_at,
    )


@router.get("/{chat_id}/itinerary/public", response_model=ItineraryResponse)
async def get_public_itinerary(
    chat_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get the latest generated travel itinerary for a chat room publicly.

    Only works if the chat room is marked as public.
    """
    # Verify chat is public
    chat_result = await db.execute(
        select(ChatRoom).where(
            and_(
                ChatRoom.id == chat_id,
                ChatRoom.is_public,
                ChatRoom.archived_at.is_(None),
            )
        )
    )
    if not chat_result.scalars().first():
        raise ResourceNotFoundError(resource="PublicChatRoom", resource_id=chat_id)

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


@router.patch("/{chat_id}/share", response_model=ShareStatusResponse)
async def toggle_share_itinerary(
    chat_id: uuid.UUID,
    payload: ShareStatusRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Toggle the public visibility of a chat itinerary."""
    is_public = payload.is_public
    chat_result = await db.execute(
        select(ChatRoom).where(
            and_(
                ChatRoom.id == chat_id,
                ChatRoom.user_id == current_user.id,
            )
        )
    )
    chat = chat_result.scalars().first()
    if not chat:
        raise ResourceNotFoundError(resource="ChatRoom", resource_id=chat_id)

    chat.is_public = is_public
    await db.commit()

    return ShareStatusResponse(chat_id=chat_id, is_public=is_public)
