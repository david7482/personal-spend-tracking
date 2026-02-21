# LINE Transaction Notification — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Send a LINE Flex Message when the worker Lambda extracts transactions from a bank email.

**Architecture:** Optional `NotificationSender` injected into `ProcessEmail`. After transactions are saved, `ProcessEmail` looks up the `line_recipient_id` from the registered address and delegates to the sender. `LineNotificationSender` builds a Flex Message and pushes it via the LINE Messaging API. Failures are logged and do not block processing.

**Tech Stack:** Python 3.12, LINE Messaging API (push + Flex Messages), urllib.request, Alembic, Terraform

---

### Task 1: DB Migration and Domain Model

**Files:**
- Create: `migrations/versions/003_add_line_recipient_id.py`
- Modify: `src/spend_tracking/shared/domain/models.py:7-12`

**Step 1: Create Alembic migration**

Create `migrations/versions/003_add_line_recipient_id.py`:

```python
"""add line_recipient_id to registered_addresses

Revision ID: 003
Revises: 002
Create Date: 2026-02-22

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '003'
down_revision: Union[str, Sequence[str], None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE registered_addresses ADD COLUMN line_recipient_id TEXT"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE registered_addresses DROP COLUMN line_recipient_id"
    )
```

**Step 2: Update RegisteredAddress dataclass**

In `src/spend_tracking/shared/domain/models.py`, add `line_recipient_id` field to `RegisteredAddress`:

```python
@dataclass
class RegisteredAddress:
    id: int
    address: str
    prefix: str
    label: str | None
    is_active: bool
    created_at: datetime
    line_recipient_id: str | None
```

**Step 3: Run tests to verify nothing breaks**

Run: `PYTHONPATH=src poetry run pytest tests/ -v`
Expected: All existing tests PASS (no test references `RegisteredAddress` fields by position)

**Step 4: Commit**

```bash
git add migrations/versions/003_add_line_recipient_id.py src/spend_tracking/shared/domain/models.py
git commit -m "feat: add line_recipient_id to registered_addresses"
```

---

### Task 2: Update DbEmailRepository to Include line_recipient_id

**Files:**
- Modify: `src/spend_tracking/shared/adapters/email_repository_db.py:20-36`

**Step 1: Update the SELECT query and RegisteredAddress construction**

In `email_repository_db.py`, update `get_registered_address`:

```python
def get_registered_address(self, address: str) -> RegisteredAddress | None:
    with psycopg2.connect(self._connection_string) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id, address, prefix, label, is_active, created_at, "
            "line_recipient_id "
            "FROM registered_addresses WHERE address = %s",
            (address,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return RegisteredAddress(
            id=row[0],
            address=row[1],
            prefix=row[2],
            label=row[3],
            is_active=row[4],
            created_at=row[5],
            line_recipient_id=row[6],
        )
```

**Step 2: Run tests**

Run: `PYTHONPATH=src poetry run pytest tests/ -v`
Expected: All existing tests PASS

**Step 3: Commit**

```bash
git add src/spend_tracking/shared/adapters/email_repository_db.py
git commit -m "feat: include line_recipient_id in registered address query"
```

---

### Task 3: Create NotificationSender Interface

**Files:**
- Create: `src/spend_tracking/shared/interfaces/notification_sender.py`

**Step 1: Create the ABC**

```python
from abc import ABC, abstractmethod

from spend_tracking.shared.domain.models import Transaction


class NotificationSender(ABC):
    @abstractmethod
    def send_transaction_notification(
        self,
        recipient_id: str,
        bank: str,
        transactions: list[Transaction],
    ) -> None: ...
```

**Step 2: Run lint and typecheck**

Run: `PYTHONPATH=src poetry run ruff check src/spend_tracking/shared/interfaces/notification_sender.py && PYTHONPATH=src poetry run mypy src/spend_tracking/shared/interfaces/notification_sender.py`
Expected: No errors

**Step 3: Commit**

```bash
git add src/spend_tracking/shared/interfaces/notification_sender.py
git commit -m "feat: add NotificationSender interface"
```

---

### Task 4: Flex Message Builder

