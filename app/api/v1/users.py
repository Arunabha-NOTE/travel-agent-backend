from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core import ResourceNotFoundError, ValidationError, get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/")
async def list_users(db: AsyncSession = Depends(get_db)):
    """
    List all users.

    The `db` parameter is automatically injected by FastAPI
    and will be a fresh AsyncSession for this request.
    """
    logger.info("Fetching all users")
    # TODO: Implement actual database query
    return {"users": []}


@router.get("/{user_id}")
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    """
    Get a single user by ID.

    Demonstrates exception handling:
    - Raises ResourceNotFoundError if user doesn't exist
    """
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
    logger.info("Creating new user")
    # TODO: Implement actual user creation
    return {"user_id": 1, "name": "New User"}


@router.get("/me")
async def get_current_user_profile(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get the current authenticated user's profile.

    Requires valid JWT token in Authorization header.

    Example:
        Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
    """
    logger.info("Fetching current user profile", user_id=current_user.get("user_id"))
    # TODO: Implement actual user lookup from database
    return current_user
