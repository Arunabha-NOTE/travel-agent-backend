import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from app.main import app
from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.models.chat_room import ChatRoom
from app.models.chat_message import ChatMessage, MessageSenderRole

client = TestClient(app)

# Mock user
mock_user = User(id=1, email="test@example.com", is_active=True)


async def override_get_current_user():
    return mock_user


app.dependency_overrides[get_current_user] = override_get_current_user


def test_list_messages():
    mock_session = AsyncMock()
    chat_id = uuid.uuid4()

    # Mock chat ownership check
    mock_chat = ChatRoom(id=chat_id, user_id=1, title="Test Chat", archived_at=None)

    mock_msg = ChatMessage(
        id=1,
        chat_room_id=chat_id,
        sender_role=MessageSenderRole.user,
        content="Hello",
        created_at=datetime.now(timezone.utc),
    )

    mock_result_chat = MagicMock()
    mock_result_chat.scalars().first.return_value = mock_chat

    mock_result_msgs = MagicMock()
    mock_result_msgs.scalars().all.return_value = [mock_msg]

    mock_session.execute.side_effect = [mock_result_chat, mock_result_msgs]
    app.dependency_overrides[get_db] = lambda: mock_session

    response = client.get(f"/api/v1/chats/{chat_id}/messages")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["content"] == "Hello"


@patch("app.api.v1.messages.evaluate_user_prompt")
def test_send_message_blocked(mock_eval):
    mock_eval.return_value = (True, "violation")

    mock_session = AsyncMock()
    chat_id = uuid.uuid4()

    mock_chat = ChatRoom(id=chat_id, user_id=1, title="Test Chat", archived_at=None)
    mock_result_chat = MagicMock()
    mock_result_chat.scalars().first.return_value = mock_chat

    mock_session.execute.return_value = mock_result_chat
    app.dependency_overrides[get_db] = lambda: mock_session

    response = client.post(
        f"/api/v1/chats/{chat_id}/messages",
        json={"content": "bad prompt", "agent": "langchain"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"

    # Check stream content
    content = response.content.decode()
    assert "data: I can't help" in content
    assert "data: [DONE]" in content


def test_normalize_planning_stage():
    from app.api.v1.messages import _normalize_planning_stage

    assert _normalize_planning_stage("FLIGHTS") == "transport"
    assert _normalize_planning_stage(None) == "initial"
    assert _normalize_planning_stage("  ") == "initial"
    assert _normalize_planning_stage("Hotel") == "hotel"
