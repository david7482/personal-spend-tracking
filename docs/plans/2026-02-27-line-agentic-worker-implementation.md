# LINE Agentic Message Worker — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the no-op ProcessLineMessage with an AI agent that uses Anthropic's tool_runner, code_execution, and a query_db tool to answer spending questions via LINE.

**Architecture:** Webhook router saves user message, sends loading animation, enqueues to SQS. Worker loads conversation history from DB, runs Anthropic tool_runner agent loop, saves assistant reply, pushes text via LINE Push API.

**Tech Stack:** Python 3.12, Anthropic SDK (`anthropic` package, `@beta_tool`, `tool_runner`), psycopg2, LINE Push API, Terraform, Alembic.

---

### Task 1: Add `anthropic` dependency

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add anthropic to poetry dependencies**

In `pyproject.toml`, add to `[tool.poetry.dependencies]`:

```toml
anthropic = "^0.84"
```

**Step 2: Install the dependency**

Run: `poetry lock --no-update && poetry install`
Expected: anthropic package installs successfully.

**Step 3: Commit**

```bash
git add pyproject.toml poetry.lock
git commit -m "chore: add anthropic SDK dependency"
```

---

### Task 2: Alembic migration — rename `line_messages` to `chat_messages`

**Files:**
- Create: `migrations/versions/006_rename_line_messages_to_chat_messages.py`

**Step 1: Create the migration file**

```python
"""rename line_messages to chat_messages

Revision ID: 006
Revises: 005
Create Date: 2026-02-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "006"
down_revision: Union[str, Sequence[str], None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE line_messages RENAME TO chat_messages")
    op.execute("ALTER TABLE chat_messages ADD COLUMN role TEXT")
    op.execute("UPDATE chat_messages SET role = 'user'")
    op.execute("ALTER TABLE chat_messages ALTER COLUMN role SET NOT NULL")
    op.execute("ALTER TABLE chat_messages RENAME COLUMN message TO content")
    op.execute("ALTER TABLE chat_messages DROP COLUMN reply_token")
    op.execute("DROP INDEX IF EXISTS idx_line_messages_user_id")
    op.execute("DROP INDEX IF EXISTS idx_line_messages_timestamp")
    op.execute(
        "CREATE INDEX idx_chat_messages_user_time "
        "ON chat_messages (line_user_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chat_messages_user_time")
    op.execute("ALTER TABLE chat_messages ADD COLUMN reply_token TEXT")
    op.execute("ALTER TABLE chat_messages RENAME COLUMN content TO message")
    op.execute("ALTER TABLE chat_messages DROP COLUMN role")
    op.execute("ALTER TABLE chat_messages RENAME TO line_messages")
    op.execute(
        "CREATE INDEX idx_line_messages_user_id ON line_messages(line_user_id)"
    )
    op.execute(
        "CREATE INDEX idx_line_messages_timestamp ON line_messages(timestamp DESC)"
    )
```

**Step 2: Commit**

```bash
git add migrations/versions/006_rename_line_messages_to_chat_messages.py
git commit -m "feat: add migration to rename line_messages to chat_messages"
```

---

### Task 3: Update domain model — replace `LineMessage` with `ChatMessage`

**Files:**
- Modify: `src/spend_tracking/domains/models.py`
- Modify: `src/spend_tracking/domains/models_test.py`

**Step 1: Write the test for the new ChatMessage dataclass**

In `src/spend_tracking/domains/models_test.py`, replace the `LineMessage` test (if any) or add:

```python
from datetime import UTC, datetime

from spend_tracking.domains.models import ChatMessage


def test_chat_message_creation():
    msg = ChatMessage(
        id=None,
        line_user_id="U123",
        role="user",
        content="Hello",
        message_type="text",
        raw_event={"type": "message"},
        timestamp=datetime(2026, 2, 27, 10, 0, 0, tzinfo=UTC),
        created_at=datetime(2026, 2, 27, 10, 0, 1, tzinfo=UTC),
    )
    assert msg.role == "user"
    assert msg.content == "Hello"
    assert msg.id is None
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/domains/models_test.py::test_chat_message_creation -v`
Expected: FAIL — `ChatMessage` does not exist yet.

**Step 3: Replace `LineMessage` with `ChatMessage` in models.py**

In `src/spend_tracking/domains/models.py`, replace the `LineMessage` dataclass:

```python
@dataclass
class ChatMessage:
    id: int | None
    line_user_id: str
    role: str
    content: str | None
    message_type: str
    raw_event: dict | None
    timestamp: datetime
    created_at: datetime
```

Remove the old `LineMessage` dataclass.

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/domains/models_test.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/spend_tracking/domains/models.py src/spend_tracking/domains/models_test.py
git commit -m "feat: replace LineMessage domain model with ChatMessage"
```

---

### Task 4: Create `ChatMessageRepository` interface and DB adapter

**Files:**
- Create: `src/spend_tracking/interfaces/chat_message_repository.py`
- Create: `src/spend_tracking/adapters/chat_message_repository_db.py`
- Create: `src/spend_tracking/adapters/chat_message_repository_db_test.py`

**Step 1: Create the interface**

`src/spend_tracking/interfaces/chat_message_repository.py`:

```python
from abc import ABC, abstractmethod

from spend_tracking.domains.models import ChatMessage


class ChatMessageRepository(ABC):
    @abstractmethod
    def save(self, message: ChatMessage) -> None: ...

    @abstractmethod
    def load_history(
        self, line_user_id: str, limit: int = 20
    ) -> list[ChatMessage]: ...

    @abstractmethod
    def get_by_id(self, message_id: int) -> ChatMessage | None: ...
```

**Step 2: Write tests for the DB adapter**

`src/spend_tracking/adapters/chat_message_repository_db_test.py`:

```python
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from spend_tracking.domains.models import ChatMessage


def _make_chat_message(role: str = "user") -> ChatMessage:
    return ChatMessage(
        id=None,
        line_user_id="U1234567890abcdef",
        role=role,
        content="Hello",
        message_type="text",
        raw_event={"type": "message"},
        timestamp=datetime(2026, 2, 27, 10, 0, 0, tzinfo=UTC),
        created_at=datetime(2026, 2, 27, 10, 0, 1, tzinfo=UTC),
    )


def _mock_db():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cur