**Files:**
- Create: `tests/worker/test_flex_message.py`
- Create: `src/spend_tracking/worker/services/flex_message.py`

**Step 1: Write the failing test**

Create `tests/worker/test_flex_message.py`:

```python
from datetime import datetime, timezone
from decimal import Decimal

from spend_tracking.shared.domain.models import Transaction


def _make_transaction(
    merchant: str = "Test Store",
    amount: Decimal = Decimal("1250"),
    currency: str = "TWD",
    category: str | None = "餐飲",
    transaction_at: datetime | None = None,
) -> Transaction:
    return Transaction(
        id=1,
        source_type="email",
        source_id=1,
        bank="cathay",
        transaction_at=transaction_at or datetime(2026, 2, 22, 15, 40, tzinfo=timezone.utc),
        region="TW",
        amount=amount,
        currency=currency,
        merchant=merchant,
        category=category,
        notes=None,
        raw_data=None,
        created_at=datetime(2026, 2, 22, 15, 40, tzinfo=timezone.utc),
    )


def test_build_flex_message_single_transaction():
    from spend_tracking.worker.services.flex_message import build_flex_message

    txn = _make_transaction()
    result = build_flex_message("cathay", [txn])

    assert result["type"] == "bubble"
    assert result["size"] == "mega"

    # Header: bank name + transaction count
    header_texts = [c["text"] for c in result["header"]["contents"]]
    assert "🏦 cathay" in header_texts[0]
    assert "1" in header_texts[1]

    # Body: one transaction row
    body_contents = result["body"]["contents"]
    # Should have one transaction box (no separator for single txn)
    assert len(body_contents) == 1
    row = body_contents[0]
    # Left side: merchant + metadata
    merchant_text = row["contents"][0]["contents"][0]["text"]
    assert "Test Store" in merchant_text
    # Right side: amount
    amount_text = row["contents"][1]["text"]
    assert "1,250" in amount_text

    # Footer: total
    footer_texts = [c["text"] for c in result["footer"]["contents"]]
    assert "1,250" in footer_texts[1]


def test_build_flex_message_multiple_transactions():
    from spend_tracking.worker.services.flex_message import build_flex_message

    txns = [
        _make_transaction(merchant="星巴克", amount=Decimal("1250"), category="餐飲"),
        _make_transaction(merchant="全聯福利中心", amount=Decimal("3500"), category="購物"),
    ]
    result = build_flex_message("cathay", txns)

    header_texts = [c["text"] for c in result["header"]["contents"]]
    assert "2" in header_texts[1]

    # Body: txn1 + separator + txn2
    body_contents = result["body"]["contents"]
    assert len(body_contents) == 3
    assert body_contents[1]["type"] == "separator"

    # Footer total should sum both
    footer_total = result["footer"]["contents"][1]["text"]
    assert "4,750" in footer_total


def test_build_flex_message_nil_merchant_and_category():
    from spend_tracking.worker.services.flex_message import build_flex_message

    txn = _make_transaction(merchant=None, category=None)
    result = build_flex_message("cathay", [txn])

    row = result["body"]["contents"][0]
    merchant_text = row["contents"][0]["contents"][0]["text"]
    assert merchant_text == "—"

    metadata_text = row["contents"][0]["contents"][1]["text"]
    # Should still have the date, no category prefix
    assert "02/22" in metadata_text


def test_build_flex_message_formats_amount_with_commas():
    from spend_tracking.worker.services.flex_message import build_flex_message

    txn = _make_transaction(amount=Decimal("12345678"))
    result = build_flex_message("cathay", [txn])

    row = result["body"]["contents"][0]
    amount_text = row["contents"][1]["text"]
    assert "NT$12,345,678" in amount_text
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src poetry run pytest tests/worker/test_flex_message.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Implement the Flex Message builder**

Create `src/spend_tracking/worker/services/flex_message.py`:

```python
from typing import Any

from spend_tracking.shared.domain.models import Transaction


