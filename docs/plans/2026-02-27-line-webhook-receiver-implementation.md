# LINE Webhook Receiver Pipeline — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Receive LINE webhook messages, save to DB, forward to SQS for a worker Lambda (no-op for now).

**Architecture:** Function URL Lambda receives POST, verifies HMAC-SHA256 signature, saves parsed message to `line_messages` table, enqueues message ID to SQS. A second Lambda triggered by SQS does a no-op (log only). All four Lambdas share one IAM role and one zip artifact.

**Tech Stack:** Python 3.12, psycopg2, boto3, Alembic, Terraform, Lambda Function URL

---

### Task 1: Domain Model — `LineMessage` Dataclass

**Files:**
- Modify: `src/spend_tracking/domains/models.py`
- Test: `src/spend_tracking/domains/models_test.py`

**Step 1: Write the failing test**

Add to `src/spend_tracking/domains/models_test.py`:

```python
def test_line_message_creation():
    from datetime import UTC, datetime

    from spend_tracking.domains.models import LineMessage

    msg = LineMessage(
        id=None,
        line_user_id="U1234567890abcdef",
        message_type="text",
        message="Hello",
        reply_token="abc123",
        raw_event={"type": "message", "message": {"type": "text", "text": "Hello"}},
        timestamp=datetime(2026, 2, 27, 10, 0, 0, tzinfo=UTC),
        created_at=datetime(2026, 2, 27, 10, 0, 1, tzinfo=UTC),
    )
    assert msg.id is None
    assert msg.line_user_id == "U1234567890abcdef"
    assert msg.message_type == "text"
    assert msg.message == "Hello"
    assert msg.raw_event["type"] == "message"
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/domains/models_test.py::test_line_message_creation -v`
Expected: FAIL with `ImportError: cannot import name 'LineMessage'`

**Step 3: Write minimal implementation**

Add to `src/spend_tracking/domains/models.py`:

```python
@dataclass
class LineMessage:
    id: int | None
    line_user_id: str
    message_type: str
    message: str | None
    reply_token: str | None
    raw_event: dict
    timestamp: datetime
    created_at: datetime
```

**Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/domains/models_test.py::test_line_message_creation -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/spend_tracking/domains/models.py src/spend_tracking/domains/models_test.py
git commit -m "feat: add LineMessage domain model"
```

---

### Task 2: Interface — `LineMessageRepository` ABC

**Files:**
- Create: `src/spend_tracking/interfaces/line_message_repository.py`

**Step 1: Create the interface**

```python
from abc import ABC, abstractmethod

from spend_tracking.domains.models import LineMessage


class LineMessageRepository(ABC):
    @abstractmethod
    def save_line_message(self, message: LineMessage) -> None: ...
```

**Step 2: Run lint + typecheck**

Run: `PYTHONPATH=src poetry run mypy src/spend_tracking/interfaces/line_message_repository.py`
Expected: PASS with no errors

**Step 3: Commit**

```bash
git add src/spend_tracking/interfaces/line_message_repository.py
git commit -m "feat: add LineMessageRepository interface"
```

---

### Task 3: Interface — `LineMessageQueue` ABC

**Files:**
- Create: `src/spend_tracking/interfaces/line_message_queue.py`

**Step 1: Create the interface**

Follow the same pattern as `interfaces/email_queue.py`:

```python
from abc import ABC, abstractmethod


class LineMessageQueue(ABC):
    @abstractmethod
    def send_message(self, message: dict) -> None: ...
```

**Step 2: Run lint + typecheck**

Run: `PYTHONPATH=src poetry run mypy src/spend_tracking/interfaces/line_message_queue.py`
Expected: PASS

**Step 3: Commit**

```bash
git add src/spend_tracking/interfaces/line_message_queue.py
git commit -m "feat: add LineMessageQueue interface"
```

---

### Task 4: Adapter — `DbLineMessageRepository`

**Files:**
- Create: `src/spend_tracking/adapters/line_message_repository_db.py`
- Create: `src/spend_tracking/adapters/line_message_repository_db_test.py`
- Modify: `pyproject.toml` (add mypy override for test file)

**Step 1: Write the failing test**

Create `src/spend_tracking/adapters/line_message_repository_db_test.py`:

```python
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from spend_tracking.domains.models import LineMessage