@patch("spend_tracking.adapters.chat_message_repository_db.boto3")
@patch("spend_tracking.adapters.chat_message_repository_db.psycopg2")
def test_save_inserts_and_sets_id(mock_psycopg2, mock_boto3):
    from spend_tracking.adapters.chat_message_repository_db import (
        DbChatMessageRepository,
    )

    mock_boto3.client.return_value.get_parameter.return_value = {
        "Parameter": {"Value": "postgresql://fake"}
    }
    mock_conn, mock_cur = _mock_db()
    mock_cur.fetchone.return_value = (42,)
    mock_psycopg2.connect.return_value = mock_conn

    repo = DbChatMessageRepository("ssm-param-name")
    msg = _make_chat_message()
    repo.save(msg)

    mock_cur.execute.assert_called_once()
    sql = mock_cur.execute.call_args[0][0]
    assert "INSERT INTO chat_messages" in sql
    assert "RETURNING id" in sql
    assert msg.id == 42
    mock_conn.commit.assert_called_once()


@patch("spend_tracking.adapters.chat_message_repository_db.boto3")
@patch("spend_tracking.adapters.chat_message_repository_db.psycopg2")
def test_load_history_returns_ordered_messages(mock_psycopg2, mock_boto3):
    from spend_tracking.adapters.chat_message_repository_db import (
        DbChatMessageRepository,
    )

    mock_boto3.client.return_value.get_parameter.return_value = {
        "Parameter": {"Value": "postgresql://fake"}
    }
    mock_conn, mock_cur = _mock_db()
    mock_cur.fetchall.return_value = [
        (1, "U123", "user", "Hi", "text", None,
         datetime(2026, 2, 27, 9, 0, 0, tzinfo=UTC),
         datetime(2026, 2, 27, 9, 0, 0, tzinfo=UTC)),
        (2, "U123", "assistant", "Hello!", "text", None,
         datetime(2026, 2, 27, 9, 0, 1, tzinfo=UTC),
         datetime(2026, 2, 27, 9, 0, 1, tzinfo=UTC)),
    ]
    mock_psycopg2.connect.return_value = mock_conn

    repo = DbChatMessageRepository("ssm-param-name")
    messages = repo.load_history("U123", limit=20)

    assert len(messages) == 2
    assert messages[0].role == "user"
    assert messages[1].role == "assistant"
    sql = mock_cur.execute.call_args[0][0]
    assert "ORDER BY created_at ASC" in sql
    assert "LIMIT" in sql


@patch("spend_tracking.adapters.chat_message_repository_db.boto3")
@patch("spend_tracking.adapters.chat_message_repository_db.psycopg2")
def test_get_by_id_returns_message(mock_psycopg2, mock_boto3):
    from spend_tracking.adapters.chat_message_repository_db import (
        DbChatMessageRepository,
    )

    mock_boto3.client.return_value.get_parameter.return_value = {
        "Parameter": {"Value": "postgresql://fake"}
    }
    mock_conn, mock_cur = _mock_db()
    mock_cur.fetchone.return_value = (
        42, "U123", "user", "Hi", "text", None,
        datetime(2026, 2, 27, 9, 0, 0, tzinfo=UTC),
        datetime(2026, 2, 27, 9, 0, 0, tzinfo=UTC),
    )
    mock_psycopg2.connect.return_value = mock_conn

    repo = DbChatMessageRepository("ssm-param-name")
    msg = repo.get_by_id(42)

    assert msg is not None
    assert msg.id == 42
    assert msg.content == "Hi"


@patch("spend_tracking.adapters.chat_message_repository_db.boto3")
@patch("spend_tracking.adapters.chat_message_repository_db.psycopg2")
def test_get_by_id_returns_none_when_not_found(mock_psycopg2, mock_boto3):
    from spend_tracking.adapters.chat_message_repository_db import (
        DbChatMessageRepository,
    )

    mock_boto3.client.return_value.get_parameter.return_value = {
        "Parameter": {"Value": "postgresql://fake"}
    }
    mock_conn, mock_cur = _mock_db()
    mock_cur.fetchone.return_value = None
    mock_psycopg2.connect.return_value = mock_conn

    repo = DbChatMessageRepository("ssm-param-name")
    msg = repo.get_by_id(999)

    assert msg is None
```

**Step 3: Run tests to verify they fail**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/adapters/chat_message_repository_db_test.py -v`
Expected: FAIL — module does not exist yet.

**Step 4: Implement the DB adapter**

`src/spend_tracking/adapters/chat_message_repository_db.py`:

```python
import json

import boto3
import psycopg2

from spend_tracking.domains.models import ChatMessage
from spend_tracking.interfaces.chat_message_repository import ChatMessageRepository


class DbChatMessageRepository(ChatMessageRepository):
    def __init__(self, ssm_parameter_name: str) -> None:
        ssm = boto3.client("ssm")
        response = ssm.get_parameter(
            Name=ssm_parameter_name,
            WithDecryption=True,
        )
        self._connection_string = response["Parameter"]["Value"]

    def save(self, message: ChatMessage) -> None:
        with psycopg2.connect(self._connection_string) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO chat_messages "
                "(line_user_id, role, content, message_type, "
                "raw_event, timestamp, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "RETURNING id",
                (
                    message.line_user_id,
                    message.role,
                    message.content,
                    message.message_type,
                    json.dumps(message.raw_event) if message.raw_event else None,
                    message.timestamp,
                    message.created_at,
                ),
            )
            row = cur.fetchone()
            assert row is not None
            message.id = row[0]
            conn.commit()

    def load_history(
        self, line_user_id: str, limit: int = 20
    ) -> list[ChatMessage]:
        with psycopg2.connect(self._connection_string) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, line_user_id, role, content, message_type, "
                "raw_event, timestamp, created_at "
                "FROM chat_messages "
                "WHERE line_user_id = %s "
                "ORDER BY created_at DESC "
                "LIMIT %s",
                (line_user_id, limit),
            )
            rows = cur.fetchall()
        return [
            ChatMessage(
                id=row[0],
                line_user_id=row[1],
                role=row[2],
                content=row[3],
                message_type=row[4],
                raw_event=row[5],
                timestamp=row[6],
                created_at=row[7],
            )
            for row in reversed(rows)  # reverse to get chronological order
        ]

    def get_by_id(self, message_id: int) -> ChatMessage | None:
        with psycopg2.connect(self._connection_string) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, line_user_id, role, content, message_type, "
                "raw_event, timestamp, created_at "
                "FROM chat_messages WHERE id = %s",
                (message_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return ChatMessage(
            id=row[0],
            line_user_id=row[1],
            role=row[2],
            content=row[3],
            message_type=row[4],
            raw_event=row[5],
            timestamp=row[6],
            created_at=row[7],
        )
```

**Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/adapters/chat_message_repository_db_test.py -v`
Expected: PASS (all 4 tests).

**Step 6: Commit**

```bash
git add src/spend_tracking/interfaces/chat_message_repository.py \
        src/spend_tracking/adapters/chat_message_repository_db.py \
        src/spend_tracking/adapters/chat_message_repository_db_test.py
git commit -m "feat: add ChatMessageRepository interface and DB adapter"
```

---

### Task 5: Update `ReceiveLineWebhook` — use `ChatMessage`, add loading animation

**Files:**
- Modify: `src/spend_tracking/lambdas/services/receive_line_webhook.py`
- Modify: `src/spend_tracking/lambdas/services/receive_line_webhook_test.py`

**Step 1: Update tests to use `ChatMessage` and test loading animation**

Replace the full content of `src/spend_tracking/lambdas/services/receive_line_webhook_test.py`:

```python
import base64
import hashlib
import hmac
import json
from unittest.mock import MagicMock, call

CHANNEL_SECRET = "test-channel-secret"
LINE_CHANNEL_ACCESS_TOKEN = "test-token"


def _sign(body: str, secret: str = CHANNEL_SECRET) -> str:
    return base64.b64encode(
        hmac.new(
            secret.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    ).decode("utf-8")


def _make_webhook_body(
    user_id: str = "U1234567890abcdef",
    message_text: str = "Hello",
    message_type: str = "text",
    timestamp: int = 1740646800000,
) -> str:
    return json.dumps(
        {
            "events": [
                {
                    "type": "message",
                    "replyToken": "reply-token-abc",
                    "source": {"type": "user", "userId": user_id},
                    "timestamp": timestamp,
                    "message": {"type": message_type, "text": message_text},
                }
            ]
        }
    )


def test_valid_signature_saves_and_enqueues():
    from spend_tracking.lambdas.services.receive_line_webhook import (
        ReceiveLineWebhook,
    )

    repository = MagicMock()
    queue = MagicMock()

    def set_id(msg):
        msg.id = 42

    repository.save.side_effect = set_id

    body = _make_webhook_body()
    signature = _sign(body)

    service = ReceiveLineWebhook(
        CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, repository, queue
    )
    result = service.execute(body, signature)

    assert result["statusCode"] == 200
    repository.save.assert_called_once()
    saved = repository.save.call_args[0][0]
    assert saved.line_user_id == "U1234567890abcdef"
    assert saved.role == "user"
    assert saved.message_type == "text"
    assert saved.content == "Hello"
    assert saved.raw_event["type"] == "message"

    queue.send_message.assert_called_once()
    enqueued = queue.send_message.call_args[0][0]
    assert enqueued["chat_message_id"] == 42


def test_loading_animation_is_sent(monkeypatch):
    from spend_tracking.lambdas.services.receive_line_webhook import (
        ReceiveLineWebhook,
    )

    repository = MagicMock()
    queue = MagicMock()

    def set_id(msg):
        msg.id = 42

    repository.save.side_effect = set_id

    mock_urlopen = MagicMock()
    mock_urlopen.__enter__ = MagicMock()
    mock_urlopen.__exit__ = MagicMock(return_value=False)
    mock_urlopen_fn = MagicMock(return_value=mock_urlopen)
    monkeypatch.setattr(
        "spend_tracking.lambdas.services.receive_line_webhook.urlopen",
        mock_urlopen_fn,
    )

    body = _make_webhook_body()
    signature = _sign(body)

    service = ReceiveLineWebhook(
        CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, repository, queue
    )
    service.execute(body, signature)

    mock_urlopen_fn.assert_called_once()
    request = mock_urlopen_fn.call_args[0][0]
    assert "loading/start" in request.full_url
    payload = json.loads(request.data)
    assert payload["chatId"] == "U1234567890abcdef"


def test_invalid_signature_returns_401():
    from spend_tracking.lambdas.services.receive_line_webhook import (
        ReceiveLineWebhook,
    )

    repository = MagicMock()
    queue = MagicMock()

    body = _make_webhook_body()
    bad_signature = "invalid-signature"

    service = ReceiveLineWebhook(
        CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, repository, queue
    )
    result = service.execute(body, bad_signature)

    assert result["statusCode"] == 401
    repository.save.assert_not_called()
    queue.send_message.assert_not_called()


def test_non_message_events_are_skipped():
    from spend_tracking.lambdas.services.receive_line_webhook import (
        ReceiveLineWebhook,
    )

    repository = MagicMock()
    queue = MagicMock()

    body = json.dumps(
        {
            "events": [
                {
                    "type": "follow",
                    "source": {"type": "user", "userId": "U123"},
                    "timestamp": 1740646800000,
                }
            ]
        }
    )
    signature = _sign(body)

    service = ReceiveLineWebhook(
        CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, repository, queue
    )
    result = service.execute(body, signature)

    assert result["statusCode"] == 200
    repository.save.assert_not_called()
    queue.send_message.assert_not_called()


def test_non_text_message_saves_with_null_content():
    from spend_tracking.lambdas.services.receive_line_webhook import (
        ReceiveLineWebhook,
    )

    repository = MagicMock()
    queue = MagicMock()

    def set_id(msg):
        msg.id = 99

    repository.save.side_effect = set_id

    body = json.dumps(
        {
            "events": [
                {
                    "type": "message",
                    "replyToken": "token",
                    "source": {"type": "user", "userId": "U123"},
                    "timestamp": 1740646800000,
                    "message": {
                        "type": "sticker",
                        "stickerId": "123",
                        "packageId": "456",
                    },
                }
            ]
        }
    )
    signature = _sign(body)

    service = ReceiveLineWebhook(
        CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, repository, queue
    )
    result = service.execute(body, signature)

    assert result["statusCode"] == 200
    saved = repository.save.call_args[0][0]
    assert saved.message_type == "sticker"
    assert saved.content is None
```

**Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/lambdas/services/receive_line_webhook_test.py -v`
Expected: FAIL — constructor signature changed, `save_line_message` → `save`, etc.

**Step 3: Update `receive_line_webhook.py`**

Replace the full content of `src/spend_tracking/lambdas/services/receive_line_webhook.py`:

```python
import base64
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from urllib.request import Request, urlopen

from spend_tracking.domains.models import ChatMessage
from spend_tracking.interfaces.chat_message_repository import ChatMessageRepository
from spend_tracking.interfaces.line_message_queue import LineMessageQueue

logger = logging.getLogger(__name__)

LINE_LOADING_URL = "https://api.line.me/v2/bot/chat/loading/start"


class ReceiveLineWebhook:
    def __init__(
        self,
        channel_secret: str,
        channel_access_token: str,
        repository: ChatMessageRepository,
        queue: LineMessageQueue,
    ) -> None:
        self._channel_secret = channel_secret
        self._channel_access_token = channel_access_token
        self._repository = repository
        self._queue = queue

    def execute(self, body: str, signature: str) -> dict:
        if not self._verify_signature(body, signature):
            logger.warning("Invalid LINE webhook signature")
            return {"statusCode": 401, "body": "Invalid signature"}

        payload = json.loads(body)
        events = payload.get("events", [])

        for event in events:
            if event.get("type") != "message":
                logger.info(
                    "Skipping non-message event",
                    extra={"type": event.get("type")},
                )
                continue

            message_obj = event.get("message", {})
            message_type = message_obj.get("type", "unknown")
            message_text = message_obj.get("text") if message_type == "text" else None
            line_user_id = event["source"]["userId"]

            chat_message = ChatMessage(
                id=None,
                line_user_id=line_user_id,
                role="user",
                content=message_text,
                message_type=message_type,
                raw_event=event,
                timestamp=datetime.fromtimestamp(event["timestamp"] / 1000, tz=UTC),
                created_at=datetime.now(UTC),
            )

            self._repository.save(chat_message)
            logger.info(
                "Saved chat message",
                extra={
                    "chat_message_id": chat_message.id,
                    "line_user_id": line_user_id,
                    "message_type": message_type,
                },
            )

            self._send_loading_animation(line_user_id)
            self._queue.send_message({"chat_message_id": chat_message.id})

        return {"statusCode": 200, "body": "OK"}

    def _send_loading_animation(self, line_user_id: str) -> None:
        try:
            data = json.dumps({"chatId": line_user_id}).encode("utf-8")
            request = Request(
                LINE_LOADING_URL,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._channel_access_token}",
                },
            )
            with urlopen(request):
                pass
        except Exception:
            logger.exception(
                "Failed to send loading animation",
                extra={"line_user_id": line_user_id},
            )

    def _verify_signature(self, body: str, signature: str) -> bool:
        expected = base64.b64encode(
            hmac.new(
                self._channel_secret.encode("utf-8"),
                body.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        ).decode("utf-8")
        return hmac.compare_digest(expected, signature)
```

**Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/lambdas/services/receive_line_webhook_test.py -v`
Expected: PASS (all 5 tests).

**Step 5: Commit**

```bash
git add src/spend_tracking/lambdas/services/receive_line_webhook.py \
        src/spend_tracking/lambdas/services/receive_line_webhook_test.py
git commit -m "feat: update ReceiveLineWebhook to use ChatMessage and send loading animation"
```

---

### Task 6: Update webhook router handler wiring

**Files:**
- Modify: `src/spend_tracking/lambdas/line_webhook_router_handler.py`
- Modify: `src/spend_tracking/lambdas/line_webhook_router_handler_test.py`

**Step 1: Update the handler to wire `ChatMessageRepository` and `channel_access_token`**

Replace `src/spend_tracking/lambdas/line_webhook_router_handler.py`:

```python
import logging
import os

import boto3

from spend_tracking.adapters.chat_message_repository_db import (
    DbChatMessageRepository,
)
from spend_tracking.adapters.line_message_queue_sqs import SQSLineMessageQueue
from spend_tracking.lambdas.services.receive_line_webhook import ReceiveLineWebhook

logger = logging.getLogger()

_ssm = boto3.client("ssm")

_secrets = _ssm.get_parameters(
    Names=[
        os.environ["SSM_LINE_CHANNEL_SECRET"],
        os.environ["SSM_LINE_CHANNEL_ACCESS_TOKEN"],
    ],
    WithDecryption=True,
)
_params = {p["Name"]: p["Value"] for p in _secrets["Parameters"]}
_channel_secret = _params[os.environ["SSM_LINE_CHANNEL_SECRET"]]
_channel_access_token = _params[os.environ["SSM_LINE_CHANNEL_ACCESS_TOKEN"]]

_chat_message_repository = DbChatMessageRepository(
    os.environ["SSM_DB_CONNECTION_STRING"]
)
_line_message_queue = SQSLineMessageQueue(os.environ["SQS_LINE_MESSAGE_QUEUE_URL"])

_service = ReceiveLineWebhook(
    channel_secret=_channel_secret,
    channel_access_token=_channel_access_token,
    repository=_chat_message_repository,
    queue=_line_message_queue,
)


def handler(event: dict, context: object) -> dict:
    body = event["body"]
    signature = event["headers"]["x-line-signature"]
    return _service.execute(body, signature)
```

**Step 2: Update handler test to include the new env var**

Replace `src/spend_tracking/lambdas/line_webhook_router_handler_test.py`:

```python
import os
from unittest.mock import MagicMock, patch

_mock_boto3_client = MagicMock()
_mock_boto3_client.get_parameters.return_value = {
    "Parameters": [
        {"Name": "/test/secret", "Value": "fake-secret"},
        {"Name": "/test/token", "Value": "fake-token"},
    ]
}
_mock_boto3_client.get_parameter.return_value = {"Parameter": {"Value": "fake-db"}}

with (
    patch.dict(
        os.environ,
        {
            "SSM_LINE_CHANNEL_SECRET": "/test/secret",
            "SSM_LINE_CHANNEL_ACCESS_TOKEN": "/test/token",
            "SSM_DB_CONNECTION_STRING": "/test/db",
            "SQS_LINE_MESSAGE_QUEUE_URL": "https://test-queue",
        },
    ),
    patch("boto3.client", return_value=_mock_boto3_client),
):
    from spend_tracking.lambdas.line_webhook_router_handler import handler


@patch("spend_tracking.lambdas.line_webhook_router_handler._service")
def test_line_webhook_router_handler_delegates_to_service(mock_service):
    mock_service.execute.return_value = {"statusCode": 200, "body": "OK"}

    event = {
        "headers": {"x-line-signature": "test-signature"},
        "body": '{"events": []}',
    }
    result = handler(event, None)

    assert result["statusCode"] == 200
    mock_service.execute.assert_called_once_with('{"events": []}', "test-signature")


@patch("spend_tracking.lambdas.line_webhook_router_handler._service")
def test_line_webhook_router_handler_returns_401_on_bad_signature(mock_service):
    mock_service.execute.return_value = {
        "statusCode": 401,
        "body": "Invalid signature",
    }

    event = {
        "headers": {"x-line-signature": "bad-sig"},
        "body": "{}",
    }
    result = handler(event, None)

    assert result["statusCode"] == 401
```

**Step 3: Run tests**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/lambdas/line_webhook_router_handler_test.py -v`
Expected: PASS.

**Step 4: Commit**

```bash
git add src/spend_tracking/lambdas/line_webhook_router_handler.py \
        src/spend_tracking/lambdas/line_webhook_router_handler_test.py
git commit -m "feat: update webhook router handler to wire ChatMessageRepository and loading animation"
```

---

### Task 7: Implement `ProcessLineMessage` service with Anthropic tool_runner

**Files:**
- Modify: `src/spend_tracking/lambdas/services/process_line_message.py`
- Modify: `src/spend_tracking/lambdas/services/process_line_message_test.py`

**Step 1: Write tests**

Replace `src/spend_tracking/lambdas/services/process_line_message_test.py`:

```python
import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from spend_tracking.domains.models import ChatMessage

SYSTEM_PROMPT = "You are a personal finance assistant."


def _make_user_message(msg_id: int = 42, content: str = "Hello") -> ChatMessage:
    return ChatMessage(
        id=msg_id,
        line_user_id="U123",
        role="user",
        content=content,
        message_type="text",
        raw_event={"type": "message"},
        timestamp=datetime(2026, 2, 27, 10, 0, 0, tzinfo=UTC),
        created_at=datetime(2026, 2, 27, 10, 0, 1, tzinfo=UTC),
    )


def _make_history() -> list[ChatMessage]:
    return [
        ChatMessage(
            id=1,
            line_user_id="U123",
            role="user",
            content="How much did I spend?",
            message_type="text",
            raw_event=None,
            timestamp=datetime(2026, 2, 27, 9, 0, 0, tzinfo=UTC),
            created_at=datetime(2026, 2, 27, 9, 0, 0, tzinfo=UTC),
        ),
        ChatMessage(
            id=2,
            line_user_id="U123",
            role="assistant",
            content="You spent $100.",
            message_type="text",
            raw_event=None,
            timestamp=datetime(2026, 2, 27, 9, 0, 1, tzinfo=UTC),
            created_at=datetime(2026, 2, 27, 9, 0, 1, tzinfo=UTC),
        ),
    ]


def test_execute_loads_message_runs_agent_saves_and_pushes():
    from spend_tracking.lambdas.services.process_line_message import (
        ProcessLineMessage,
    )

    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = _make_user_message()
    mock_repo.load_history.return_value = _make_history()

    mock_final_message = MagicMock()
    mock_final_message.content = [MagicMock(type="text", text="Agent reply")]
    mock_final_message.model = "claude-opus-4-6"
    mock_final_message.stop_reason = "end_turn"
    mock_final_message.usage = MagicMock(
        input_tokens=100, output_tokens=50
    )

    mock_runner = MagicMock()
    mock_runner.until_done.return_value = mock_final_message

    mock_client = MagicMock()
    mock_client.beta.messages.tool_runner.return_value = mock_runner

    mock_push = MagicMock()

    service = ProcessLineMessage(
        client=mock_client,
        model="claude-opus-4-6",
        chat_message_repository=mock_repo,
        line_push_sender=mock_push,
        db_connection_string="postgresql://fake",
    )
    service.execute(chat_message_id=42)

    mock_repo.get_by_id.assert_called_once_with(42)
    mock_repo.load_history.assert_called_once_with("U123", limit=20)
    mock_client.beta.messages.tool_runner.assert_called_once()
    mock_repo.save.assert_called_once()
    saved = mock_repo.save.call_args[0][0]
    assert saved.role == "assistant"
    assert saved.content == "Agent reply"
    mock_push.send_text.assert_called_once_with("U123", "Agent reply")


def test_execute_handles_api_error_sends_fallback():
    from spend_tracking.lambdas.services.process_line_message import (
        ProcessLineMessage,
    )

    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = _make_user_message()
    mock_repo.load_history.return_value = []

    mock_runner = MagicMock()
    mock_runner.until_done.side_effect = Exception("API error")

    mock_client = MagicMock()
    mock_client.beta.messages.tool_runner.return_value = mock_runner

    mock_push = MagicMock()

    service = ProcessLineMessage(
        client=mock_client,
        model="claude-opus-4-6",
        chat_message_repository=mock_repo,
        line_push_sender=mock_push,
        db_connection_string="postgresql://fake",
    )
    service.execute(chat_message_id=42)

    mock_push.send_text.assert_called_once()
    fallback_text = mock_push.send_text.call_args[0][1]
    assert "try again" in fallback_text.lower() or "trouble" in fallback_text.lower()


def test_query_db_rejects_non_select():
    from spend_tracking.lambdas.services.process_line_message import (
        _validate_sql,
    )

    assert _validate_sql("SELECT * FROM transactions") is True
    assert _validate_sql("select count(*) from transactions") is True
    assert _validate_sql("DROP TABLE transactions") is False
    assert _validate_sql("DELETE FROM transactions") is False
    assert _validate_sql("INSERT INTO transactions VALUES (1)") is False
    assert _validate_sql("UPDATE transactions SET amount = 0") is False


def test_build_messages_from_history():
    from spend_tracking.lambdas.services.process_line_message import (
        _build_messages,
    )

    history = _make_history()
    current = _make_user_message(content="New question")
    messages = _build_messages(history, current)

    assert len(messages) == 3
    assert messages[0] == {"role": "user", "content": "How much did I spend?"}
    assert messages[1] == {"role": "assistant", "content": "You spent $100."}
    assert messages[2] == {"role": "user", "content": "New question"}
```

**Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/lambdas/services/process_line_message_test.py -v`
Expected: FAIL — `ProcessLineMessage` has wrong signature, helper functions don't exist.

**Step 3: Implement `ProcessLineMessage`**

Replace `src/spend_tracking/lambdas/services/process_line_message.py`:

```python
import json
import logging
from datetime import UTC, datetime

import psycopg2
from anthropic import Anthropic, beta_tool

from spend_tracking.domains.models import ChatMessage
from spend_tracking.interfaces.chat_message_repository import ChatMessageRepository

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are a personal finance assistant. You help the user understand their spending \
by querying their transaction database and performing calculations.

Always respond in the same language the user writes in.

You have access to:
- query_db: Run read-only SQL against the transactions table. Columns: id, source_type, \
source_id, bank, transaction_at, region, amount, currency, merchant, category, notes, \
raw_data, created_at.
- code_execution: Run Python/bash code for calculations, data analysis, and visualizations.

Guidelines:
- Keep responses concise (this is a chat app, not a report).
- Use query_db to look up real transaction data before answering spending questions.
- Use code_execution for calculations, aggregations, or formatting that SQL alone can't do.
- Amounts are stored as DECIMAL. Currency is a string like 'TWD', 'USD'.
- When showing monetary values, include the currency symbol.
- If the user's question is unclear, ask for clarification.\
"""

FALLBACK_MESSAGE = "Sorry, I'm having trouble right now. Please try again later."


class LinePushSender:
    """Sends text messages via LINE Push API."""

    def __init__(self, channel_access_token: str) -> None:
        self._token = channel_access_token

    def send_text(self, line_user_id: str, text: str) -> None:
        from urllib.request import Request, urlopen

        payload = {
            "to": line_user_id,
            "messages": [{"type": "text", "text": text}],
        }
        data = json.dumps(payload).encode("utf-8")
        request = Request(
            "https://api.line.me/v2/bot/message/push",
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._token}",
            },
        )
        with urlopen(request) as response:
            logger.info(
                "LINE push sent",
                extra={"line_user_id": line_user_id, "status": response.status},
            )