def build_flex_message(bank: str, transactions: list[Transaction]) -> dict[str, Any]:
    count = len(transactions)
    date_str = transactions[0].transaction_at.strftime("%Y/%m/%d")
    total = sum(t.amount for t in transactions)
    currency = transactions[0].currency

    return {
        "type": "bubble",
        "size": "mega",
        "header": _build_header(bank, count, date_str),
        "body": _build_body(transactions),
        "footer": _build_footer(currency, total),
    }


def _build_header(bank: str, count: int, date_str: str) -> dict[str, Any]:
    return {
        "type": "box",
        "layout": "vertical",
        "contents": [
            {
                "type": "text",
                "text": f"🏦 {bank}",
                "weight": "bold",
                "size": "lg",
                "color": "#FFFFFF",
            },
            {
                "type": "text",
                "text": f"💳 {count} 筆交易 · {date_str}",
                "size": "xs",
                "color": "#FFFFFFAA",
                "margin": "sm",
            },
        ],
        "backgroundColor": "#4A6B8A",
        "paddingAll": "18px",
        "paddingStart": "20px",
    }


def _build_body(transactions: list[Transaction]) -> dict[str, Any]:
    contents: list[dict[str, Any]] = []
    for i, txn in enumerate(transactions):
        if i > 0:
            contents.append({"type": "separator", "color": "#F0F0F0"})
        contents.append(_build_transaction_row(txn))

    return {
        "type": "box",
        "layout": "vertical",
        "spacing": "lg",
        "paddingAll": "20px",
        "contents": contents,
    }


def _build_transaction_row(txn: Transaction) -> dict[str, Any]:
    merchant = txn.merchant or "—"
    date_str = txn.transaction_at.strftime("%m/%d")
    metadata = f"{txn.category} · {date_str}" if txn.category else date_str

    return {
        "type": "box",
        "layout": "horizontal",
        "contents": [
            {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {
                        "type": "text",
                        "text": merchant,
                        "weight": "bold",
                        "size": "md",
                        "color": "#2C3E50",
                    },
                    {
                        "type": "text",
                        "text": metadata,
                        "size": "xs",
                        "color": "#A0A0A0",
                        "margin": "xs",
                    },
                ],
                "flex": 3,
            },
            {
                "type": "text",
                "text": f"{txn.currency}${txn.amount:,.0f}",
                "weight": "bold",
                "size": "md",
                "color": "#2C3E50",
                "align": "end",
                "gravity": "center",
                "flex": 2,
            },
        ],
    }


def _build_footer(currency: str, total: int | float) -> dict[str, Any]:
    return {
        "type": "box",
        "layout": "horizontal",
        "contents": [
            {
                "type": "text",
                "text": "合計",
                "size": "sm",
                "color": "#8C8C8C",
                "gravity": "center",
            },
            {
                "type": "text",
                "text": f"{currency}${total:,.0f}",
                "weight": "bold",
                "size": "lg",
                "color": "#2C3E50",
                "align": "end",
            },
        ],
        "backgroundColor": "#F4F6F9",
        "paddingAll": "18px",
        "paddingStart": "20px",
        "paddingEnd": "20px",
    }
```

**Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src poetry run pytest tests/worker/test_flex_message.py -v`
Expected: All 4 tests PASS

**Step 5: Run full CI check**

Run: `make lint && make typecheck`
Expected: No errors

**Step 6: Commit**

```bash
git add tests/worker/test_flex_message.py src/spend_tracking/worker/services/flex_message.py
git commit -m "feat: add Flex Message builder for LINE notifications"
```

---

### Task 5: LineNotificationSender Adapter

**Files:**
- Create: `tests/worker/test_line_notification_sender.py`
- Create: `src/spend_tracking/shared/adapters/notification_sender_line.py`

**Step 1: Write the failing tests**

Create `tests/worker/test_line_notification_sender.py`:

