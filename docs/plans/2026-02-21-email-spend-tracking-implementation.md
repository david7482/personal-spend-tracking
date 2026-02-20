# Email Spend Tracking Service — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an email-based spend tracking pipeline that receives bank emails via SES, stores raw MIME in S3, and writes structured data to Neon PostgreSQL.

**Architecture:** Clean architecture with domain models, interfaces (ABCs), adapters (S3/SQS/DB), and services. Two Lambda functions (Router + Worker) connected by SQS. All AWS infra managed by Terraform.

**Tech Stack:** Python 3.12, Poetry, Terraform, AWS (SES, S3, Lambda, SQS, SSM), Neon PostgreSQL, psycopg2-binary, pytest

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: all `__init__.py` files for package structure
- Create: `src/spend_tracking/__init__.py`
- Create: `src/spend_tracking/router/__init__.py`
- Create: `src/spend_tracking/router/services/__init__.py`
- Create: `src/spend_tracking/worker/__init__.py`
- Create: `src/spend_tracking/worker/services/__init__.py`
- Create: `src/spend_tracking/shared/__init__.py`
- Create: `src/spend_tracking/shared/domain/__init__.py`
- Create: `src/spend_tracking/shared/interfaces/__init__.py`
- Create: `src/spend_tracking/shared/adapters/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/router/__init__.py`
- Create: `tests/worker/__init__.py`
- Create: `tests/shared/__init__.py`

**Step 1: Create pyproject.toml**

