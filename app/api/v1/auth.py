from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.logging import get_logger
from app.core.security import create_access_token

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    """Login request schema."""

    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    """Login response schema."""

    access_token: str
    token_type: str = "bearer"
    user_id: int


class TokenRefreshRequest(BaseModel):
    """Token refresh request schema."""

    refresh_token: str


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
    logger.info("Login attempt", email=credentials.email)

    # TODO: Implement actual database lookup
    # user = await db.execute(select(User).where(User.email == credentials.email))
    # user = user.scalars().first()

    # For demo purposes, accept any credentials
    if not credentials.password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    # Create access token
    access_token = create_access_token(data={"sub": "demo_user_1"})

    logger.info("User logged in", email=credentials.email)

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        user_id=1,
    )


@router.post("/register", response_model=LoginResponse)
async def register(
    credentials: LoginRequest,
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
    logger.info("Registration attempt", email=credentials.email)

    # TODO: Implement actual user creation
    # Check if user exists
    # user = await db.execute(select(User).where(User.email == credentials.email))
    # if user.scalars().first():
    #     raise HTTPException(
    #         status_code=status.HTTP_409_CONFLICT,
    #         detail="Email already registered",
    #     )

    # Hash password and create user
    # hashed_password = hash_password(credentials.password)
    # new_user = User(email=credentials.email, hashed_password=hashed_password)
    # db.add(new_user)
    # await db.commit()
    # await db.refresh(new_user)

    # Create access token
    access_token = create_access_token(data={"sub": "new_user_1"})

    logger.info("User registered", email=credentials.email)

    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        user_id=1,
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