```python
import json
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from spend_tracking.shared.domain.models import Transaction


def _make_transaction(
    merchant: str = "星巴克",
    amount: Decimal = Decimal("1250"),
) -> Transaction:
    return Transaction(
        id=1,
        source_type="email",
        source_id=1,
        bank="cathay",
        transaction_at=datetime(2026, 2, 22, 15, 40, tzinfo=timezone.utc),
        region="TW",
        amount=amount,
        currency="TWD",
        merchant=merchant,
        category="餐飲",
        notes=None,
        raw_data=None,
        created_at=datetime(2026, 2, 22, 15, 40, tzinfo=timezone.utc),
    )


@patch("spend_tracking.shared.adapters.notification_sender_line.urlopen")
def test_sends_push_message_to_line_api(mock_urlopen):
    from spend_tracking.shared.adapters.notification_sender_line import (
        LineNotificationSender,
    )

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.read.return_value = b'{"message":"ok"}'
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_response

    sender = LineNotificationSender(channel_access_token="test-token")
    sender.send_transaction_notification(
        recipient_id="U1234567890",
        bank="cathay",
        transactions=[_make_transaction()],
    )

    mock_urlopen.assert_called_once()
    request = mock_urlopen.call_args[0][0]
    assert request.full_url == "https://api.line.me/v2/bot/message/push"
    assert request.get_header("Authorization") == "Bearer test-token"
    assert request.get_header("Content-type") == "application/json"

    body = json.loads(request.data)
    assert body["to"] == "U1234567890"
    assert len(body["messages"]) == 1
    assert body["messages"][0]["type"] == "flex"
    assert "cathay" in body["messages"][0]["altText"]


@patch("spend_tracking.shared.adapters.notification_sender_line.urlopen")
def test_logs_error_on_http_failure(mock_urlopen, caplog):
    from spend_tracking.shared.adapters.notification_sender_line import (
        LineNotificationSender,
    )

    mock_urlopen.side_effect = Exception("Connection refused")

    sender = LineNotificationSender(channel_access_token="test-token")
    # Should NOT raise
    sender.send_transaction_notification(
        recipient_id="U1234567890",
        bank="cathay",
        transactions=[_make_transaction()],
    )

    assert "LINE notification failed" in caplog.text
```

**Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src poetry run pytest tests/worker/test_line_notification_sender.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Implement LineNotificationSender**

Create `src/spend_tracking/shared/adapters/notification_sender_line.py`:

```python
import json
import logging
from urllib.request import Request, urlopen

from spend_tracking.shared.domain.models import Transaction
from spend_tracking.shared.interfaces.notification_sender import NotificationSender
from spend_tracking.worker.services.flex_message import build_flex_message

logger = logging.getLogger(__name__)

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


class LineNotificationSender(NotificationSender):
    def __init__(self, channel_access_token: str) -> None:
        self._token = channel_access_token

    def send_transaction_notification(
        self,
        recipient_id: str,
        bank: str,
        transactions: list[Transaction],
    ) -> None:
        try:
            flex_contents = build_flex_message(bank, transactions)
            count = len(transactions)
            alt_text = f"🏦 {bank} — {count} 筆交易"

            payload = {
                "to": recipient_id,
                "messages": [
                    {
                        "type": "flex",
                        "altText": alt_text,
                        "contents": flex_contents,
                    }
                ],
            }

            data = json.dumps(payload).encode("utf-8")
            request = Request(
                LINE_PUSH_URL,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._token}",
                },
            )

            with urlopen(request) as response:
                logger.info(
                    "LINE notification sent",
                    extra={
                        "recipient_id": recipient_id,
                        "status": response.status,
                        "transaction_count": count,
                    },
                )
        except Exception:
            logger.exception(
                "LINE notification failed",
                extra={"recipient_id": recipient_id, "bank": bank},
            )
```

**Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src poetry run pytest tests/worker/test_line_notification_sender.py -v`
Expected: All 2 tests PASS

**Step 5: Run lint and typecheck**

Run: `make lint && make typecheck`
Expected: No errors

**Step 6: Commit**

```bash
git add tests/worker/test_line_notification_sender.py src/spend_tracking/shared/adapters/notification_sender_line.py
git commit -m "feat: add LineNotificationSender adapter"
```

---

### Task 6: Integrate NotificationSender into ProcessEmail

**Files:**
- Modify: `src/spend_tracking/worker/services/process_email.py:18-84`
- Modify: `tests/worker/test_process_email.py`

**Step 1: Write the failing tests**

Append to `tests/worker/test_process_email.py`:

```python
def test_sends_notification_when_transactions_parsed():
    from spend_tracking.worker.services.process_email import ProcessEmail

    storage = MagicMock()
    repository = MagicMock()
    transaction_repository = MagicMock()
    notification_sender = MagicMock()

    # Use Cathay-like address with HTML that triggers parser
    html = """<html><body>
    <table><tr><td>消費彙整通知</td></tr>
    <tr><td>通知日期：2026/02/20</td></tr>
    <tr><td>卡號後4碼： 6903</td></tr></table>
    <table><tbody>
    <tr><td>卡別</td><td>行動卡號後4碼</td><td>授權日期</td><td>授權時間</td><td>消費地區</td></tr>
    <tr><td>正卡</td><td>4623</td><td>2026/02/19</td><td>15:40</td><td>TW</td></tr>
    <tr><td>消費金額</td><td>商店名稱</td><td>消費類別</td><td>備註</td></tr>
    <tr><td colspan="2">NT$330</td><td>Test Store</td>
    <td>線上繳費</td><td>&nbsp;</td></tr>
    </tbody></table>
    </body></html>"""

    storage.get_email_raw.return_value = _make_multipart_email(body_html=html)

    # Repository returns a registered address with line_recipient_id
    from spend_tracking.shared.domain.models import RegisteredAddress
    from datetime import datetime, timezone

    registered = RegisteredAddress(
        id=1,
        address="cathay-cc@mail.david74.dev",
        prefix="cathay-cc",
        label="Cathay CC",
        is_active=True,
        created_at=datetime.now(timezone.utc),
        line_recipient_id="U1234567890",
    )
    repository.get_registered_address.return_value = registered

    service = ProcessEmail(
        storage, repository, transaction_repository, notification_sender
    )
    service.execute(
        s3_key="cathay-key",
        address="cathay-cc@mail.david74.dev",
        sender="service@cathaybk.com.tw",
        received_at="2026-02-20T06:23:16+00:00",
    )

    notification_sender.send_transaction_notification.assert_called_once()
    call_kwargs = notification_sender.send_transaction_notification.call_args
    assert call_kwargs[1]["recipient_id"] == "U1234567890"
    assert call_kwargs[1]["bank"] == "cathay"
    assert len(call_kwargs[1]["transactions"]) == 1


def test_no_notification_when_no_transactions():
    from spend_tracking.worker.services.process_email import ProcessEmail

    storage = MagicMock()
    repository = MagicMock()
    transaction_repository = MagicMock()
    notification_sender = MagicMock()

    storage.get_email_raw.return_value = _make_plain_email()

    service = ProcessEmail(
        storage, repository, transaction_repository, notification_sender
    )
    service.execute(
        s3_key="other-key",
        address="unknown@mail.david74.dev",
        sender="noreply@other.com",
        received_at="2026-02-21T10:00:00+00:00",
    )

    notification_sender.send_transaction_notification.assert_not_called()


def test_no_notification_when_no_line_recipient():
    from spend_tracking.worker.services.process_email import ProcessEmail

    storage = MagicMock()
    repository = MagicMock()
    transaction_repository = MagicMock()
    notification_sender = MagicMock()

    html = """<html><body>
    <table><tr><td>消費彙整通知</td></tr>
    <tr><td>通知日期：2026/02/20</td></tr>
    <tr><td>卡號後4碼： 6903</td></tr></table>
    <table><tbody>
    <tr><td>卡別</td><td>行動卡號後4碼</td><td>授權日期</td><td>授權時間</td><td>消費地區</td></tr>
    <tr><td>正卡</td><td>4623</td><td>2026/02/19</td><td>15:40</td><td>TW</td></tr>
    <tr><td>消費金額</td><td>商店名稱</td><td>消費類別</td><td>備註</td></tr>
    <tr><td colspan="2">NT$330</td><td>Test Store</td>
    <td>線上繳費</td><td>&nbsp;</td></tr>
    </tbody></table>
    </body></html>"""

    storage.get_email_raw.return_value = _make_multipart_email(body_html=html)

    # Registered address with NO line_recipient_id
    from spend_tracking.shared.domain.models import RegisteredAddress
    from datetime import datetime, timezone

    registered = RegisteredAddress(
        id=1,
        address="cathay-cc@mail.david74.dev",
        prefix="cathay-cc",
        label="Cathay CC",
        is_active=True,
        created_at=datetime.now(timezone.utc),
        line_recipient_id=None,
    )
    repository.get_registered_address.return_value = registered

    service = ProcessEmail(
        storage, repository, transaction_repository, notification_sender
    )
    service.execute(
        s3_key="cathay-key",
        address="cathay-cc@mail.david74.dev",
        sender="service@cathaybk.com.tw",
        received_at="2026-02-20T06:23:16+00:00",
    )

    notification_sender.send_transaction_notification.assert_not_called()


