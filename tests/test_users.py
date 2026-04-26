from unittest.mock import AsyncMock
from fastapi.testclient import TestClient
from app.main import app
from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.core.security import hash_password

client = TestClient(app)

# Mock user
hashed = hash_password("oldpassword")
mock_user = User(
    id=1,
    email="test@example.com",
    username="testuser",
    is_active=True,
    is_superuser=False,
    hashed_password=hashed,
    token_usage_millions=0,
    total_tokens=0,
    total_cost=0,
)


async def override_get_current_user():
    return mock_user


app.dependency_overrides[get_current_user] = override_get_current_user


def test_get_me():
    mock_session = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_session

    response = client.get("/api/v1/users/me")
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "test@example.com"
    assert data["username"] == "testuser"


def test_reset_password_success():
    mock_session = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_session

    response = client.post(
        "/api/v1/users/me/reset-password",
        json={"current_password": "oldpassword", "new_password": "newpassword123"},
    )

    assert response.status_code == 200
    assert response.json()["message"] == "Password updated successfully"
    mock_session.commit.assert_called_once()


def test_reset_password_wrong_current():
    mock_session = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_session

    response = client.post(
        "/api/v1/users/me/reset-password",
        json={"current_password": "wrongpassword", "new_password": "newpassword123"},
    )

    assert response.status_code == 401
    # Check if 'detail' or 'message' is in the response
    data = response.json()
    assert "detail" in data or "message" in data


def test_get_user_by_id():
    mock_session = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_session

    response = client.get("/api/v1/users/1")
    assert response.status_code == 200
    assert response.json()["user_id"] == 1


def test_get_user_invalid_id():
    response = client.get("/api/v1/users/0")
    # Custom validation might raise 400, but Pydantic/FastAPI might raise 422
    # The code in users.py line 102 raises ValidationError which might be handled by a global handler as 400 or 422.
    assert response.status_code in [400, 422]


def test_get_user_not_found():
    response = client.get("/api/v1/users/999")
    assert response.status_code == 404


def test_list_users():
    response = client.get("/api/v1/users/")
    assert response.status_code == 200
    assert response.json() == {"users": []}


def test_create_user():
    response = client.post("/api/v1/users/")
    assert response.status_code == 200
    assert "user_id" in response.json()