def _validate_sql(sql: str) -> bool:
    """Only allow SELECT statements."""
    stripped = sql.strip().upper()
    return stripped.startswith("SELECT") or stripped.startswith("WITH")


def _build_messages(
    history: list[ChatMessage], current: ChatMessage
) -> list[dict]:
    """Build Anthropic messages array from conversation history."""
    messages: list[dict] = []
    for msg in history:
        if msg.content is not None:
            messages.append({"role": msg.role, "content": msg.content})
    if current.content is not None:
        messages.append({"role": "user", "content": current.content})
    return messages


def _extract_text(message: object) -> str:
    """Extract text content from Anthropic response message."""
    parts: list[str] = []
    for block in message.content:  # type: ignore[attr-defined]
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts) if parts else FALLBACK_MESSAGE


def _make_query_db_tool(connection_string: str):  # type: ignore[no-untyped-def]
    """Create a query_db beta_tool function bound to a DB connection string."""

    @beta_tool
    def query_db(sql: str) -> str:
        """Run a read-only SQL query against the transactions table.
        Only SELECT statements are allowed. The transactions table has columns:
        id, source_type, source_id, bank, transaction_at, region, amount,
        currency, merchant, category, notes, raw_data, created_at.

        Args:
            sql: A SELECT SQL query to run against the transactions table.
        Returns:
            JSON array of result rows, or an error message.
        """
        if not _validate_sql(sql):
            return json.dumps({"error": "Only SELECT queries are allowed."})

        try:
            with psycopg2.connect(connection_string) as conn:
                with conn.cursor() as cur:
                    cur.execute(sql)
                    columns = [desc[0] for desc in cur.description or []]
                    rows = cur.fetchall()
                    result = [dict(zip(columns, row)) for row in rows]
                    return json.dumps(result, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)})

    return query_db