def test_notification_failure_does_not_block_processing():
    from spend_tracking.worker.services.process_email import ProcessEmail

    storage = MagicMock()
    repository = MagicMock()
    transaction_repository = MagicMock()
    notification_sender = MagicMock()

    html = """<html><body>
    <table><tr><td>消費彙整通知</td></tr>
    <tr><td>通知日期：2026/02/20</td></tr>
    <tr><td>卡號後4碼： 6903</td></tr></table>
    <table><tbody>
    <tr><td>卡別</td><td>行動卡號後4碼</td><td>授權日期</td><td>授權時間</td><td>消費地區</td></tr>
    <tr><td>正卡</td><td>4623</td><td>2026/02/19</td><td>15:40</td><td>TW</td></tr>
    <tr><td>消費金額</td><td>商店名稱</td><td>消費類別</td><td>備註</td></tr>
    <tr><td colspan="2">NT$330</td><td>Test Store</td>
    <td>線上繳費</td><td>&nbsp;</td></tr>
    </tbody></table>
    </body></html>"""

    storage.get_email_raw.return_value = _make_multipart_email(body_html=html)

    from spend_tracking.shared.domain.models import RegisteredAddress
    from datetime import datetime, timezone

    registered = RegisteredAddress(
        id=1,
        address="cathay-cc@mail.david74.dev",
        prefix="cathay-cc",
        label="Cathay CC",
        is_active=True,
        created_at=datetime.now(timezone.utc),
        line_recipient_id="U1234567890",
    )
    repository.get_registered_address.return_value = registered

    # Make notification sender raise
    notification_sender.send_transaction_notification.side_effect = Exception("boom")

    service = ProcessEmail(
        storage, repository, transaction_repository, notification_sender
    )
    # Should NOT raise
    service.execute(
        s3_key="cathay-key",
        address="cathay-cc@mail.david74.dev",
        sender="service@cathaybk.com.tw",
        received_at="2026-02-20T06:23:16+00:00",
    )

    # Email and transactions should still have been saved
    repository.save_email.assert_called_once()
    transaction_repository.save_transactions.assert_called_once()