def _make_line_message() -> LineMessage:
    return LineMessage(
        id=None,
        line_user_id="U1234567890abcdef",
        message_type="text",
        message="Hello",
        reply_token="reply-token-abc",
        raw_event={"type": "message", "message": {"type": "text", "text": "Hello"}},
        timestamp=datetime(2026, 2, 27, 10, 0, 0, tzinfo=UTC),
        created_at=datetime(2026, 2, 27, 10, 0, 1, tzinfo=UTC),
    )


@patch("spend_tracking.adapters.line_message_repository_db.boto3")
@patch("spend_tracking.adapters.line_message_repository_db.psycopg2")
def test_save_line_message_inserts_and_sets_id(mock_psycopg2, mock_boto3):
    from spend_tracking.adapters.line_message_repository_db import (
        DbLineMessageRepository,
    )

    mock_boto3.client.return_value.get_parameter.return_value = {
        "Parameter": {"Value": "postgresql://fake"}
    }
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = (42,)
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_psycopg2.connect.return_value = mock_conn

    repo = DbLineMessageRepository("ssm-param-name")
    msg = _make_line_message()
    repo.save_line_message(msg)

    mock_cur.execute.assert_called_once()
    sql = mock_cur.execute.call_args[0][0]
    assert "INSERT INTO line_messages" in sql
    assert "RETURNING id" in sql
    assert msg.id == 42
    mock_conn.commit.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/adapters/line_message_repository_db_test.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the adapter**

Create `src/spend_tracking/adapters/line_message_repository_db.py`:

```python
import json

import boto3
import psycopg2

from spend_tracking.domains.models import LineMessage
from spend_tracking.interfaces.line_message_repository import LineMessageRepository


class DbLineMessageRepository(LineMessageRepository):
    def __init__(self, ssm_parameter_name: str) -> None:
        ssm = boto3.client("ssm")
        response = ssm.get_parameter(
            Name=ssm_parameter_name,
            WithDecryption=True,
        )
        self._connection_string = response["Parameter"]["Value"]

    def save_line_message(self, message: LineMessage) -> None:
        with psycopg2.connect(self._connection_string) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO line_messages "
                "(line_user_id, message_type, message, reply_token, "
                "raw_event, timestamp, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "RETURNING id",
                (
                    message.line_user_id,
                    message.message_type,
                    message.message,
                    message.reply_token,
                    json.dumps(message.raw_event),
                    message.timestamp,
                    message.created_at,
                ),
            )
            row = cur.fetchone()
            assert row is not None
            message.id = row[0]
            conn.commit()
```

**Step 4: Add mypy override for test file**

In `pyproject.toml`, add `"spend_tracking.adapters.line_message_repository_db_test"` to the `[[tool.mypy.overrides]]` module list.

**Step 5: Run test to verify it passes**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/adapters/line_message_repository_db_test.py -v`
Expected: PASS

**Step 6: Run full CI check**

Run: `make ci`
Expected: All checks pass

**Step 7: Commit**

```bash
git add src/spend_tracking/adapters/line_message_repository_db.py \
        src/spend_tracking/adapters/line_message_repository_db_test.py \
        pyproject.toml
git commit -m "feat: add DbLineMessageRepository adapter"
```

---

### Task 5: Adapter — `SQSLineMessageQueue`

**Files:**
- Create: `src/spend_tracking/adapters/line_message_queue_sqs.py`

**Step 1: Create the adapter**

Follow the exact pattern of `adapters/email_queue_sqs.py`:

```python
import json

import boto3

from spend_tracking.interfaces.line_message_queue import LineMessageQueue


class SQSLineMessageQueue(LineMessageQueue):
    def __init__(self, queue_url: str) -> None:
        self._sqs = boto3.client("sqs")
        self._queue_url = queue_url

    def send_message(self, message: dict) -> None:
        self._sqs.send_message(
            QueueUrl=self._queue_url,
            MessageBody=json.dumps(message),
        )
```

**Step 2: Run lint + typecheck**

Run: `PYTHONPATH=src poetry run mypy src/spend_tracking/adapters/line_message_queue_sqs.py`
Expected: PASS

**Step 3: Commit**

```bash
git add src/spend_tracking/adapters/line_message_queue_sqs.py
git commit -m "feat: add SQSLineMessageQueue adapter"
```

---

### Task 6: Service — `ReceiveLineWebhook`

**Files:**
- Create: `src/spend_tracking/lambdas/services/receive_line_webhook.py`
- Create: `src/spend_tracking/lambdas/services/receive_line_webhook_test.py`
- Modify: `pyproject.toml` (add mypy override for test file)

**Step 1: Write the failing tests**

Create `src/spend_tracking/lambdas/services/receive_line_webhook_test.py`:

```python
import hashlib
import hmac
import json
from datetime import UTC, datetime
from unittest.mock import MagicMock