class ProcessLineMessage:
    def __init__(
        self,
        client: Anthropic,
        model: str,
        chat_message_repository: ChatMessageRepository,
        line_push_sender: LinePushSender,
        db_connection_string: str,
    ) -> None:
        self._client = client
        self._model = model
        self._repo = chat_message_repository
        self._push = line_push_sender
        self._db_connection_string = db_connection_string

    def execute(self, chat_message_id: int) -> None:
        user_msg = self._repo.get_by_id(chat_message_id)
        if user_msg is None:
            logger.error(
                "Chat message not found",
                extra={"chat_message_id": chat_message_id},
            )
            return

        history = self._repo.load_history(user_msg.line_user_id, limit=20)
        messages = _build_messages(history, user_msg)

        if not messages:
            logger.warning(
                "No messages to process",
                extra={"chat_message_id": chat_message_id},
            )
            return

        try:
            query_db_tool = _make_query_db_tool(self._db_connection_string)
            runner = self._client.beta.messages.tool_runner(
                model=self._model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=[
                    query_db_tool,
                    {"type": "code_execution_20250825", "name": "code_execution"},
                ],
                messages=messages,
            )
            final_message = runner.until_done()
            reply_text = _extract_text(final_message)
        except Exception:
            logger.exception(
                "Agent loop failed",
                extra={"chat_message_id": chat_message_id},
            )
            reply_text = FALLBACK_MESSAGE
            final_message = None

        assistant_msg = ChatMessage(
            id=None,
            line_user_id=user_msg.line_user_id,
            role="assistant",
            content=reply_text,
            message_type="text",
            raw_event=self._extract_metadata(final_message),
            timestamp=datetime.now(UTC),
            created_at=datetime.now(UTC),
        )
        self._repo.save(assistant_msg)

        self._push.send_text(user_msg.line_user_id, reply_text)

        logger.info(
            "Processed LINE message",
            extra={
                "chat_message_id": chat_message_id,
                "assistant_message_id": assistant_msg.id,
                "reply_length": len(reply_text),
            },
        )

    def _extract_metadata(self, message: object | None) -> dict | None:
        if message is None:
            return None
        try:
            return {
                "model": getattr(message, "model", None),
                "stop_reason": getattr(message, "stop_reason", None),
                "usage": {
                    "input_tokens": getattr(message.usage, "input_tokens", None),  # type: ignore[union-attr]
                    "output_tokens": getattr(message.usage, "output_tokens", None),  # type: ignore[union-attr]
                },
            }
        except Exception:
            return None