```

**Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src poetry run pytest tests/worker/test_process_email.py::test_sends_notification_when_transactions_parsed -v`
Expected: FAIL (ProcessEmail doesn't accept notification_sender yet)

**Step 3: Update ProcessEmail**

Modify `src/spend_tracking/worker/services/process_email.py`:

```python
import logging
from datetime import UTC, datetime
from email import message_from_bytes
from email.header import decode_header
from email.message import Message

from spend_tracking.shared.domain.models import Email
from spend_tracking.shared.interfaces.email_repository import EmailRepository
from spend_tracking.shared.interfaces.email_storage import EmailStorage
from spend_tracking.shared.interfaces.notification_sender import NotificationSender
from spend_tracking.shared.interfaces.transaction_repository import (
    TransactionRepository,
)
from spend_tracking.worker.services.parsers import find_parser

logger = logging.getLogger(__name__)


class ProcessEmail:
    def __init__(
        self,
        storage: EmailStorage,
        repository: EmailRepository,
        transaction_repository: TransactionRepository,
        notification_sender: NotificationSender | None = None,
    ) -> None:
        self._storage = storage
        self._repository = repository
        self._transaction_repository = transaction_repository
        self._notification_sender = notification_sender

    def execute(
        self,
        s3_key: str,
        address: str,
        sender: str,
        received_at: str,
    ) -> None:
        raw = self._storage.get_email_raw(s3_key)
        msg = message_from_bytes(raw)

        subject = self._decode_header(msg.get("Subject"))
        body_text = self._extract_body(msg, "text/plain")
        body_html = self._extract_body(msg, "text/html")

        parsed_data = None
        transactions = []
        bank = None

        parser = find_parser(address, subject or "")
        if parser and body_html:
            try:
                result = parser.parse(body_html, {"received_at": received_at})
                parsed_data = result.parsed_data
                transactions = result.transactions
                bank = parsed_data.get("bank")
            except Exception:
                logger.exception(
                    "Parser failed for %s, falling back",
                    address,
                )

        email = Email(
            id=None,
            address=address,
            sender=sender,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            raw_s3_key=s3_key,
            received_at=datetime.fromisoformat(received_at),
            parsed_data=parsed_data,
            created_at=datetime.now(UTC),
        )
        self._repository.save_email(email)
        logger.info(
            "Saved email",
            extra={"email_id": email.id, "address": address, "s3_key": s3_key},
        )

        if transactions:
            for txn in transactions:
                txn.source_id = email.id
            self._transaction_repository.save_transactions(transactions)
            logger.info(
                "Saved %d transactions for email %s",
                len(transactions),
                email.id,
            )

            self._send_notification(address, bank or "unknown", transactions)

    def _send_notification(
        self, address: str, bank: str, transactions: list["Transaction"]
    ) -> None:
        if not self._notification_sender:
            return
        try:
            registered = self._repository.get_registered_address(address)
            if not registered or not registered.line_recipient_id:
                return
            self._notification_sender.send_transaction_notification(
                recipient_id=registered.line_recipient_id,
                bank=bank,
                transactions=transactions,
            )
        except Exception:
            logger.exception(
                "Notification sending failed for %s",
                address,
            )

    @staticmethod
    def _decode_header(value: str | None) -> str | None:
        if value is None:
            return None
        parts = decode_header(value)
        decoded = []
        for data, charset in parts:
            if isinstance(data, bytes):
                decoded.append(data.decode(charset or "utf-8", errors="replace"))
            else:
                decoded.append(data)
        return "".join(decoded)

    @staticmethod
    def _extract_body(msg: Message, content_type: str) -> str | None:
        if not msg.is_multipart():
            if msg.get_content_type() == content_type:
                payload: bytes | None = msg.get_payload(decode=True)  # type: ignore[assignment]
                if payload is None:
                    return None
                return payload.decode(msg.get_content_charset("utf-8"))
            return None

        for part in msg.walk():
            if part.get_content_type() == content_type:
                payload = part.get_payload(decode=True)  # type: ignore[assignment]
                if payload is None:
                    return None
                return payload.decode(part.get_content_charset("utf-8"))
        return None
```

Note: The `_send_notification` method has its own try/except to ensure notification failures never propagate. The `NotificationSender.send_transaction_notification` also catches internally, but this is a defense-in-depth belt-and-suspenders approach.

**Step 4: Add missing import for type annotation**

Add to the imports at the top of `process_email.py` if mypy requires it:

```python
from spend_tracking.shared.domain.models import Email, Transaction
```

(Replace the existing `Email`-only import.)

**Step 5: Run all tests**

Run: `PYTHONPATH=src poetry run pytest tests/worker/test_process_email.py -v`
Expected: All tests PASS (old tests still work because `notification_sender` defaults to `None`)

**Step 6: Run full CI**

Run: `make lint && make typecheck`
Expected: No errors

**Step 7: Commit**

```bash
git add src/spend_tracking/worker/services/process_email.py tests/worker/test_process_email.py
git commit -m "feat: integrate NotificationSender into ProcessEmail"
```

---

### Task 7: Wire LineNotificationSender into Worker Handler

**Files:**
- Modify: `src/spend_tracking/worker/handler.py`

**Step 1: Update handler to create and inject LineNotificationSender**

```python
import json
import logging
import os

import boto3

from spend_tracking.shared.adapters.email_repository_db import DbEmailRepository
from spend_tracking.shared.adapters.email_storage_s3 import S3EmailStorage
from spend_tracking.shared.adapters.notification_sender_line import (
    LineNotificationSender,
)
from spend_tracking.shared.adapters.transaction_repository_db import (
    DbTransactionRepository,
)
from spend_tracking.worker.services.process_email import ProcessEmail

logger = logging.getLogger()

_storage = S3EmailStorage(os.environ["S3_BUCKET"])
_repository = DbEmailRepository(os.environ["SSM_DB_CONNECTION_STRING"])
_transaction_repository = DbTransactionRepository(
    os.environ["SSM_DB_CONNECTION_STRING"]
)

_notification_sender = None
_line_token_param = os.environ.get("SSM_LINE_CHANNEL_ACCESS_TOKEN")
if _line_token_param:
    ssm = boto3.client("ssm")
    response = ssm.get_parameter(Name=_line_token_param, WithDecryption=True)
    _notification_sender = LineNotificationSender(
        channel_access_token=response["Parameter"]["Value"]
    )

_service = ProcessEmail(
    _storage, _repository, _transaction_repository, _notification_sender
)


def handler(event: dict, context: object) -> None:
    for record in event["Records"]:
        body = json.loads(record["body"])
        extra = {
            "s3_key": body["s3_key"],
            "address": body["address"],
            "sender": body["sender"],
        }
        logger.info("Processing email", extra=extra)
        _service.execute(
            s3_key=body["s3_key"],
            address=body["address"],
            sender=body["sender"],
            received_at=body["received_at"],
        )
```

The `SSM_LINE_CHANNEL_ACCESS_TOKEN` env var is optional — if not set, no notification sender is created and the feature is disabled.

**Step 2: Run lint and typecheck**

Run: `make lint && make typecheck`
Expected: No errors

**Step 3: Commit**

```bash
git add src/spend_tracking/worker/handler.py
git commit -m "feat: wire LineNotificationSender into worker handler"
```

---

### Task 8: Terraform Infrastructure

**Files:**
- Modify: `infra/ssm.tf`
- Modify: `infra/iam.tf:70-107`
- Modify: `infra/lambda.tf:56-60`

**Step 1: Add SSM parameter for LINE token**

Append to `infra/ssm.tf`:

```hcl
resource "aws_ssm_parameter" "line_channel_access_token" {
  name  = "/${var.project_name}/line-channel-access-token"
  type  = "SecureString"
  value = "placeholder"

  lifecycle {
    ignore_changes = [value]
  }
}
```

**Step 2: Add IAM permission for worker to read the new SSM parameter**

In `infra/iam.tf`, update the worker role policy's SSM statement to include both parameters. Change:

```hcl
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = aws_ssm_parameter.db_connection_string.arn
      },
```

To:

```hcl
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = [
          aws_ssm_parameter.db_connection_string.arn,
          aws_ssm_parameter.line_channel_access_token.arn
        ]
      },
```

**Step 3: Add env var to worker Lambda**

In `infra/lambda.tf`, update the worker Lambda environment variables. Change:

```hcl
  environment {
    variables = {
      S3_BUCKET               = aws_s3_bucket.raw_emails.id
      SSM_DB_CONNECTION_STRING = aws_ssm_parameter.db_connection_string.name
    }
  }
```

To:

```hcl
  environment {
    variables = {
      S3_BUCKET                      = aws_s3_bucket.raw_emails.id
      SSM_DB_CONNECTION_STRING        = aws_ssm_parameter.db_connection_string.name
      SSM_LINE_CHANNEL_ACCESS_TOKEN   = aws_ssm_parameter.line_channel_access_token.name
    }
  }
```

**Step 4: Validate Terraform**

Run: `cd infra && terraform validate`
Expected: `Success! The configuration is valid.`

**Step 5: Run full CI to make sure app code still passes**

Run: `make ci`
Expected: All checks pass

**Step 6: Commit**

```bash
git add infra/ssm.tf infra/iam.tf infra/lambda.tf
git commit -m "infra: add LINE channel access token SSM parameter and worker permissions"
```