```toml
[tool.poetry]
name = "spend-tracking"
version = "0.1.0"
description = "Email-based personal spend tracking service"
authors = []
packages = [{include = "spend_tracking", from = "src"}]

[tool.poetry.dependencies]
python = "^3.12"
boto3 = "^1.35"
psycopg2-binary = "^2.9"

[tool.poetry.group.dev.dependencies]
pytest = "^8.0"

[tool.pytest.ini_options]
testpaths = ["tests"]

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

**Step 2: Create .gitignore**

```
__pycache__/
*.pyc
.build/
*.egg-info/
dist/
.idea/
.venv/
*.zip
infra/.terraform/
infra/*.tfstate*
infra/placeholder.zip
```

**Step 3: Create all directory structure and __init__.py files**

Create every directory and empty `__init__.py` file listed above.

**Step 4: Install dependencies**

Run: `poetry install`
Expected: dependencies resolve and install successfully

**Step 5: Verify pytest runs**

Run: `poetry run pytest --co`
Expected: "no tests ran" or similar (no test files yet with test functions)

**Step 6: Commit**

```bash
git add pyproject.toml poetry.lock .gitignore src/ tests/
git commit -m "scaffold: project structure with Poetry and package layout"
```

---

### Task 2: Domain Models (TDD)

**Files:**
- Test: `tests/shared/test_models.py`
- Create: `src/spend_tracking/shared/domain/models.py`

**Step 1: Write the failing test**

```python
# tests/shared/test_models.py
from datetime import datetime, timezone
from uuid import uuid4


def test_registered_address_creation():
    from spend_tracking.shared.domain.models import RegisteredAddress

    addr = RegisteredAddress(
        address="bank-abc123@mail.david74.dev",
        prefix="bank",
        label="Test Bank",
        is_active=True,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert addr.address == "bank-abc123@mail.david74.dev"
    assert addr.prefix == "bank"
    assert addr.label == "Test Bank"
    assert addr.is_active is True


def test_registered_address_optional_label():
    from spend_tracking.shared.domain.models import RegisteredAddress

    addr = RegisteredAddress(
        address="card-xyz@mail.david74.dev",
        prefix="card",
        label=None,
        is_active=True,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert addr.label is None


def test_email_creation():
    from spend_tracking.shared.domain.models import Email

    email_id = uuid4()
    email = Email(
        id=email_id,
        address="bank-abc123@mail.david74.dev",
        sender="noreply@bank.com",
        subject="Your statement",
        body_html="<p>Statement</p>",
        body_text="Statement",
        raw_s3_key="abc123",
        received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        parsed_data=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert email.id == email_id
    assert email.sender == "noreply@bank.com"
    assert email.parsed_data is None


def test_email_with_parsed_data():
    from spend_tracking.shared.domain.models import Email

    parsed = {"type": "credit_card_statement", "amount": 12345}
    email = Email(
        id=uuid4(),
        address="bank-abc123@mail.david74.dev",
        sender="noreply@bank.com",
        subject="Statement",
        body_html=None,
        body_text="text",
        raw_s3_key="key1",
        received_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        parsed_data=parsed,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert email.parsed_data["amount"] == 12345
```

**Step 2: Run test to verify it fails**

Run: `poetry run pytest tests/shared/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError`

**Step 3: Write minimal implementation**

```python
# src/spend_tracking/shared/domain/models.py
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class RegisteredAddress:
    address: str
    prefix: str
    label: str | None
    is_active: bool
    created_at: datetime


@dataclass
class Email:
    id: UUID
    address: str
    sender: str
    subject: str | None
    body_html: str | None
    body_text: str | None
    raw_s3_key: str
    received_at: datetime
    parsed_data: dict | None
    created_at: datetime
```

**Step 4: Run test to verify it passes**

Run: `poetry run pytest tests/shared/test_models.py -v`
Expected: 4 PASSED

**Step 5: Commit**

```bash
git add src/spend_tracking/shared/domain/models.py tests/shared/test_models.py
git commit -m "feat: add domain models for RegisteredAddress and Email"
```

---

### Task 3: Interfaces

**Files:**
- Create: `src/spend_tracking/shared/interfaces/email_repository.py`
- Create: `src/spend_tracking/shared/interfaces/email_storage.py`
- Create: `src/spend_tracking/shared/interfaces/email_queue.py`

No tests needed — these are abstract base classes.

**Step 1: Create EmailRepository interface**

```python
# src/spend_tracking/shared/interfaces/email_repository.py
from abc import ABC, abstractmethod

from spend_tracking.shared.domain.models import Email, RegisteredAddress


class EmailRepository(ABC):
    @abstractmethod
    def get_registered_address(self, address: str) -> RegisteredAddress | None:
        ...

    @abstractmethod
    def save_email(self, email: Email) -> None:
        ...
```

**Step 2: Create EmailStorage interface**

```python
# src/spend_tracking/shared/interfaces/email_storage.py
from abc import ABC, abstractmethod


class EmailStorage(ABC):
    @abstractmethod
    def get_email_headers(self, s3_key: str) -> bytes:
        ...

    @abstractmethod
    def get_email_raw(self, s3_key: str) -> bytes:
        ...
```

**Step 3: Create EmailQueue interface**

```python
# src/spend_tracking/shared/interfaces/email_queue.py
from abc import ABC, abstractmethod


class EmailQueue(ABC):
    @abstractmethod
    def send_message(self, message: dict) -> None:
        ...
```

**Step 4: Verify existing tests still pass**

Run: `poetry run pytest -v`
Expected: 4 PASSED (domain model tests unchanged)

**Step 5: Commit**

```bash
git add src/spend_tracking/shared/interfaces/
git commit -m "feat: add interfaces for EmailRepository, EmailStorage, EmailQueue"
```

---

### Task 4: Router Service — ValidateAndEnqueue (TDD)

**Files:**
- Test: `tests/router/test_validate_and_enqueue.py`
- Create: `src/spend_tracking/router/services/validate_and_enqueue.py`

**Step 1: Write the failing tests**

```python
# tests/router/test_validate_and_enqueue.py
from datetime import datetime, timezone
from unittest.mock import MagicMock


def _make_raw_headers(to_address: str, from_address: str = "sender@example.com") -> bytes:
    return (
        f"From: {from_address}\r\n"
        f"To: {to_address}\r\n"
        f"Subject: Test\r\n"
        f"Date: Sat, 21 Feb 2026 10:00:00 +0000\r\n"
        f"\r\n"
    ).encode()


def test_enqueues_for_active_registered_address():
    from spend_tracking.router.services.validate_and_enqueue import ValidateAndEnqueue
    from spend_tracking.shared.domain.models import RegisteredAddress

    storage = MagicMock()
    repository = MagicMock()
    queue = MagicMock()

    to_addr = "bank-abc123@mail.david74.dev"
    storage.get_email_headers.return_value = _make_raw_headers(to_addr)
    repository.get_registered_address.return_value = RegisteredAddress(
        address=to_addr,
        prefix="bank",
        label="Test",
        is_active=True,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    service = ValidateAndEnqueue(storage, repository, queue)
    result = service.execute("some-s3-key")

    assert result is True
    queue.send_message.assert_called_once()
    msg = queue.send_message.call_args[0][0]
    assert msg["s3_key"] == "some-s3-key"
    assert msg["address"] == to_addr
    assert msg["sender"] == "sender@example.com"


def test_skips_unregistered_address():
    from spend_tracking.router.services.validate_and_enqueue import ValidateAndEnqueue

    storage = MagicMock()
    repository = MagicMock()
    queue = MagicMock()

    storage.get_email_headers.return_value = _make_raw_headers("unknown@mail.david74.dev")
    repository.get_registered_address.return_value = None

    service = ValidateAndEnqueue(storage, repository, queue)
    result = service.execute("some-s3-key")

    assert result is False
    queue.send_message.assert_not_called()


def test_skips_inactive_address():
    from spend_tracking.router.services.validate_and_enqueue import ValidateAndEnqueue
    from spend_tracking.shared.domain.models import RegisteredAddress

    storage = MagicMock()
    repository = MagicMock()
    queue = MagicMock()

    to_addr = "bank-abc123@mail.david74.dev"
    storage.get_email_headers.return_value = _make_raw_headers(to_addr)
    repository.get_registered_address.return_value = RegisteredAddress(
        address=to_addr,
        prefix="bank",
        label="Test",
        is_active=False,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    service = ValidateAndEnqueue(storage, repository, queue)
    result = service.execute("some-s3-key")

    assert result is False
    queue.send_message.assert_not_called()


def test_checks_delivered_to_header():
    from spend_tracking.router.services.validate_and_enqueue import ValidateAndEnqueue
    from spend_tracking.shared.domain.models import RegisteredAddress

    storage = MagicMock()
    repository = MagicMock()
    queue = MagicMock()

    target_addr = "bank-abc123@mail.david74.dev"
    raw = (
        "From: sender@example.com\r\n"
        "To: someother@example.com\r\n"
        f"Delivered-To: {target_addr}\r\n"
        "Subject: Test\r\n"
        "Date: Sat, 21 Feb 2026 10:00:00 +0000\r\n"
        "\r\n"
    ).encode()
    storage.get_email_headers.return_value = raw

    def lookup(addr):
        if addr == target_addr:
            return RegisteredAddress(
                address=target_addr,
                prefix="bank",
                label="Test",
                is_active=True,
                created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            )
        return None

    repository.get_registered_address.side_effect = lookup

    service = ValidateAndEnqueue(storage, repository, queue)
    result = service.execute("s3-key")

    assert result is True
    msg = queue.send_message.call_args[0][0]
    assert msg["address"] == target_addr
```

**Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/router/test_validate_and_enqueue.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
# src/spend_tracking/router/services/validate_and_enqueue.py
import logging
from email.parser import BytesHeaderParser
from email.utils import getaddresses, parsedate_to_datetime

from spend_tracking.shared.interfaces.email_queue import EmailQueue
from spend_tracking.shared.interfaces.email_repository import EmailRepository
from spend_tracking.shared.interfaces.email_storage import EmailStorage

logger = logging.getLogger(__name__)


class ValidateAndEnqueue:
    def __init__(
        self,
        storage: EmailStorage,
        repository: EmailRepository,
        queue: EmailQueue,
    ) -> None:
        self._storage = storage
        self._repository = repository
        self._queue = queue

    def execute(self, s3_key: str) -> bool:
        raw_headers = self._storage.get_email_headers(s3_key)

        parser = BytesHeaderParser()
        headers = parser.parsebytes(raw_headers)

        to_values = headers.get_all("To", [])
        delivered_to = headers.get_all("Delivered-To", [])
        all_recipients = getaddresses(to_values + delivered_to)

        for _, addr in all_recipients:
            registered = self._repository.get_registered_address(addr)
            if registered and registered.is_active:
                sender_values = headers.get_all("From", [])
                senders = getaddresses(sender_values)
                sender = senders[0][1] if senders else "unknown"

                date_str = headers.get("Date", "")
                try:
                    received_at = parsedate_to_datetime(date_str).isoformat()
                except Exception:
                    from datetime import datetime, timezone
                    received_at = datetime.now(timezone.utc).isoformat()

                self._queue.send_message(
                    {
                        "s3_key": s3_key,
                        "address": addr,
                        "sender": sender,
                        "received_at": received_at,
                    }
                )
                logger.info("Enqueued email for %s from %s", addr, sender)
                return True

        logger.warning("No registered address found for email at %s", s3_key)
        return False
```

**Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/router/test_validate_and_enqueue.py -v`
Expected: 4 PASSED

**Step 5: Run all tests**

Run: `poetry run pytest -v`
Expected: 8 PASSED (4 model + 4 router)

**Step 6: Commit**

```bash
git add tests/router/test_validate_and_enqueue.py src/spend_tracking/router/services/validate_and_enqueue.py
git commit -m "feat: add ValidateAndEnqueue router service with TDD"
```

---

### Task 5: Worker Service — ProcessEmail (TDD)

**Files:**
- Test: `tests/worker/test_process_email.py`
- Create: `src/spend_tracking/worker/services/process_email.py`

**Step 1: Write the failing tests**

```python
# tests/worker/test_process_email.py
from unittest.mock import MagicMock


def _make_multipart_email(
    from_addr: str = "sender@example.com",
    subject: str = "Test Subject",
    body_text: str = "Plain text body",
    body_html: str = "<p>HTML body</p>",
) -> bytes:
    boundary = "boundary123"
    return (
        f"From: {from_addr}\r\n"
        f"To: bank-abc@mail.david74.dev\r\n"
        f"Subject: {subject}\r\n"
        f"MIME-Version: 1.0\r\n"
        f'Content-Type: multipart/alternative; boundary="{boundary}"\r\n'
        f"\r\n"
        f"--{boundary}\r\n"
        f'Content-Type: text/plain; charset="utf-8"\r\n'
        f"\r\n"
        f"{body_text}\r\n"
        f"--{boundary}\r\n"
        f'Content-Type: text/html; charset="utf-8"\r\n'
        f"\r\n"
        f"{body_html}\r\n"
        f"--{boundary}--\r\n"
    ).encode()


def _make_plain_email(
    from_addr: str = "sender@example.com",
    subject: str = "Plain Email",
    body: str = "Just plain text",
) -> bytes:
    return (
        f"From: {from_addr}\r\n"
        f"To: bank-abc@mail.david74.dev\r\n"
        f"Subject: {subject}\r\n"
        f"Content-Type: text/plain\r\n"
        f"\r\n"
        f"{body}\r\n"
    ).encode()


def test_processes_multipart_email():
    from spend_tracking.worker.services.process_email import ProcessEmail

    storage = MagicMock()
    repository = MagicMock()

    storage.get_email_raw.return_value = _make_multipart_email()

    service = ProcessEmail(storage, repository)
    service.execute(
        s3_key="some-key",
        address="bank-abc@mail.david74.dev",
        sender="sender@example.com",
        received_at="2026-02-21T10:00:00+00:00",
    )

    repository.save_email.assert_called_once()
    saved = repository.save_email.call_args[0][0]
    assert saved.subject == "Test Subject"
    assert saved.body_text == "Plain text body\r\n"
    assert saved.body_html == "<p>HTML body</p>\r\n"
    assert saved.raw_s3_key == "some-key"
    assert saved.address == "bank-abc@mail.david74.dev"
    assert saved.parsed_data is None


def test_processes_plain_text_only_email():
    from spend_tracking.worker.services.process_email import ProcessEmail

    storage = MagicMock()
    repository = MagicMock()

    storage.get_email_raw.return_value = _make_plain_email()

    service = ProcessEmail(storage, repository)
    service.execute(
        s3_key="key-2",
        address="bank-abc@mail.david74.dev",
        sender="sender@example.com",
        received_at="2026-02-21T10:00:00+00:00",
    )

    saved = repository.save_email.call_args[0][0]
    assert saved.body_text == "Just plain text\r\n"
    assert saved.body_html is None
    assert saved.subject == "Plain Email"


def test_email_has_correct_metadata():
    from spend_tracking.worker.services.process_email import ProcessEmail

    storage = MagicMock()
    repository = MagicMock()

    storage.get_email_raw.return_value = _make_plain_email()

    service = ProcessEmail(storage, repository)
    service.execute(
        s3_key="key-3",
        address="card-xyz@mail.david74.dev",
        sender="bank@example.com",
        received_at="2026-02-21T10:00:00+00:00",
    )

    saved = repository.save_email.call_args[0][0]
    assert saved.sender == "bank@example.com"
    assert saved.address == "card-xyz@mail.david74.dev"
    assert saved.id is not None
    assert saved.created_at is not None
```

**Step 2: Run tests to verify they fail**

Run: `poetry run pytest tests/worker/test_process_email.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
# src/spend_tracking/worker/services/process_email.py
import logging
from datetime import datetime, timezone
from email import message_from_bytes
from email.message import Message
from uuid import uuid4

from spend_tracking.shared.domain.models import Email
from spend_tracking.shared.interfaces.email_repository import EmailRepository
from spend_tracking.shared.interfaces.email_storage import EmailStorage

logger = logging.getLogger(__name__)


class ProcessEmail:
    def __init__(
        self,
        storage: EmailStorage,
        repository: EmailRepository,
    ) -> None:
        self._storage = storage
        self._repository = repository

    def execute(
        self,
        s3_key: str,
        address: str,
        sender: str,
        received_at: str,
    ) -> None:
        raw = self._storage.get_email_raw(s3_key)
        msg = message_from_bytes(raw)

        subject = msg.get("Subject")
        body_text = self._extract_body(msg, "text/plain")
        body_html = self._extract_body(msg, "text/html")

        email = Email(
            id=uuid4(),
            address=address,
            sender=sender,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            raw_s3_key=s3_key,
            received_at=datetime.fromisoformat(received_at),
            parsed_data=None,
            created_at=datetime.now(timezone.utc),
        )
        self._repository.save_email(email)
        logger.info("Saved email %s for %s", email.id, address)

    @staticmethod
    def _extract_body(msg: Message, content_type: str) -> str | None:
        if not msg.is_multipart():
            if msg.get_content_type() == content_type:
                payload = msg.get_payload(decode=True)
                return payload.decode(msg.get_content_charset("utf-8"))
            return None

        for part in msg.walk():
            if part.get_content_type() == content_type:
                payload = part.get_payload(decode=True)
                return payload.decode(part.get_content_charset("utf-8"))
        return None
```

**Step 4: Run tests to verify they pass**

Run: `poetry run pytest tests/worker/test_process_email.py -v`
Expected: 3 PASSED

**Step 5: Run all tests**

Run: `poetry run pytest -v`
Expected: 11 PASSED

**Step 6: Commit**

```bash
git add tests/worker/test_process_email.py src/spend_tracking/worker/services/process_email.py
git commit -m "feat: add ProcessEmail worker service with TDD"
```

---

### Task 6: Adapters

**Files:**
- Create: `src/spend_tracking/shared/adapters/email_storage_s3.py`
- Create: `src/spend_tracking/shared/adapters/email_queue_sqs.py`
- Create: `src/spend_tracking/shared/adapters/email_repository_db.py`

No unit tests for V1 — these are thin wrappers around boto3/psycopg2.

**Step 1: Create S3EmailStorage adapter**

```python
# src/spend_tracking/shared/adapters/email_storage_s3.py
import boto3

from spend_tracking.shared.interfaces.email_storage import EmailStorage


class S3EmailStorage(EmailStorage):
    def __init__(self, bucket: str) -> None:
        self._s3 = boto3.client("s3")
        self._bucket = bucket

    def get_email_headers(self, s3_key: str) -> bytes:
        response = self._s3.get_object(
            Bucket=self._bucket,
            Key=s3_key,
            Range="bytes=0-8191",
        )
        return response["Body"].read()

    def get_email_raw(self, s3_key: str) -> bytes:
        response = self._s3.get_object(
            Bucket=self._bucket,
            Key=s3_key,
        )
        return response["Body"].read()
```

**Step 2: Create SQSEmailQueue adapter**

```python
# src/spend_tracking/shared/adapters/email_queue_sqs.py
import json

import boto3

from spend_tracking.shared.interfaces.email_queue import EmailQueue


class SQSEmailQueue(EmailQueue):
    def __init__(self, queue_url: str) -> None:
        self._sqs = boto3.client("sqs")
        self._queue_url = queue_url

    def send_message(self, message: dict) -> None:
        self._sqs.send_message(
            QueueUrl=self._queue_url,
            MessageBody=json.dumps(message),
        )
```

**Step 3: Create DbEmailRepository adapter**

```python
# src/spend_tracking/shared/adapters/email_repository_db.py
import json

import boto3
import psycopg2

from spend_tracking.shared.domain.models import Email, RegisteredAddress
from spend_tracking.shared.interfaces.email_repository import EmailRepository


class DbEmailRepository(EmailRepository):
    def __init__(self, ssm_parameter_name: str) -> None:
        ssm = boto3.client("ssm")
        response = ssm.get_parameter(
            Name=ssm_parameter_name,
            WithDecryption=True,
        )
        self._connection_string = response["Parameter"]["Value"]

    def get_registered_address(self, address: str) -> RegisteredAddress | None:
        with psycopg2.connect(self._connection_string) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT address, prefix, label, is_active, created_at "
                    "FROM registered_addresses WHERE address = %s",
                    (address,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return RegisteredAddress(
                    address=row[0],
                    prefix=row[1],
                    label=row[2],
                    is_active=row[3],
                    created_at=row[4],
                )

    def save_email(self, email: Email) -> None:
        with psycopg2.connect(self._connection_string) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO emails "
                    "(id, address, sender, subject, body_html, body_text, "
                    "raw_s3_key, received_at, parsed_data, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        str(email.id),
                        email.address,
                        email.sender,
                        email.subject,
                        email.body_html,
                        email.body_text,
                        email.raw_s3_key,
                        email.received_at,
                        json.dumps(email.parsed_data) if email.parsed_data else None,
                        email.created_at,
                    ),
                )
            conn.commit()
```

**Step 4: Verify all tests still pass**

Run: `poetry run pytest -v`
Expected: 11 PASSED

**Step 5: Commit**

```bash
git add src/spend_tracking/shared/adapters/
git commit -m "feat: add S3, SQS, and DB adapters"
```

---

### Task 7: Lambda Handlers

**Files:**
- Create: `src/spend_tracking/router/handler.py`
- Create: `src/spend_tracking/worker/handler.py`

No unit tests — handlers are thin wiring code.

**Step 1: Create Router handler**

```python
# src/spend_tracking/router/handler.py
import logging
import os

from spend_tracking.router.services.validate_and_enqueue import ValidateAndEnqueue
from spend_tracking.shared.adapters.email_queue_sqs import SQSEmailQueue
from spend_tracking.shared.adapters.email_repository_db import DbEmailRepository
from spend_tracking.shared.adapters.email_storage_s3 import S3EmailStorage

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_storage = S3EmailStorage(os.environ["S3_BUCKET"])
_queue = SQSEmailQueue(os.environ["SQS_QUEUE_URL"])
_repository = DbEmailRepository(os.environ["SSM_DB_CONNECTION_STRING"])
_service = ValidateAndEnqueue(_storage, _repository, _queue)


def handler(event, context):
    for record in event["Records"]:
        s3_key = record["s3"]["object"]["key"]
        logger.info("Processing S3 object: %s", s3_key)
        _service.execute(s3_key)
```

**Step 2: Create Worker handler**

```python
# src/spend_tracking/worker/handler.py
import json
import logging
import os

from spend_tracking.shared.adapters.email_repository_db import DbEmailRepository
from spend_tracking.shared.adapters.email_storage_s3 import S3EmailStorage
from spend_tracking.worker.services.process_email import ProcessEmail

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_storage = S3EmailStorage(os.environ["S3_BUCKET"])
_repository = DbEmailRepository(os.environ["SSM_DB_CONNECTION_STRING"])
_service = ProcessEmail(_storage, _repository)


def handler(event, context):
    for record in event["Records"]:
        body = json.loads(record["body"])
        logger.info("Processing email: %s", body["s3_key"])
        _service.execute(
            s3_key=body["s3_key"],
            address=body["address"],
            sender=body["sender"],
            received_at=body["received_at"],
        )
```

**Step 3: Verify all tests still pass**

Run: `poetry run pytest -v`
Expected: 11 PASSED

**Step 4: Commit**

```bash
git add src/spend_tracking/router/handler.py src/spend_tracking/worker/handler.py
git commit -m "feat: add Router and Worker Lambda handlers"
```

---

### Task 8: Makefile

**Files:**
- Create: `Makefile`

**Step 1: Create the Makefile**

```makefile
.PHONY: build build-router build-worker deploy deploy-router deploy-worker clean test

ROUTER_FUNCTION := spend-tracking-router
WORKER_FUNCTION := spend-tracking-worker
BUILD_DIR := .build

build: build-router build-worker

build-router:
	rm -rf $(BUILD_DIR)/router
	mkdir -p $(BUILD_DIR)/router
	poetry export --without-hashes --without dev -o $(BUILD_DIR)/router/requirements.txt
	pip install -r $(BUILD_DIR)/router/requirements.txt -t $(BUILD_DIR)/router/ --quiet
	cp -r src/spend_tracking $(BUILD_DIR)/router/
	cd $(BUILD_DIR)/router && zip -r ../router.zip . -x "*.pyc" "__pycache__/*"

build-worker:
	rm -rf $(BUILD_DIR)/worker
	mkdir -p $(BUILD_DIR)/worker
	poetry export --without-hashes --without dev -o $(BUILD_DIR)/worker/requirements.txt
	pip install -r $(BUILD_DIR)/worker/requirements.txt -t $(BUILD_DIR)/worker/ --quiet
	cp -r src/spend_tracking $(BUILD_DIR)/worker/
	cd $(BUILD_DIR)/worker && zip -r ../worker.zip . -x "*.pyc" "__pycache__/*"

deploy-router: build-router
	aws lambda update-function-code \
		--function-name $(ROUTER_FUNCTION) \
		--zip-file fileb://$(BUILD_DIR)/router.zip

deploy-worker: build-worker
	aws lambda update-function-code \
		--function-name $(WORKER_FUNCTION) \
		--zip-file fileb://$(BUILD_DIR)/worker.zip

deploy: deploy-router deploy-worker

clean:
	rm -rf $(BUILD_DIR)

test:
	poetry run pytest tests/ -v
```

**Step 2: Verify `make test` works**

Run: `make test`
Expected: 11 PASSED

**Step 3: Commit**

```bash
git add Makefile
git commit -m "feat: add Makefile for Lambda build and deploy"
```

---

### Task 9: Terraform Infrastructure

**Files:**
- Create: `infra/backend.tf`
- Create: `infra/provider.tf`
- Create: `infra/variables.tf`
- Create: `infra/outputs.tf`
- Create: `infra/ses.tf`
- Create: `infra/s3.tf`
- Create: `infra/sqs.tf`
- Create: `infra/lambda.tf`
- Create: `infra/iam.tf`
- Create: `infra/ssm.tf`

**Step 1: Create backend.tf**

```hcl
# infra/backend.tf
terraform {
  backend "s3" {
    bucket = "david74-terraform-remote-state-storage"
    key    = "spend-tracking/terraform.tfstate"
    region = "us-west-2"
  }
}
```

**Step 2: Create provider.tf**

```hcl
# infra/provider.tf
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  required_version = ">= 1.0"
}

provider "aws" {
  region = "us-east-1"
}
```

**Step 3: Create variables.tf**

```hcl
# infra/variables.tf
variable "email_domain" {
  description = "Domain for receiving emails"
  default     = "mail.david74.dev"
}

variable "project_name" {
  description = "Project name used as prefix for resource naming"
  default     = "spend-tracking"
}
```

**Step 4: Create s3.tf**

```hcl
# infra/s3.tf
resource "aws_s3_bucket" "raw_emails" {
  bucket = "david74-spend-tracking-raw-emails"
}

resource "aws_s3_bucket_policy" "allow_ses" {
  bucket = aws_s3_bucket.raw_emails.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowSESPuts"
        Effect    = "Allow"
        Principal = { Service = "ses.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.raw_emails.arn}/*"
      }
    ]
  })
}

resource "aws_s3_bucket_notification" "email_received" {
  bucket = aws_s3_bucket.raw_emails.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.router.arn
    events              = ["s3:ObjectCreated:*"]
  }

  depends_on = [aws_lambda_permission.allow_s3]
}
```

**Step 5: Create ses.tf**

```hcl
# infra/ses.tf
resource "aws_ses_domain_identity" "email" {
  domain = var.email_domain
}

resource "aws_ses_receipt_rule_set" "main" {
  rule_set_name = "${var.project_name}-rule-set"
}

resource "aws_ses_active_receipt_rule_set" "main" {
  rule_set_name = aws_ses_receipt_rule_set.main.rule_set_name
}

resource "aws_ses_receipt_rule" "catch_all" {
  name          = "${var.project_name}-catch-all"
  rule_set_name = aws_ses_receipt_rule_set.main.rule_set_name
  enabled       = true
  scan_enabled  = true

  s3_action {
    bucket_name = aws_s3_bucket.raw_emails.id
    position    = 1
  }
}
```

**Step 6: Create sqs.tf**

```hcl
# infra/sqs.tf
resource "aws_sqs_queue" "dlq" {
  name = "${var.project_name}-dlq"
}

resource "aws_sqs_queue" "processing" {
  name                       = "${var.project_name}-processing"
  visibility_timeout_seconds = 300

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3
  })
}
```

**Step 7: Create iam.tf**

```hcl
# infra/iam.tf

# --- Router Lambda Role ---

resource "aws_iam_role" "router" {
  name = "${var.project_name}-router"

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

resource "aws_iam_role_policy" "router" {
  name = "${var.project_name}-router"
  role = aws_iam_role.router.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.raw_emails.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = aws_sqs_queue.processing.arn
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = aws_ssm_parameter.db_connection_string.arn
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

# --- Worker Lambda Role ---

resource "aws_iam_role" "worker" {
  name = "${var.project_name}-worker"

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

resource "aws_iam_role_policy" "worker" {
  name = "${var.project_name}-worker"
  role = aws_iam_role.worker.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.raw_emails.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = aws_ssm_parameter.db_connection_string.arn
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = aws_sqs_queue.processing.arn
      }
    ]
  })
}
```

**Step 8: Create lambda.tf**

```hcl
# infra/lambda.tf

data "archive_file" "placeholder" {
  type        = "zip"
  output_path = "${path.module}/placeholder.zip"

  source {
    content  = "def handler(event, context): pass"
    filename = "spend_tracking/router/handler.py"
  }
}

resource "aws_lambda_function" "router" {
  function_name = "${var.project_name}-router"
  role          = aws_iam_role.router.arn
  handler       = "spend_tracking.router.handler.handler"
  runtime       = "python3.12"
  timeout       = 30
  memory_size   = 128
  filename      = data.archive_file.placeholder.output_path

  environment {
    variables = {
      S3_BUCKET              = aws_s3_bucket.raw_emails.id
      SQS_QUEUE_URL          = aws_sqs_queue.processing.url
      SSM_DB_CONNECTION_STRING = aws_ssm_parameter.db_connection_string.name
    }
  }

  lifecycle {
    ignore_changes = [filename, source_code_hash]
  }
}

resource "aws_lambda_permission" "allow_s3" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.router.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.raw_emails.arn
}

resource "aws_lambda_function" "worker" {
  function_name = "${var.project_name}-worker"
  role          = aws_iam_role.worker.arn
  handler       = "spend_tracking.worker.handler.handler"
  runtime       = "python3.12"
  timeout       = 60
  memory_size   = 256
  filename      = data.archive_file.placeholder.output_path

  environment {
    variables = {
      S3_BUCKET              = aws_s3_bucket.raw_emails.id
      SSM_DB_CONNECTION_STRING = aws_ssm_parameter.db_connection_string.name
    }
  }

  lifecycle {
    ignore_changes = [filename, source_code_hash]
  }
}

resource "aws_lambda_event_source_mapping" "worker_sqs" {
  event_source_arn = aws_sqs_queue.processing.arn
  function_name    = aws_lambda_function.worker.arn
  batch_size       = 1
}
```

**Step 9: Create ssm.tf**

```hcl
# infra/ssm.tf
resource "aws_ssm_parameter" "db_connection_string" {
  name  = "/${var.project_name}/db-connection-string"
  type  = "SecureString"
  value = "placeholder"

  lifecycle {
    ignore_changes = [value]
  }
}
```

**Step 10: Create outputs.tf**

```hcl
# infra/outputs.tf
output "ses_verification_token" {
  value       = aws_ses_domain_identity.email.verification_token
  description = "Add as TXT record _amazonses.mail.david74.dev in Cloudflare"
}

output "router_function_name" {
  value = aws_lambda_function.router.function_name
}

output "worker_function_name" {
  value = aws_lambda_function.worker.function_name
}

output "raw_emails_bucket" {
  value = aws_s3_bucket.raw_emails.id
}

output "sqs_queue_url" {
  value = aws_sqs_queue.processing.url
}
```

**Step 11: Validate Terraform**

Run: `cd infra && terraform init && terraform validate`
Expected: "Success! The configuration is valid."

**Step 12: Commit**

```bash
git add infra/
git commit -m "feat: add Terraform infrastructure for SES, S3, Lambda, SQS, IAM, SSM"
```

---

### Task 10: Deployment & Manual Setup

This task covers the steps to actually deploy and configure the system. These are manual/operational steps.

**Step 1: Set the Neon PG connection string in SSM**

Run:
```bash
aws ssm put-parameter \
  --name "/spend-tracking/db-connection-string" \
  --type SecureString \
  --value "postgresql://user:pass@host.neon.tech/dbname?sslmode=require" \
  --overwrite \
  --region us-east-1
```

**Step 2: Create database tables in Neon PG**

Connect to Neon and run:

```sql
CREATE TABLE registered_addresses (
    address     TEXT PRIMARY KEY,
    prefix      TEXT NOT NULL,
    label       TEXT,
    is_active   BOOLEAN DEFAULT true,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE emails (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    address     TEXT NOT NULL REFERENCES registered_addresses(address),
    sender      TEXT NOT NULL,
    subject     TEXT,
    body_html   TEXT,
    body_text   TEXT,
    raw_s3_key  TEXT NOT NULL,
    received_at TIMESTAMPTZ NOT NULL,
    parsed_data JSONB,
    created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_emails_address ON emails(address);
CREATE INDEX idx_emails_received_at ON emails(received_at DESC);
CREATE INDEX idx_emails_parsed_data ON emails USING GIN(parsed_data);
```

**Step 3: Deploy Terraform**

Run: `cd infra && terraform plan && terraform apply`

Note the `ses_verification_token` output.

**Step 4: Add DNS records in Cloudflare**

Add these records for `mail.david74.dev`:

| Type | Name | Value |
|------|------|-------|
| TXT | `_amazonses.mail.david74.dev` | `<ses_verification_token from terraform output>` |
| MX | `mail.david74.dev` | `10 inbound-smtp.us-east-1.amazonaws.com` |

**Step 5: Wait for SES domain verification**

Check status:
```bash
aws ses get-identity-verification-attributes \
  --identities mail.david74.dev \
  --region us-east-1
```
Expected: `"VerificationStatus": "Success"`

**Step 6: Deploy Lambda code**

Run: `make deploy`

**Step 7: Register a test address**

```sql
INSERT INTO registered_addresses (address, prefix, label)
VALUES ('test-abc123@mail.david74.dev', 'test', 'Test address');
```

**Step 8: Send a test email**

Send an email to `test-abc123@mail.david74.dev` and check:
- CloudWatch Logs for Router Lambda
- CloudWatch Logs for Worker Lambda
- `emails` table in Neon PG