```

**Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/lambdas/services/process_line_message_test.py -v`
Expected: PASS (all 4 tests).

**Step 5: Commit**

```bash
git add src/spend_tracking/lambdas/services/process_line_message.py \
        src/spend_tracking/lambdas/services/process_line_message_test.py
git commit -m "feat: implement ProcessLineMessage with Anthropic tool_runner agent loop"
```

---

### Task 8: Update message worker handler wiring

**Files:**
- Modify: `src/spend_tracking/lambdas/line_message_worker_handler.py`
- Modify: `src/spend_tracking/lambdas/line_message_worker_handler_test.py`

**Step 1: Update the handler to wire all dependencies**

Replace `src/spend_tracking/lambdas/line_message_worker_handler.py`:

```python
import json
import logging
import os

import boto3
from anthropic import Anthropic

from spend_tracking.adapters.chat_message_repository_db import (
    DbChatMessageRepository,
)
from spend_tracking.lambdas.services.process_line_message import (
    LinePushSender,
    ProcessLineMessage,
)

logger = logging.getLogger()

_ssm = boto3.client("ssm")

_secrets = _ssm.get_parameters(
    Names=[
        os.environ["SSM_ANTHROPIC_API_KEY"],
        os.environ["SSM_LINE_CHANNEL_ACCESS_TOKEN"],
        os.environ["SSM_DB_CONNECTION_STRING"],
    ],
    WithDecryption=True,
)
_params = {p["Name"]: p["Value"] for p in _secrets["Parameters"]}

_anthropic_api_key = _params[os.environ["SSM_ANTHROPIC_API_KEY"]]
_line_channel_access_token = _params[os.environ["SSM_LINE_CHANNEL_ACCESS_TOKEN"]]
_db_connection_string = _params[os.environ["SSM_DB_CONNECTION_STRING"]]

_model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-6")

_client = Anthropic(api_key=_anthropic_api_key)
_chat_message_repository = DbChatMessageRepository(
    os.environ["SSM_DB_CONNECTION_STRING"]
)
_line_push_sender = LinePushSender(_line_channel_access_token)

_service = ProcessLineMessage(
    client=_client,
    model=_model,
    chat_message_repository=_chat_message_repository,
    line_push_sender=_line_push_sender,
    db_connection_string=_db_connection_string,
)


def handler(event: dict, context: object) -> None:
    for record in event["Records"]:
        body = json.loads(record["body"])
        _service.execute(chat_message_id=body["chat_message_id"])
```

