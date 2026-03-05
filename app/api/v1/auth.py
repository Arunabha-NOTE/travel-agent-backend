from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core import ConflictError, DatabaseError, UnauthorizedError
from app.core.logging import get_logger
from app.core.metrics import AUTH_EVENTS
from app.core.security import create_access_token, hash_password, verify_password
from app.core.telemetry import get_tracer
from app.models.user import User

logger = get_logger(__name__)
tracer = get_tracer(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """Login request schema."""

    username: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=255)


class LoginResponse(BaseModel):
    """Login response schema."""

    access_token: str
    token_type: str = "bearer"
    user_id: int


class TokenRefreshRequest(BaseModel):
    """Token refresh request schema."""

    refresh_token: str


class RegisterRequest(BaseModel):
    """Registration request schema."""

    username: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=255)


@router.post("/login", response_model=LoginResponse)
async def login(
    credentials: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Authenticate user and return JWT access token.

    Args:
        credentials: User email and password
        db: Database session

    Returns:
        LoginResponse with access_token

    Raises:
        HTTPException: If credentials are invalid
    """
    with tracer.start_as_current_span("auth.login") as span:
        logger.info("Login attempt", username=credentials.username)
        AUTH_EVENTS.labels("login", "attempt").inc()

        try:
            result = await db.execute(
                select(User).where(User.username == credentials.username)
            )
            user = result.scalar_one_or_none()
        except SQLAlchemyError as error:
            logger.exception(
                "Database error during login",
                username=credentials.username,
                exc_info=error,
            )
            raise DatabaseError("Failed to authenticate user") from error

        if not user or not verify_password(credentials.password, user.hashed_password):
            span.set_attribute("auth.login.success", False)
            AUTH_EVENTS.labels("login", "failure").inc()
            raise UnauthorizedError("Invalid credentials")

        access_token = create_access_token(data={"sub": str(user.id)})
        span.set_attribute("auth.login.success", True)
        span.set_attribute("auth.user_id", user.id)
        AUTH_EVENTS.labels("login", "success").inc()

        logger.info("User logged in", user_id=user.id, username=user.username)

        return LoginResponse(
            access_token=access_token,
            token_type="bearer",
            user_id=user.id,
        )


@router.post("/register", response_model=LoginResponse)
async def register(
    credentials: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Register a new user and return JWT access token.

    Args:
        credentials: User email and password
        db: Database session

    Returns:
        LoginResponse with access_token for the new user

    Raises:
        HTTPException: If email already exists or validation fails
    """
    with tracer.start_as_current_span("auth.register") as span:
        logger.info("Registration attempt", username=credentials.username)
        AUTH_EVENTS.labels("register", "attempt").inc()

        try:
            existing_user = await db.execute(
                select(User).where(User.username == credentials.username)
            )
            if existing_user.scalar_one_or_none() is not None:
                span.set_attribute("auth.register.success", False)
                AUTH_EVENTS.labels("register", "failure").inc()
                raise ConflictError(
                    "Username already registered",
                    details={"username": credentials.username},
                )

            new_user = User(
                username=credentials.username,
                hashed_password=hash_password(credentials.password),
            )
            db.add(new_user)
            await db.commit()
            await db.refresh(new_user)
        except SQLAlchemyError as error:
            await db.rollback()
            logger.exception(
                "Database error during registration",
                username=credentials.username,
                exc_info=error,
            )
            raise DatabaseError("Failed to register user") from error

        access_token = create_access_token(data={"sub": str(new_user.id)})
        span.set_attribute("auth.register.success", True)
        span.set_attribute("auth.user_id", new_user.id)
        AUTH_EVENTS.labels("register", "success").inc()

        logger.info("User registered", user_id=new_user.id, username=new_user.username)

        return LoginResponse(
            access_token=access_token,
            token_type="bearer",
            user_id=new_user.id,
        )


@router.get("/verify")
async def verify_token():
    """
    Verify that the provided token is valid.

    Requires valid JWT token in Authorization header.

    Returns:
        {"message": "Token is valid"}
    """
    logger.info("Token verification requested")
    return {"message": "Token is valid"}
