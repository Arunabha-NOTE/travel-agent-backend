from __future__ import annotations

from datetime import datetime, timezone
import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core import ResourceNotFoundError, ValidationError, get_logger
from app.models.chat_room import ChatRoom
from app.models.user import User

logger = get_logger(__name__)

router = APIRouter(prefix="/chats", tags=["chats"])


class ChatCreateRequest(BaseModel):
    """Create chat request payload."""

    title: str = Field(default="New chat", min_length=1, max_length=255)


class ChatRenameRequest(BaseModel):
    """Rename chat request payload."""

    title: str = Field(min_length=1, max_length=255)


class ChatResponse(BaseModel):
    """Response schema for chat room operations."""

    id: uuid.UUID
    user_id: int
    title: str
    created_at: datetime
    updated_at: datetime


def _serialize_chat(chat: ChatRoom) -> ChatResponse:
    return ChatResponse(
        id=chat.id,
        user_id=chat.user_id,
        title=chat.title,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
    )


def _normalize_title(title: str) -> str:
    normalized = title.strip()
    if not normalized:
        raise ValidationError("Chat title cannot be empty")
    return normalized


async def _get_owned_chat_or_404(
    *,
    db: AsyncSession,
    chat_id: uuid.UUID,
    user_id: int,
) -> ChatRoom:
    result = await db.execute(
        select(ChatRoom).where(
            and_(
                ChatRoom.id == chat_id,
                ChatRoom.user_id == user_id,
                ChatRoom.archived_at.is_(None),
            )
        )
    )
    chat = result.scalars().first()
    if chat is None:
        raise ResourceNotFoundError(resource="ChatRoom", resource_id=chat_id)
    return chat


@router.get("/", response_model=list[ChatResponse])
async def list_chats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all non-archived chat rooms for the authenticated user."""
    result = await db.execute(
        select(ChatRoom)
        .where(
            and_(
                ChatRoom.user_id == current_user.id,
                ChatRoom.archived_at.is_(None),
            )
        )
        .order_by(ChatRoom.updated_at.desc())
    )
    chats = result.scalars().all()
    return [_serialize_chat(chat) for chat in chats]


@router.get("/{chat_id}", response_model=ChatResponse)
async def get_chat(
    chat_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single chat room owned by the authenticated user."""
    chat = await _get_owned_chat_or_404(db=db, chat_id=chat_id, user_id=current_user.id)
    return _serialize_chat(chat)


@router.post("/", response_model=ChatResponse, status_code=status.HTTP_201_CREATED)
async def create_chat(
    payload: ChatCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new chat room for the authenticated user."""
    title = _normalize_title(payload.title)

    chat = ChatRoom(user_id=current_user.id, title=title)
    db.add(chat)
    await db.commit()
    await db.refresh(chat)

    logger.info("Chat room created", chat_id=chat.id, user_id=current_user.id)
    return _serialize_chat(chat)


@router.patch("/{chat_id}", response_model=ChatResponse)
async def rename_chat(
    chat_id: uuid.UUID,
    payload: ChatRenameRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rename an existing chat room owned by the authenticated user."""
    title = _normalize_title(payload.title)
    chat = await _get_owned_chat_or_404(db=db, chat_id=chat_id, user_id=current_user.id)

    chat.title = title
    chat.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(chat)

    logger.info("Chat room renamed", chat_id=chat.id, user_id=current_user.id)
    return _serialize_chat(chat)


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(
    chat_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete an existing chat room owned by the authenticated user."""
    chat = await _get_owned_chat_or_404(db=db, chat_id=chat_id, user_id=current_user.id)

    await db.delete(chat)
    await db.commit()

    logger.info("Chat room deleted", chat_id=chat_id, user_id=current_user.id)