**Step 2: Update the handler test**

Replace `src/spend_tracking/lambdas/line_message_worker_handler_test.py`:

```python
import json
import os
from unittest.mock import MagicMock, patch

_mock_boto3_client = MagicMock()
_mock_boto3_client.get_parameters.return_value = {
    "Parameters": [
        {"Name": "/test/anthropic-key", "Value": "fake-key"},
        {"Name": "/test/line-token", "Value": "fake-token"},
        {"Name": "/test/db", "Value": "postgresql://fake"},
    ]
}
_mock_boto3_client.get_parameter.return_value = {
    "Parameter": {"Value": "postgresql://fake"}
}

with (
    patch.dict(
        os.environ,
        {
            "SSM_ANTHROPIC_API_KEY": "/test/anthropic-key",
            "SSM_LINE_CHANNEL_ACCESS_TOKEN": "/test/line-token",
            "SSM_DB_CONNECTION_STRING": "/test/db",
            "ANTHROPIC_MODEL": "claude-haiku-4-5-20251001",
        },
    ),
    patch("boto3.client", return_value=_mock_boto3_client),
    patch("anthropic.Anthropic"),
):
    from spend_tracking.lambdas.line_message_worker_handler import handler


@patch("spend_tracking.lambdas.line_message_worker_handler._service")
def test_line_message_worker_handler_processes_each_record(mock_service):
    event = {
        "Records": [
            {"body": json.dumps({"chat_message_id": 42})},
            {"body": json.dumps({"chat_message_id": 99})},
        ]
    }
    handler(event, None)

    assert mock_service.execute.call_count == 2
    mock_service.execute.assert_any_call(chat_message_id=42)
    mock_service.execute.assert_any_call(chat_message_id=99)
```

**Step 3: Run tests**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/lambdas/line_message_worker_handler_test.py -v`
Expected: PASS.

**Step 4: Commit**

```bash
git add src/spend_tracking/lambdas/line_message_worker_handler.py \
        src/spend_tracking/lambdas/line_message_worker_handler_test.py
