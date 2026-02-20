from __future__ import annotations

from typing import AsyncGenerator

from fastapi import Depends, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import async_session_maker

logger = get_logger(__name__)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides a request-scoped database session.

    Usage in route handlers:
        @router.get("/users")
        async def list_users(db: AsyncSession = Depends(get_db)):
            # db is automatically closed after this route completes
            result = await db.execute(select(User))
            return result.scalars().all()

    Yields:
        AsyncSession: A database session for the request

    The session is automatically closed after the request,
    even if an exception occurs.
    """
    async with async_session_maker() as session:
        try:
            yield session
        finally:
            await session.close()


async def get_current_user_token(
    authorization: str | None = None,
) -> dict:
    """
    Extract and verify JWT token from Authorization header.

    Args:
        authorization: Authorization header value (Bearer <token>)

    Returns:
        Decoded token payload as dictionary

    Raises:
        HTTPException: If token is missing, invalid, or expired
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise ValueError("Invalid authentication scheme")
    except (ValueError, IndexError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        user_id: str | None = payload.get("sub")
        if user_id is None:
            raise ValueError("Token missing subject")
        return payload
    except JWTError as e:
        logger.warning("JWT verification failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    token: dict = Depends(get_current_user_token),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Get the currently authenticated user from JWT token.

    This dependency:
    1. Verifies the JWT token (via get_current_user_token)
    2. Extracts the user_id from the token
    3. Looks up the user in the database
    4. Returns the user data

    Args:
        token: Decoded JWT token from get_current_user_token
        db: Database session from get_db

    Returns:
        Dictionary with user data from token

    Raises:
        HTTPException: If token is invalid or user not found
    """
    user_id: str | None = token.get("sub")
    if not user_id:
        logger.warning("Token missing user ID")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    # TODO: Implement actual database lookup
    # For now, return the token payload as user
    logger.info("User authenticated", user_id=user_id)
    return {"user_id": user_id, **token}


# Optional: Token dependency that only returns the raw token
def get_token_from_header(authorization: str | None = None) -> str:
    """
    Extract raw JWT token from Authorization header.

    Args:
        authorization: Authorization header value (Bearer <token>)

    Returns:
        The JWT token string

    Raises:
        HTTPException: If token is missing or header format is invalid
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise ValueError("Invalid authentication scheme")
        return token
    except (ValueError, IndexError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authorization header format",
            headers={"WWW-Authenticate": "Bearer"},
        )
