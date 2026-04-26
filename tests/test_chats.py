import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.models.chat_room import ChatRoom
from app.core import ValidationError

client = TestClient(app)

# Mock user
mock_user = User(id=1, email="test@example.com", is_active=True)


async def override_get_current_user():
    return mock_user


app.dependency_overrides[get_current_user] = override_get_current_user


def test_normalize_title():
    from app.api.v1.chats import _normalize_title

    assert _normalize_title("  Valid Title  ") == "Valid Title"

    with pytest.raises(ValidationError):
        _normalize_title("")

    with pytest.raises(ValidationError):
        _normalize_title("a" * 81)

    with pytest.raises(ValidationError):
        _normalize_title("Control \x00 Char")


def test_create_chat_endpoint():
    mock_session = AsyncMock()
    mock_session.commit.return_value = None

    async def mock_refresh(instance):
        instance.id = uuid.uuid4()
        instance.created_at = datetime.now(timezone.utc)
        instance.updated_at = datetime.now(timezone.utc)

    mock_session.refresh.side_effect = mock_refresh
    app.dependency_overrides[get_db] = lambda: mock_session

    response = client.post("/api/v1/chats/", json={"title": "New Chat"})

    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "New Chat"
    assert "id" in data


def test_list_chats():
    mock_session = AsyncMock()
    mock_chat = ChatRoom(
        id=uuid.uuid4(),
        user_id=1,
        title="Test Chat",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    mock_result = MagicMock()
    mock_result.scalars().all.return_value = [mock_chat]
    mock_session.execute.return_value = mock_result
    app.dependency_overrides[get_db] = lambda: mock_session

    response = client.get("/api/v1/chats/")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["title"] == "Test Chat"


def test_get_chat():
    mock_session = AsyncMock()
    chat_id = uuid.uuid4()
    mock_chat = ChatRoom(
        id=chat_id,
        user_id=1,
        title="Specific Chat",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    mock_result = MagicMock()
    mock_result.scalars().first.return_value = mock_chat
    mock_session.execute.return_value = mock_result
    app.dependency_overrides[get_db] = lambda: mock_session

    response = client.get(f"/api/v1/chats/{chat_id}")
    assert response.status_code == 200
    assert response.json()["title"] == "Specific Chat"


def test_get_chat_not_found():
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars().first.return_value = None
    mock_session.execute.return_value = mock_result
    app.dependency_overrides[get_db] = lambda: mock_session

    chat_id = uuid.uuid4()
    response = client.get(f"/api/v1/chats/{chat_id}")
    assert response.status_code == 404


def test_rename_chat():
    mock_session = AsyncMock()
    chat_id = uuid.uuid4()
    mock_chat = ChatRoom(
        id=chat_id,
        user_id=1,
        title="Old Title",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    mock_result = MagicMock()
    mock_result.scalars().first.return_value = mock_chat
    mock_session.execute.return_value = mock_result

    async def mock_refresh(instance):
        pass  # Title already updated by the code

    mock_session.refresh.side_effect = mock_refresh
    app.dependency_overrides[get_db] = lambda: mock_session

    response = client.patch(f"/api/v1/chats/{chat_id}", json={"title": "Renamed Chat"})

    assert response.status_code == 200
    assert response.json()["title"] == "Renamed Chat"


def test_delete_chat():
    mock_session = AsyncMock()
    chat_id = uuid.uuid4()
    mock_chat = ChatRoom(
        id=chat_id,
        user_id=1,
        title="Delete Me",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    mock_result = MagicMock()
    mock_result.scalars().first.return_value = mock_chat
    mock_session.execute.return_value = mock_result
    app.dependency_overrides[get_db] = lambda: mock_session

    response = client.delete(f"/api/v1/chats/{chat_id}")
    assert response.status_code == 204
    mock_session.delete.assert_called_once()
