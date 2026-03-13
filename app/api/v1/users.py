from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core import (
    ResourceNotFoundError,
    UnauthorizedError,
    ValidationError,
    get_logger,
)
from app.core.security import hash_password, verify_password
from app.core.telemetry import get_tracer
from app.models.user import User

logger = get_logger(__name__)
tracer = get_tracer(__name__)

router = APIRouter(prefix="/users", tags=["users"])


class ResetPasswordFromProfileRequest(BaseModel):
    """Authenticated profile password reset payload."""

    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8)


@router.get("/")
async def list_users(db: AsyncSession = Depends(get_db)):
    """
    List all users.

    The `db` parameter is automatically injected by FastAPI
    and will be a fresh AsyncSession for this request.
    """
    with tracer.start_as_current_span("users.list"):
        logger.info("Fetching all users")
        # TODO: Implement actual database query
        return {"users": []}


@router.get("/me")
async def get_current_user_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the current authenticated user's profile.

    Requires valid JWT token in Authorization header.

    Example:
        Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
    """
    with tracer.start_as_current_span("users.profile") as span:
        span.set_attribute("user.id", current_user.id)
        logger.info("Fetching current user profile", user_id=current_user.id)
        return {
            "id": current_user.id,
            "email": current_user.email,
            "username": current_user.username,
            "is_active": current_user.is_active,
            "is_superuser": current_user.is_superuser,
            "token_usage_millions": current_user.token_usage_millions,
        }


@router.post("/me/reset-password")
async def reset_password_from_profile(
    payload: ResetPasswordFromProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reset password for the authenticated user from profile settings."""
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise UnauthorizedError("Current password is incorrect")

    current_user.hashed_password = hash_password(payload.new_password)
    await db.commit()

    logger.info("Password reset from profile", user_id=current_user.id)
    return {"message": "Password updated successfully"}


@router.get("/{user_id}")
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    """
    Get a single user by ID.

    Demonstrates exception handling:
    - Raises ResourceNotFoundError if user doesn't exist
    """
    with tracer.start_as_current_span("users.get") as span:
        span.set_attribute("user.id", user_id)

        if user_id <= 0:
            raise ValidationError(
                message="user_id must be a positive integer",
                details={"user_id": user_id},
            )

        logger.info("Fetching user", user_id=user_id)

        # TODO: Implement actual database query
        # For now, simulate a not found error
        if user_id == 999:
            raise ResourceNotFoundError(resource="User", resource_id=user_id)

        return {"user_id": user_id, "name": f"User {user_id}"}


@router.post("/")
async def create_user(db: AsyncSession = Depends(get_db)):
    """
    Create a new user.

    Demonstrates exception handling:
    - Raises ValidationError if input is invalid
    """
    with tracer.start_as_current_span("users.create"):
        logger.info("Creating new user")
        # TODO: Implement actual user creation
        return {"user_id": 1, "name": "New User"}