CHANNEL_SECRET = "test-channel-secret"


def _sign(body: str, secret: str = CHANNEL_SECRET) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256,
    ).digest().hex()


def _make_webhook_body(
    user_id: str = "U1234567890abcdef",
    message_text: str = "Hello",
    message_type: str = "text",
    reply_token: str = "reply-token-abc",
    timestamp: int = 1740646800000,
) -> str:
    return json.dumps({
        "events": [
            {
                "type": "message",
                "replyToken": reply_token,
                "source": {"type": "user", "userId": user_id},
                "timestamp": timestamp,
                "message": {"type": message_type, "text": message_text},
            }
        ]
    })


def test_valid_signature_saves_and_enqueues():
    from spend_tracking.lambdas.services.receive_line_webhook import (
        ReceiveLineWebhook,
    )

    repository = MagicMock()
    queue = MagicMock()

    # Make save_line_message set the id (simulating DB)
    def set_id(msg):
        msg.id = 42

    repository.save_line_message.side_effect = set_id

    body = _make_webhook_body()
    import base64
    signature = base64.b64encode(
        hmac.new(
            CHANNEL_SECRET.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    ).decode("utf-8")

    service = ReceiveLineWebhook(CHANNEL_SECRET, repository, queue)
    result = service.execute(body, signature)

    assert result["statusCode"] == 200
    repository.save_line_message.assert_called_once()
    saved = repository.save_line_message.call_args[0][0]
    assert saved.line_user_id == "U1234567890abcdef"
    assert saved.message_type == "text"
    assert saved.message == "Hello"
    assert saved.reply_token == "reply-token-abc"
    assert saved.raw_event["type"] == "message"

    queue.send_message.assert_called_once()
    enqueued = queue.send_message.call_args[0][0]
    assert enqueued["line_message_id"] == 42


def test_invalid_signature_returns_401():
    from spend_tracking.lambdas.services.receive_line_webhook import (
        ReceiveLineWebhook,
    )

    repository = MagicMock()
    queue = MagicMock()

    body = _make_webhook_body()
    bad_signature = "invalid-signature"

    service = ReceiveLineWebhook(CHANNEL_SECRET, repository, queue)
    result = service.execute(body, bad_signature)

    assert result["statusCode"] == 401
    repository.save_line_message.assert_not_called()
    queue.send_message.assert_not_called()


def test_non_message_events_are_skipped():
    from spend_tracking.lambdas.services.receive_line_webhook import (
        ReceiveLineWebhook,
    )

    repository = MagicMock()
    queue = MagicMock()

    body = json.dumps({
        "events": [
            {
                "type": "follow",
                "source": {"type": "user", "userId": "U123"},
                "timestamp": 1740646800000,
            }
        ]
    })
    import base64
    signature = base64.b64encode(
        hmac.new(
            CHANNEL_SECRET.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    ).decode("utf-8")

    service = ReceiveLineWebhook(CHANNEL_SECRET, repository, queue)
    result = service.execute(body, signature)

    assert result["statusCode"] == 200
    repository.save_line_message.assert_not_called()
    queue.send_message.assert_not_called()


def test_non_text_message_saves_with_null_message():
    from spend_tracking.lambdas.services.receive_line_webhook import (
        ReceiveLineWebhook,
    )

    repository = MagicMock()
    queue = MagicMock()

    def set_id(msg):
        msg.id = 99

    repository.save_line_message.side_effect = set_id

    body = json.dumps({
        "events": [
            {
                "type": "message",
                "replyToken": "token",
                "source": {"type": "user", "userId": "U123"},
                "timestamp": 1740646800000,
                "message": {"type": "sticker", "stickerId": "123", "packageId": "456"},
            }
        ]
    })
    import base64
    signature = base64.b64encode(
        hmac.new(
            CHANNEL_SECRET.encode("utf-8"),
            body.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    ).decode("utf-8")

    service = ReceiveLineWebhook(CHANNEL_SECRET, repository, queue)
    result = service.execute(body, signature)

    assert result["statusCode"] == 200
    saved = repository.save_line_message.call_args[0][0]
    assert saved.message_type == "sticker"
    assert saved.message is None
```

**Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/lambdas/services/receive_line_webhook_test.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the service implementation**

Create `src/spend_tracking/lambdas/services/receive_line_webhook.py`:

```python
import base64
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime

from spend_tracking.domains.models import LineMessage
from spend_tracking.interfaces.line_message_queue import LineMessageQueue
from spend_tracking.interfaces.line_message_repository import LineMessageRepository

logger = logging.getLogger(__name__)


class ReceiveLineWebhook:
    def __init__(
        self,
        channel_secret: str,
        repository: LineMessageRepository,
        queue: LineMessageQueue,
    ) -> None:
        self._channel_secret = channel_secret
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
                logger.info("Skipping non-message event", extra={"type": event.get("type")})
                continue

            message_obj = event.get("message", {})
            message_type = message_obj.get("type", "unknown")
            message_text = message_obj.get("text") if message_type == "text" else None

            line_message = LineMessage(
                id=None,
                line_user_id=event["source"]["userId"],
                message_type=message_type,
                message=message_text,
                reply_token=event.get("replyToken"),
                raw_event=event,
                timestamp=datetime.fromtimestamp(
                    event["timestamp"] / 1000, tz=UTC
                ),
                created_at=datetime.now(UTC),
            )

            self._repository.save_line_message(line_message)
            logger.info(
                "Saved LINE message",
                extra={
                    "line_message_id": line_message.id,
                    "line_user_id": line_message.line_user_id,
                    "message_type": message_type,
                },
            )

            self._queue.send_message({"line_message_id": line_message.id})

        return {"statusCode": 200, "body": "OK"}

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

**Step 4: Add mypy override for test file**

In `pyproject.toml`, add `"spend_tracking.lambdas.services.receive_line_webhook_test"` to the `[[tool.mypy.overrides]]` module list.

**Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/lambdas/services/receive_line_webhook_test.py -v`
Expected: All 4 tests PASS

**Step 6: Run full CI check**

Run: `make ci`
Expected: All checks pass

**Step 7: Commit**

```bash
git add src/spend_tracking/lambdas/services/receive_line_webhook.py \
        src/spend_tracking/lambdas/services/receive_line_webhook_test.py \
        pyproject.toml
git commit -m "feat: add ReceiveLineWebhook service with signature verification"
```

---

### Task 7: Service — `ProcessLineMessage` (No-Op)

**Files:**
- Create: `src/spend_tracking/lambdas/services/process_line_message.py`
- Create: `src/spend_tracking/lambdas/services/process_line_message_test.py`
- Modify: `pyproject.toml` (add mypy override for test file)

**Step 1: Write the failing test**

Create `src/spend_tracking/lambdas/services/process_line_message_test.py`:

```python
def test_execute_is_noop():
    from spend_tracking.lambdas.services.process_line_message import (
        ProcessLineMessage,
    )

    service = ProcessLineMessage()
    # Should not raise
    service.execute(line_message_id=42)
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/lambdas/services/process_line_message_test.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write the no-op service**

Create `src/spend_tracking/lambdas/services/process_line_message.py`:

```python
import logging

logger = logging.getLogger(__name__)


class ProcessLineMessage:
    def execute(self, line_message_id: int) -> None:
        logger.info(
            "Processing LINE message (no-op)",
            extra={"line_message_id": line_message_id},
        )
```

**Step 4: Add mypy override for test file**

In `pyproject.toml`, add `"spend_tracking.lambdas.services.process_line_message_test"` to the `[[tool.mypy.overrides]]` module list.

**Step 5: Run test to verify it passes**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/lambdas/services/process_line_message_test.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/spend_tracking/lambdas/services/process_line_message.py \
        src/spend_tracking/lambdas/services/process_line_message_test.py \
        pyproject.toml
git commit -m "feat: add ProcessLineMessage service (no-op)"
```

---

### Task 8: Handler Entry Points

**Files:**
- Modify: `src/spend_tracking/lambdas/handler.py`

**Step 1: Add the two new handler entry points**

Add to `handler.py`:

1. Wire up dependencies at module level (guarded by env var checks so existing handlers don't break when env vars are absent):
   - `SQSLineMessageQueue` from `SQS_LINE_MESSAGE_QUEUE_URL`
   - `DbLineMessageRepository` from `SSM_DB_CONNECTION_STRING`
   - `channel_secret` from `SSM_LINE_CHANNEL_SECRET` (read via SSM, same pattern as LINE token)
   - `ReceiveLineWebhook` service
   - `ProcessLineMessage` service

2. `line_webhook_router_handler(event, context)`:
   - Extract `body` from event (Function URL sends `event["body"]`)
   - Extract `X-Line-Signature` from `event["headers"]`
   - Call `_receive_line_webhook_service.execute(body, signature)`
   - Return the result dict (which has `statusCode` and `body`)

3. `line_message_worker_handler(event, context)`:
   - Loop through `event["Records"]`
   - Parse `json.loads(record["body"])` to get `line_message_id`
   - Call `_process_line_message_service.execute(line_message_id)`

**Step 2: Run full CI check**

Run: `make ci`
Expected: All checks pass

**Step 3: Commit**

```bash
git add src/spend_tracking/lambdas/handler.py
git commit -m "feat: add LINE webhook router and message worker handler entry points"
```

---

### Task 9: Handler Tests

**Files:**
- Create: `src/spend_tracking/lambdas/handler_test.py`
- Modify: `pyproject.toml` (add mypy override for test file)

**Step 1: Write the failing tests**

Create `src/spend_tracking/lambdas/handler_test.py`:

```python
import json
from unittest.mock import MagicMock, patch


@patch("spend_tracking.lambdas.handler._receive_line_webhook_service")
def test_line_webhook_router_handler_delegates_to_service(mock_service):
    from spend_tracking.lambdas.handler import line_webhook_router_handler

    mock_service.execute.return_value = {"statusCode": 200, "body": "OK"}

    event = {
        "headers": {"x-line-signature": "test-signature"},
        "body": '{"events": []}',
    }
    result = line_webhook_router_handler(event, None)

    assert result["statusCode"] == 200
    mock_service.execute.assert_called_once_with('{"events": []}', "test-signature")


@patch("spend_tracking.lambdas.handler._receive_line_webhook_service")
def test_line_webhook_router_handler_returns_401_on_bad_signature(mock_service):
    from spend_tracking.lambdas.handler import line_webhook_router_handler

    mock_service.execute.return_value = {"statusCode": 401, "body": "Invalid signature"}

    event = {
        "headers": {"x-line-signature": "bad-sig"},
        "body": "{}",
    }
    result = line_webhook_router_handler(event, None)

    assert result["statusCode"] == 401


@patch("spend_tracking.lambdas.handler._process_line_message_service")
def test_line_message_worker_handler_processes_each_record(mock_service):
    from spend_tracking.lambdas.handler import line_message_worker_handler

    event = {
        "Records": [
            {"body": json.dumps({"line_message_id": 42})},
            {"body": json.dumps({"line_message_id": 99})},
        ]
    }
    line_message_worker_handler(event, None)

    assert mock_service.execute.call_count == 2
    mock_service.execute.assert_any_call(line_message_id=42)
    mock_service.execute.assert_any_call(line_message_id=99)
```

**Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/lambdas/handler_test.py -v`
Expected: FAIL (handler entry points or module-level wiring not yet compatible, or `_receive_line_webhook_service` not patchable)

Note: These tests may already pass if Task 8 was implemented correctly. That's fine — the tests still validate the handler behavior.

**Step 3: Add mypy override for test file**

In `pyproject.toml`, add `"spend_tracking.lambdas.handler_test"` to the `[[tool.mypy.overrides]]` module list.

**Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/lambdas/handler_test.py -v`
Expected: All 3 tests PASS

**Step 5: Run full CI**

Run: `make ci`
Expected: All checks pass

**Step 6: Commit**

```bash
git add src/spend_tracking/lambdas/handler_test.py pyproject.toml
git commit -m "test: add handler tests for LINE webhook router and message worker"
```

---

### Task 10: Database Migration

**Files:**
- Create: `migrations/versions/005_add_line_messages.py`

**Step 1: Create migration**

Run: `poetry run alembic revision -m "add line_messages"`

This creates a file in `migrations/versions/`. Edit it:

```python
revision: str = '005'
down_revision = '004'

def upgrade() -> None:
    op.execute("""
        CREATE TABLE line_messages (
            id            BIGSERIAL PRIMARY KEY,
            line_user_id  TEXT NOT NULL,
            message_type  TEXT NOT NULL,
            message       TEXT,
            reply_token   TEXT,
            raw_event     JSONB NOT NULL,
            timestamp     TIMESTAMPTZ NOT NULL,
            created_at    TIMESTAMPTZ DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_line_messages_user_id ON line_messages(line_user_id)")
    op.execute("CREATE INDEX idx_line_messages_timestamp ON line_messages(timestamp DESC)")

def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS line_messages")
```

**Step 2: Commit**

```bash
git add migrations/versions/005_add_line_messages.py
git commit -m "feat: add line_messages table migration"
```

---

### Task 11: Makefile — Simplify Build, Rename Deploys

**Files:**
- Modify: `Makefile`

**Step 1: Replace build and deploy targets**

Replace the entire Makefile build/deploy section with:

```makefile
.PHONY: build deploy deploy-email-router deploy-email-worker deploy-line-webhook-router deploy-line-message-worker clean test migrate migrate-new lint lint-fix format-check format typecheck ci

ROUTER_FUNCTION := spend-tracking-router
WORKER_FUNCTION := spend-tracking-worker
LINE_WEBHOOK_ROUTER_FUNCTION := spend-tracking-line-webhook-router
LINE_MESSAGE_WORKER_FUNCTION := spend-tracking-line-message-worker
BUILD_DIR := .build
AWS_REGION := us-east-1

build:
	rm -rf $(BUILD_DIR)/lambda
	mkdir -p $(BUILD_DIR)/lambda
	pip install --no-deps -t $(BUILD_DIR)/lambda/ --quiet --platform manylinux2014_x86_64 --python-version 3.12 --only-binary=:all: psycopg2-binary
	cp -r src/spend_tracking $(BUILD_DIR)/lambda/
	cd $(BUILD_DIR)/lambda && zip -r ../lambda.zip . -x "*.pyc" "__pycache__/*"

deploy-email-router: build
	aws lambda update-function-code \
		--function-name $(ROUTER_FUNCTION) \
		--zip-file fileb://$(BUILD_DIR)/lambda.zip \
		--region $(AWS_REGION)

deploy-email-worker: build
	aws lambda update-function-code \
		--function-name $(WORKER_FUNCTION) \
		--zip-file fileb://$(BUILD_DIR)/lambda.zip \
		--region $(AWS_REGION)

deploy-line-webhook-router: build
	aws lambda update-function-code \
		--function-name $(LINE_WEBHOOK_ROUTER_FUNCTION) \
		--zip-file fileb://$(BUILD_DIR)/lambda.zip \
		--region $(AWS_REGION)

deploy-line-message-worker: build
	aws lambda update-function-code \
		--function-name $(LINE_MESSAGE_WORKER_FUNCTION) \
		--zip-file fileb://$(BUILD_DIR)/lambda.zip \
		--region $(AWS_REGION)

deploy: deploy-email-router deploy-email-worker deploy-line-webhook-router deploy-line-message-worker
```

Keep all other targets (clean, test, migrate, lint, etc.) unchanged.

**Step 2: Verify build works**

Run: `make build`
Expected: Creates `.build/lambda.zip` containing `spend_tracking/` and `psycopg2/`

**Step 3: Run full CI**

Run: `make ci`
Expected: All checks pass (ci target uses `build`, which now produces the single zip)

**Step 4: Commit**

```bash
git add Makefile
git commit -m "refactor: simplify Makefile to single build target, rename deploy targets"
```

---

### Task 12: Terraform — Shared IAM Role

**Files:**
- Modify: `infra/iam.tf`

**Step 1: Replace two roles with one shared role**

Replace all contents of `infra/iam.tf` with:

```hcl
resource "aws_iam_role" "lambda" {
  name = "${var.project_name}-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action    = "sts:AssumeRole"
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
      }
    ]
  })
}

resource "aws_iam_role_policy" "lambda" {
  name = "${var.project_name}-lambda"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.raw_emails.arn}/*"
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:SendMessage",
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = [
          aws_sqs_queue.email-processing.arn,
          aws_sqs_queue.line-message-processing.arn
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = [
          aws_ssm_parameter.db_connection_string.arn,
          aws_ssm_parameter.line_channel_access_token.arn,
          aws_ssm_parameter.line_channel_secret.arn
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      }
    ]
  })
}
```

**Step 2: Update `infra/lambda.tf`**

Change all `role = aws_iam_role.router.arn` and `role = aws_iam_role.worker.arn` references to `role = aws_iam_role.lambda.arn`.

**Step 3: Commit**

```bash
git add infra/iam.tf infra/lambda.tf
git commit -m "refactor: merge IAM roles into single shared lambda role"
```

---

### Task 13: Terraform — SQS, SSM, Lambda, Function URL

**Files:**
- Modify: `infra/sqs.tf`
- Modify: `infra/ssm.tf`
- Modify: `infra/lambda.tf`

**Step 1: Add SQS queue + DLQ to `infra/sqs.tf`**

Append to `infra/sqs.tf`:

```hcl
resource "aws_sqs_queue" "line-message-dlq" {
  name = "${var.project_name}-line-message-dlq"
}

resource "aws_sqs_queue" "line-message-processing" {
  name                       = "${var.project_name}-line-message-processing"
  visibility_timeout_seconds = 300

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.line-message-dlq.arn
    maxReceiveCount     = 3
  })
}
```

**Step 2: Add SSM parameter to `infra/ssm.tf`**

Append to `infra/ssm.tf`:

```hcl
resource "aws_ssm_parameter" "line_channel_secret" {
  name  = "/${var.project_name}/line-channel-secret"
  type  = "SecureString"
  value = "placeholder"

  lifecycle {
    ignore_changes = [value]
  }
}
```

**Step 3: Add Lambda functions + Function URL to `infra/lambda.tf`**

Append to `infra/lambda.tf`:

```hcl
resource "aws_lambda_function" "line_webhook_router" {
  function_name = "${var.project_name}-line-webhook-router"
  role          = aws_iam_role.lambda.arn
  handler       = "spend_tracking.lambdas.handler.line_webhook_router_handler"
  runtime       = "python3.12"
  timeout       = 30
  memory_size   = 128
  filename      = data.archive_file.placeholder.output_path

  environment {
    variables = {
      SSM_DB_CONNECTION_STRING   = aws_ssm_parameter.db_connection_string.name
      SSM_LINE_CHANNEL_SECRET    = aws_ssm_parameter.line_channel_secret.name
      SQS_LINE_MESSAGE_QUEUE_URL = aws_sqs_queue.line-message-processing.url
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

resource "aws_lambda_function_url" "line_webhook_router" {
  function_name      = aws_lambda_function.line_webhook_router.function_name
  authorization_type = "NONE"
}

resource "aws_lambda_function" "line_message_worker" {
  function_name = "${var.project_name}-line-message-worker"
  role          = aws_iam_role.lambda.arn
  handler       = "spend_tracking.lambdas.handler.line_message_worker_handler"
  runtime       = "python3.12"
  timeout       = 60
  memory_size   = 128
  filename      = data.archive_file.placeholder.output_path

  environment {
    variables = {
      SSM_DB_CONNECTION_STRING = aws_ssm_parameter.db_connection_string.name
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

resource "aws_lambda_event_source_mapping" "line_message_worker_sqs" {
  event_source_arn = aws_sqs_queue.line-message-processing.arn
  function_name    = aws_lambda_function.line_message_worker.arn
  batch_size       = 1
}
```

**Step 4: Add Function URL to `infra/outputs.tf`**

Append:

```hcl
output "line_webhook_url" {
  value = aws_lambda_function_url.line_webhook_router.function_url
}
```

**Step 5: Commit**

```bash
git add infra/sqs.tf infra/ssm.tf infra/lambda.tf infra/outputs.tf
git commit -m "feat: add LINE webhook router and message worker infrastructure"
```

---

### Task 14: CD Pipeline Update

**Files:**
- Modify: `.github/workflows/cd.yml`

**Step 1: Update deploy step**

The `make deploy` target already deploys all four Lambdas after the Makefile changes in Task 10. No changes needed to the CD workflow itself — it already runs `make deploy`.

Verify by reading the workflow: `make deploy` calls `deploy-email-router deploy-email-worker deploy-line-webhook-router deploy-line-message-worker`.

**Step 2: Commit (only if changes were needed)**

No commit needed for this task.

---

### Task 15: Final CI Verification

**Step 1: Run full CI**

Run: `make ci`
Expected: All lint, format, typecheck, test, and build checks pass.

**Step 2: Review all commits on the branch**

Run: `git log --oneline master..HEAD`
Expected: ~10 commits covering model, interfaces, adapters, services, handlers, migration, Makefile, and Terraform.
