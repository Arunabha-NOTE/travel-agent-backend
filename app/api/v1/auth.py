from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_token, get_db
from app.core import (
    ConflictError,
    ResourceNotFoundError,
    UnauthorizedError,
    ValidationError,
)
from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import AUTH_EVENTS
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.core.telemetry import get_tracer
from app.models.auth_session import AuthSession
from app.models.password_reset_token import PasswordResetToken
from app.models.user import User

logger = get_logger(__name__)
tracer = get_tracer(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """Login request schema."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=255)


class LoginResponse(BaseModel):
    """Login response schema."""

    user_id: int


class TokenRefreshRequest(BaseModel):
    """Token refresh request schema."""

    refresh_token: str | None = None


class LogoutRequest(BaseModel):
    """Logout request schema."""

    refresh_token: str | None = None


class RegisterRequest(BaseModel):
    """Register request schema."""

    email: EmailStr
    password: str


class ForgotPasswordRequest(BaseModel):
    """Forgot password request schema."""

    email: EmailStr


class ForgotPasswordResponse(BaseModel):
    """Forgot password response schema."""

    message: str
    reset_token: str | None = None


class ResetPasswordRequest(BaseModel):
    """Reset password request schema."""

    token: str
    new_password: str


def _username_from_email(email: str) -> str:
    base = email.split("@")[0].strip().lower()
    cleaned = "".join(char for char in base if char.isalnum() or char == "_")
    suffix = secrets.token_hex(3)
    return f"{cleaned or 'user'}_{suffix}"


def _extract_request_metadata(request: Request) -> tuple[str | None, str | None]:
    forwarded_for = request.headers.get("x-forwarded-for")
    ip_address = (
        forwarded_for.split(",")[0].strip()
        if forwarded_for
        else (request.client.host if request.client else None)
    )
    user_agent = request.headers.get("user-agent")
    return ip_address, user_agent


def _is_secure_cookie_request(request: Request) -> bool:
    forwarded_proto = request.headers.get("x-forwarded-proto", "")
    if forwarded_proto:
        return forwarded_proto.split(",")[0].strip().lower() == "https"
    return request.url.scheme == "https"


def _set_auth_cookies(
    response: Response,
    request: Request,
    *,
    access_token: str,
    refresh_token: str,
) -> None:
    secure = _is_secure_cookie_request(request)
    access_max_age = int(timedelta(hours=settings.JWT_EXPIRATION_HOURS).total_seconds())
    refresh_max_age = int(
        timedelta(days=settings.JWT_REFRESH_EXPIRATION_DAYS).total_seconds()
    )

    response.set_cookie(
        key=settings.AUTH_ACCESS_COOKIE_NAME,
        value=access_token,
        max_age=access_max_age,
        httponly=True,
        secure=secure,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path="/",
    )
    response.set_cookie(
        key=settings.AUTH_REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=refresh_max_age,
        httponly=True,
        secure=secure,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path="/",
    )


def _clear_auth_cookies(response: Response, request: Request) -> None:
    secure = _is_secure_cookie_request(request)
    response.delete_cookie(
        key=settings.AUTH_ACCESS_COOKIE_NAME,
        httponly=True,
        secure=secure,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path="/",
    )
    response.delete_cookie(
        key=settings.AUTH_REFRESH_COOKIE_NAME,
        httponly=True,
        secure=secure,
        samesite=settings.AUTH_COOKIE_SAMESITE,
        path="/",
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    credentials: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate user and return JWT access and refresh tokens."""
    with tracer.start_as_current_span("auth.login") as span:
        logger.info("Login attempt", email=credentials.email)
        AUTH_EVENTS.labels("login", "attempt").inc()

        result = await db.execute(
            select(User).where(User.email == credentials.email.lower())
        )
        user = result.scalars().first()
        if user is None or not verify_password(
            credentials.password, user.hashed_password
        ):
            span.set_attribute("auth.login.success", False)
            AUTH_EVENTS.labels("login", "failure").inc()
            raise UnauthorizedError("Invalid credentials")

        if not user.is_active:
            span.set_attribute("auth.login.success", False)
            AUTH_EVENTS.labels("login", "failure").inc()
            raise UnauthorizedError("User account is inactive")

        access_token = create_access_token(
            data={"sub": str(user.id), "email": user.email}
        )
        refresh_token = create_refresh_token()
        refresh_token_hash = hash_token(refresh_token)
        ip_address, user_agent = _extract_request_metadata(request)

        expires_at = datetime.now(timezone.utc) + timedelta(
            days=settings.JWT_REFRESH_EXPIRATION_DAYS
        )
        session = AuthSession(
            user_id=user.id,
            refresh_token_hash=refresh_token_hash,
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=expires_at,
        )
        db.add(session)
        await db.commit()

        span.set_attribute("auth.login.success", True)
        span.set_attribute("auth.user_id", user.id)
        AUTH_EVENTS.labels("login", "success").inc()

        logger.info(
            "User logged in", email=credentials.email, user_id=user.id, ip=ip_address
        )

        _set_auth_cookies(
            response,
            request,
            access_token=access_token,
            refresh_token=refresh_token,
        )

        return LoginResponse(
            user_id=user.id,
        )


@router.post("/register", response_model=LoginResponse)
async def register(
    credentials: RegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Register a new user and return JWT access and refresh tokens."""
    with tracer.start_as_current_span("auth.register") as span:
        logger.info("Registration attempt", email=credentials.email)
        AUTH_EVENTS.labels("register", "attempt").inc()

        existing = await db.execute(
            select(User).where(User.email == credentials.email.lower())
        )
        if existing.scalars().first() is not None:
            span.set_attribute("auth.register.success", False)
            AUTH_EVENTS.labels("register", "failure").inc()
            raise ConflictError(
                "Email already registered", {"email": credentials.email}
            )

        if len(credentials.password) < 8:
            span.set_attribute("auth.register.success", False)
            AUTH_EVENTS.labels("register", "failure").inc()
            raise ValidationError("Password must be at least 8 characters")

        new_user = User(
            email=credentials.email.lower(),
            username=_username_from_email(credentials.email),
            hashed_password=hash_password(credentials.password),
        )
        db.add(new_user)
        await db.flush()

        access_token = create_access_token(
            data={"sub": str(new_user.id), "email": new_user.email}
        )
        refresh_token = create_refresh_token()

        ip_address, user_agent = _extract_request_metadata(request)
        session = AuthSession(
            user_id=new_user.id,
            refresh_token_hash=hash_token(refresh_token),
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.JWT_REFRESH_EXPIRATION_DAYS),
        )
        db.add(session)
        await db.commit()
        await db.refresh(new_user)

        span.set_attribute("auth.register.success", True)
        span.set_attribute("auth.user_id", new_user.id)
        AUTH_EVENTS.labels("register", "success").inc()

        logger.info("User registered", email=credentials.email, user_id=new_user.id)

        _set_auth_cookies(
            response,
            request,
            access_token=access_token,
            refresh_token=refresh_token,
        )

        return LoginResponse(
            user_id=new_user.id,
        )


@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(
    request: Request,
    response: Response,
    payload: TokenRefreshRequest | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Exchange a valid refresh token for a new access token."""
    refresh_token_value = (payload.refresh_token if payload else None) or request.cookies.get(
        settings.AUTH_REFRESH_COOKIE_NAME
    )
    if not refresh_token_value:
        raise UnauthorizedError("Missing refresh token")

    token_hash = hash_token(refresh_token_value)
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(AuthSession).where(
            and_(
                AuthSession.refresh_token_hash == token_hash,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
            )
        )
    )
    session = result.scalars().first()
    if session is None:
        raise UnauthorizedError("Invalid or expired refresh token")

    user_result = await db.execute(select(User).where(User.id == session.user_id))
    user = user_result.scalars().first()
    if user is None:
        raise ResourceNotFoundError("User", session.user_id)

    session.last_used_at = now
    ip_address, _ = _extract_request_metadata(request)
    if ip_address:
        session.ip_address = ip_address
    await db.commit()

    access_token = create_access_token(data={"sub": str(user.id), "email": user.email})
    logger.info("Access token refreshed", user_id=user.id, session_id=session.id)

    _set_auth_cookies(
        response,
        request,
        access_token=access_token,
        refresh_token=refresh_token_value,
    )

    return LoginResponse(
        user_id=user.id,
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    payload: LogoutRequest | None = Body(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Revoke an active refresh-token session."""
    refresh_token_value = (payload.refresh_token if payload else None) or request.cookies.get(
        settings.AUTH_REFRESH_COOKIE_NAME
    )
    if refresh_token_value is None:
        _clear_auth_cookies(response, request)
        return {"message": "Logged out successfully"}

    token_hash = hash_token(refresh_token_value)
    result = await db.execute(
        select(AuthSession).where(
            and_(
                AuthSession.refresh_token_hash == token_hash,
                AuthSession.revoked_at.is_(None),
            )
        )
    )
    session = result.scalars().first()
    if session:
        session.revoked_at = datetime.now(timezone.utc)
        await db.commit()

    _clear_auth_cookies(response, request)

    return {"message": "Logged out successfully"}


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Generate and persist a password reset token when a user exists."""
    result = await db.execute(select(User).where(User.email == payload.email.lower()))
    user = result.scalars().first()

    reset_token: str | None = None
    if user:
        reset_token = create_refresh_token()
        db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=hash_token(reset_token),
                requested_ip=_extract_request_metadata(request)[0],
                expires_at=datetime.now(timezone.utc)
                + timedelta(minutes=settings.PASSWORD_RESET_EXPIRATION_MINUTES),
            )
        )
        await db.commit()

    logger.info("Password reset requested", email=payload.email)

    return ForgotPasswordResponse(
        message="If an account exists for this email, a reset link has been sent",
        reset_token=reset_token if settings.DEBUG else None,
    )


@router.post("/reset-password")
async def reset_password(
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Reset user password using a valid one-time reset token."""
    if len(payload.new_password) < 8:
        raise ValidationError("Password must be at least 8 characters")

    token_hash = hash_token(payload.token)
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(PasswordResetToken).where(
            and_(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > now,
            )
        )
    )
    reset = result.scalars().first()
    if reset is None:
        raise UnauthorizedError("Invalid or expired reset token")

    user_result = await db.execute(select(User).where(User.id == reset.user_id))
    user = user_result.scalars().first()
    if user is None:
        raise ResourceNotFoundError("User", reset.user_id)

    user.hashed_password = hash_password(payload.new_password)
    reset.used_at = now

    active_sessions = await db.execute(
        select(AuthSession).where(
            and_(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        )
    )
    for session in active_sessions.scalars().all():
        session.revoked_at = now

    await db.commit()
    logger.info("Password reset completed", user_id=user.id)
    return {"message": "Password reset successful"}


@router.get("/verify")
async def verify_token_endpoint(token: dict = Depends(get_current_user_token)):
    """
    Verify that the provided token is valid.

    Requires valid JWT token in Authorization header.

    Returns:
        {"message": "Token is valid"}
    """
    logger.info("Token verification requested", user_id=token.get("sub"))
    return {"message": "Token is valid", "user_id": token.get("sub")}