git commit -m "feat: update message worker handler to wire Anthropic agent dependencies"
```

---

### Task 9: Remove old `LineMessageRepository` and update `LineMessage` references

**Files:**
- Delete: `src/spend_tracking/interfaces/line_message_repository.py`
- Delete: `src/spend_tracking/adapters/line_message_repository_db.py`
- Delete: `src/spend_tracking/adapters/line_message_repository_db_test.py`
- Modify: `src/spend_tracking/domains/models.py` (verify `LineMessage` is removed from Task 3)
- Modify: `pyproject.toml` (update mypy overrides)

**Step 1: Delete old files**

```bash
rm src/spend_tracking/interfaces/line_message_repository.py
rm src/spend_tracking/adapters/line_message_repository_db.py
rm src/spend_tracking/adapters/line_message_repository_db_test.py
```

**Step 2: Update mypy overrides in `pyproject.toml`**

In the `[[tool.mypy.overrides]]` section, replace:
- `"spend_tracking.adapters.line_message_repository_db_test"` → `"spend_tracking.adapters.chat_message_repository_db_test"`
- Remove `"spend_tracking.lambdas.services.receive_line_webhook_test"` if already listed, then re-add it
- Add any new test modules

The final overrides list should be:

```toml
[[tool.mypy.overrides]]
module = [
    "spend_tracking.domains.models_test",
    "spend_tracking.adapters.notification_sender_line_test",
    "spend_tracking.adapters.chat_message_repository_db_test",
    "spend_tracking.lambdas.services.validate_and_enqueue_test",
    "spend_tracking.lambdas.services.process_email_test",
    "spend_tracking.lambdas.services.flex_message_test",
    "spend_tracking.lambdas.services.parsers.cathay_test",
    "spend_tracking.lambdas.services.receive_line_webhook_test",
    "spend_tracking.lambdas.services.process_line_message_test",
    "spend_tracking.lambdas.line_webhook_router_handler_test",
    "spend_tracking.lambdas.line_message_worker_handler_test",
]
disallow_untyped_defs = false
```

**Step 3: Run full test suite**

Run: `PYTHONPATH=src poetry run pytest src/ -v`
Expected: ALL tests pass. No imports of `LineMessage`, `LineMessageRepository`, or `DbLineMessageRepository` remain.

**Step 4: Run full CI**

Run: `make ci`
Expected: lint, format-check, typecheck, test, build all pass.

**Step 5: Commit**

```bash
git add -A
git commit -m "refactor: remove old LineMessageRepository, clean up mypy overrides"
```

---

### Task 10: Terraform infrastructure changes

**Files:**
- Modify: `infra/ssm.tf`
- Modify: `infra/lambda.tf`
- Modify: `infra/sqs.tf`
- Modify: `infra/iam.tf`

**Step 1: Add Anthropic API key SSM parameter**

In `infra/ssm.tf`, add:

```hcl
resource "aws_ssm_parameter" "anthropic_api_key" {
  name  = "/${var.project_name}/anthropic-api-key"
  type  = "SecureString"
  value = "placeholder"

  lifecycle {
    ignore_changes = [value]
  }
}
```

**Step 2: Update `line_message_worker` Lambda**

In `infra/lambda.tf`, update the `aws_lambda_function.line_message_worker` resource:
- `timeout = 600`
- `memory_size = 256`
- Add env vars: `SSM_ANTHROPIC_API_KEY`, `SSM_LINE_CHANNEL_ACCESS_TOKEN`, `ANTHROPIC_MODEL`

```hcl
resource "aws_lambda_function" "line_message_worker" {
  function_name = "${var.project_name}-line-message-worker"
  role          = aws_iam_role.lambda.arn
  handler       = "spend_tracking.lambdas.line_message_worker_handler.handler"
  runtime       = "python3.12"
  timeout       = 600
  memory_size   = 256
  filename      = data.archive_file.placeholder.output_path

  environment {
    variables = {
      SSM_DB_CONNECTION_STRING       = aws_ssm_parameter.db_connection_string.name
      SSM_ANTHROPIC_API_KEY          = aws_ssm_parameter.anthropic_api_key.name
      SSM_LINE_CHANNEL_ACCESS_TOKEN  = aws_ssm_parameter.line_channel_access_token.name
      ANTHROPIC_MODEL                = "claude-opus-4-6"
    }
  }

  logging_config {
    log_format            = "JSON"
    application_log_level = "INFO"
    system_log_level      = "WARN"
  }

  lifecycle {
    ignore_changes = [filename, source_code_hash]
  }
}
```

**Step 3: Update `line_webhook_router` Lambda — add `SSM_LINE_CHANNEL_ACCESS_TOKEN`**

In `infra/lambda.tf`, add env var to the `aws_lambda_function.line_webhook_router` resource:

```hcl
  environment {
    variables = {
      SSM_DB_CONNECTION_STRING        = aws_ssm_parameter.db_connection_string.name
      SSM_LINE_CHANNEL_SECRET         = aws_ssm_parameter.line_channel_secret.name
      SSM_LINE_CHANNEL_ACCESS_TOKEN   = aws_ssm_parameter.line_channel_access_token.name
      SQS_LINE_MESSAGE_QUEUE_URL      = aws_sqs_queue.line-message-processing.url
    }
  }
```

**Step 4: Update SQS visibility timeout**

In `infra/sqs.tf`, change `line-message-processing` queue:

```hcl
resource "aws_sqs_queue" "line-message-processing" {
  name                       = "${var.project_name}-line-message-processing"
  visibility_timeout_seconds = 660

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.line-message-dlq.arn
    maxReceiveCount     = 3
  })
}
```

**Step 5: Update IAM policy — add SSM read for anthropic-api-key**

In `infra/iam.tf`, add `aws_ssm_parameter.anthropic_api_key.arn` to the SSM resource list:

```hcl
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:GetParameters"]
        Resource = [
          aws_ssm_parameter.db_connection_string.arn,
          aws_ssm_parameter.line_channel_access_token.arn,
          aws_ssm_parameter.line_channel_secret.arn,
          aws_ssm_parameter.anthropic_api_key.arn
        ]
      },
```

Note: also added `ssm:GetParameters` (plural) since handlers now use `get_parameters` batch call.

**Step 6: Commit**

```bash
git add infra/ssm.tf infra/lambda.tf infra/sqs.tf infra/iam.tf
git commit -m "feat: update Terraform for agentic worker (timeout, SSM, SQS, IAM)"
```

---

### Task 11: Update Makefile build to include `anthropic` package

**Files:**
- Modify: `Makefile`

**Step 1: Add `anthropic` to the pip install in the build target**

The current `build` target only installs `psycopg2-binary`. Add `anthropic`:

```makefile
build:
	rm -rf $(BUILD_DIR)/lambda
	mkdir -p $(BUILD_DIR)/lambda
	pip install --no-deps -t $(BUILD_DIR)/lambda/ --quiet --platform manylinux2014_x86_64 --python-version 3.12 --only-binary=:all: psycopg2-binary
	pip install -t $(BUILD_DIR)/lambda/ --quiet anthropic
	cp -r src/spend_tracking $(BUILD_DIR)/lambda/
	cd $(BUILD_DIR)/lambda && zip -r ../lambda.zip . -x "*.pyc" "__pycache__/*" "*_test.py"
```

Note: `anthropic` is a pure-Python package (no platform-specific wheels needed), so it uses a simpler pip install. Also added `-x "*_test.py"` to exclude test files from the zip.

**Step 2: Verify build works**

Run: `make build`
Expected: `.build/lambda.zip` created successfully, contains `anthropic/` directory.

**Step 3: Commit**

```bash
git add Makefile
git commit -m "chore: update build to include anthropic package and exclude test files"
```

---

### Task 12: Final CI validation

**Step 1: Run full CI**

Run: `make ci`
Expected: ALL checks pass — lint, format-check, typecheck, test, build.

**Step 2: Verify no broken imports**

Run: `PYTHONPATH=src poetry run python -c "from spend_tracking.lambdas.services.process_line_message import ProcessLineMessage; print('OK')"`
Expected: `OK`

**Step 3: Check git status is clean**

Run: `git status`
Expected: clean working tree on `feat/line-agentic-worker` branch.
