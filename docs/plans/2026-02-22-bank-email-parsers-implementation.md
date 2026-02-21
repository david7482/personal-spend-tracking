# Bank Email Parsers Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Parse Cathay United Bank daily transaction summary emails into structured data, storing results in both `emails.parsed_data` JSONB and a new `transactions` table.

**Architecture:** Parser plugin system — a registry of parser classes matched by TO address. The worker service tries each parser, and on match, extracts structured data and saves transactions. Graceful fallback to V1 behavior (no parsed data) when no parser matches or parsing fails.

**Tech Stack:** Python 3.12, stdlib `html.parser`, psycopg2, Alembic raw SQL migrations

---

### Task 1: Add Transaction Domain Model

**Files:**
- Modify: `src/spend_tracking/shared/domain/models.py`
- Test: `tests/shared/test_models.py`

**Step 1: Write the failing test**

Add to `tests/shared/test_models.py`:

```python
def test_transaction_creation():
    from decimal import Decimal
    from datetime import datetime, timezone
    from spend_tracking.shared.domain.models import Transaction

    txn = Transaction(
        id=None,
        source_type="email",
        source_id=42,
        bank="cathay",
        transaction_at=datetime(2026, 2, 19, 15, 40, tzinfo=timezone.utc),
        region="TW",
        amount=Decimal("330.00"),
        currency="TWD",
        merchant="國立臺灣科學教育館",
        category="線上繳費",
        notes=None,
        raw_data={"card_last_four": "6903", "card_type": "正卡"},
        created_at=datetime(2026, 2, 20, 6, 23, tzinfo=timezone.utc),
    )
    assert txn.bank == "cathay"
    assert txn.amount == Decimal("330.00")
    assert txn.merchant == "國立臺灣科學教育館"
    assert txn.raw_data["card_type"] == "正卡"
    assert txn.id is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/shared/test_models.py::test_transaction_creation -v`
Expected: FAIL with `ImportError: cannot import name 'Transaction'`

**Step 3: Write minimal implementation**

Add to `src/spend_tracking/shared/domain/models.py` after the `Email` class:

```python
from decimal import Decimal

@dataclass
class Transaction:
    id: int | None
    source_type: str
    source_id: int | None
    bank: str
    transaction_at: datetime
    region: str | None
    amount: Decimal
    currency: str
    merchant: str | None
    category: str | None
    notes: str | None
    raw_data: dict | None
    created_at: datetime
```

Note: Move the `from decimal import Decimal` to the top of the file with the other imports.

**Step 4: Run test to verify it passes**

Run: `pytest tests/shared/test_models.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add src/spend_tracking/shared/domain/models.py tests/shared/test_models.py
git commit -m "feat: add Transaction domain model"
```

---

### Task 2: Add TransactionRepository Interface

**Files:**
- Create: `src/spend_tracking/shared/interfaces/transaction_repository.py`

**Step 1: Create the interface**

```python
from abc import ABC, abstractmethod

from spend_tracking.shared.domain.models import Transaction


class TransactionRepository(ABC):
    @abstractmethod
    def save_transactions(self, transactions: list[Transaction]) -> None:
        ...
```

Takes a list because Cathay emails contain multiple transactions per email.

**Step 2: Verify imports work**

Run: `python -c "from spend_tracking.shared.interfaces.transaction_repository import TransactionRepository; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/spend_tracking/shared/interfaces/transaction_repository.py
git commit -m "feat: add TransactionRepository interface"
```

---

### Task 3: Add EmailParser Interface and ParseResult

**Files:**
- Create: `src/spend_tracking/shared/interfaces/email_parser.py`

**Step 1: Create the interface and result dataclass**

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

from spend_tracking.shared.domain.models import Transaction


@dataclass
class ParseResult:
    parsed_data: dict
    transactions: list[Transaction]


class EmailParser(ABC):
    @abstractmethod
    def can_parse(self, to_address: str, subject: str) -> bool:
        ...

    @abstractmethod
    def parse(self, html: str, metadata: dict) -> ParseResult:
        ...
```

`metadata` carries context the parser might need (e.g. `received_at`, `sender`).

**Step 2: Verify imports work**

Run: `python -c "from spend_tracking.shared.interfaces.email_parser import EmailParser, ParseResult; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/spend_tracking/shared/interfaces/email_parser.py
git commit -m "feat: add EmailParser interface and ParseResult"
```

---

### Task 4: Add TransactionRepository DB Adapter

**Files:**
- Create: `src/spend_tracking/shared/adapters/transaction_repository_db.py`

**Step 1: Create the adapter**

Follow the pattern from `email_repository_db.py` — SSM for connection string, psycopg2, RETURNING id.

```python
import json

import boto3
import psycopg2

from spend_tracking.shared.domain.models import Transaction
from spend_tracking.shared.interfaces.transaction_repository import TransactionRepository


class DbTransactionRepository(TransactionRepository):
    def __init__(self, ssm_parameter_name: str) -> None:
        ssm = boto3.client("ssm")
        response = ssm.get_parameter(
            Name=ssm_parameter_name,
            WithDecryption=True,
        )
        self._connection_string = response["Parameter"]["Value"]

    def save_transactions(self, transactions: list[Transaction]) -> None:
        if not transactions:
            return
        with psycopg2.connect(self._connection_string) as conn:
            with conn.cursor() as cur:
                for txn in transactions:
                    cur.execute(
                        "INSERT INTO transactions "
                        "(source_type, source_id, bank, transaction_at, region, "
                        "amount, currency, merchant, category, notes, raw_data, created_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                        "RETURNING id",
                        (
                            txn.source_type,
                            txn.source_id,
                            txn.bank,
                            txn.transaction_at,
                            txn.region,
                            txn.amount,
                            txn.currency,
                            txn.merchant,
                            txn.category,
                            txn.notes,
                            json.dumps(txn.raw_data) if txn.raw_data else None,
                            txn.created_at,
                        ),
                    )
                    txn.id = cur.fetchone()[0]
            conn.commit()
```

**Step 2: Verify imports work**

Run: `python -c "from spend_tracking.shared.adapters.transaction_repository_db import DbTransactionRepository; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/spend_tracking/shared/adapters/transaction_repository_db.py
git commit -m "feat: add DbTransactionRepository adapter"
```

---

### Task 5: Implement Cathay Parser (TDD)

**Files:**
- Create: `src/spend_tracking/worker/services/parsers/__init__.py`
- Create: `src/spend_tracking/worker/services/parsers/cathay.py`
- Create: `tests/worker/parsers/__init__.py`
- Create: `tests/worker/test_cathay_parser.py`
- Create: `tests/worker/parsers/` (empty `__init__.py`)

**Step 1: Create test fixture**

Create `tests/worker/test_cathay_parser.py` with an HTML fixture extracted from the real email. The fixture should contain a minimal but representative Cathay HTML with 2 transactions (enough to test the repeating pattern).

Build the fixture by decoding the sample email's HTML structure — the key elements are:
- A notification date cell: `通知日期：2026/02/20`
- A card last 4 cell: `卡號後4碼： 6903`
- Repeating transaction blocks with header row (卡別, 行動卡號後4碼, 授權日期, 授權時間, 消費地區) and data row (消費金額, 商店名稱, 消費類別, 備註)

```python
from decimal import Decimal
from datetime import datetime, timezone, timedelta

TAIPEI_TZ = timezone(timedelta(hours=8))

CATHAY_HTML_FIXTURE = """
<html>
<body>
<table>
  <tr><td>消費彙整通知</td></tr>
  <tr><td>通知日期：2026/02/20</td></tr>
  <tr><td>親愛的客戶，您好</td></tr>
  <tr><td>感謝您使用國泰世華銀行信用卡/簽帳金融卡消費，您最新的消費授權紀錄如下：</td></tr>
  <tr><td>卡號後4碼： 6903</td></tr>
</table>
<table>
  <tbody>
    <tr>
      <td>卡別</td><td>行動卡號後4碼</td><td>授權日期</td><td>授權時間</td><td>消費地區</td>
    </tr>
    <tr>
      <td>正卡</td><td>4623</td><td>2026/02/19</td><td>15:40</td><td>TW</td>
    </tr>
    <tr>
      <td>消費金額</td><td>商店名稱</td><td>消費類別</td><td>備註</td>
    </tr>
    <tr>
      <td colspan="2">NT$330</td><td>國立臺灣科學教育館</td><td>線上繳費</td><td>&nbsp;</td>
    </tr>
  </tbody>
</table>
<table>
  <tbody>
    <tr>
      <td>卡別</td><td>行動卡號後4碼</td><td>授權日期</td><td>授權時間</td><td>消費地區</td>
    </tr>
    <tr>
      <td>正卡</td><td>6012</td><td>2026/02/19</td><td>00:27</td><td>NL</td>
    </tr>
    <tr>
      <td>消費金額</td><td>商店名稱</td><td>消費類別</td><td>備註</td>
    </tr>
    <tr>
      <td colspan="2">NT$1,040</td><td>PRAGMATICENGINEER.COM</td><td>其他</td><td>&nbsp;</td>
    </tr>
  </tbody>
</table>
</body>
</html>
"""


def test_can_parse_matches_cathay_address():
    from spend_tracking.worker.services.parsers.cathay import CathayParser

    parser = CathayParser()
    assert parser.can_parse("cathay-cc@mail.david74.dev", "國泰世華銀行消費彙整通知") is True


def test_can_parse_rejects_other_address():
    from spend_tracking.worker.services.parsers.cathay import CathayParser

    parser = CathayParser()
    assert parser.can_parse("ctbc-cc@mail.david74.dev", "something") is False


def test_parses_two_transactions():
    from spend_tracking.worker.services.parsers.cathay import CathayParser

    parser = CathayParser()
    result = parser.parse(CATHAY_HTML_FIXTURE, {"received_at": "2026-02-20T06:23:16+00:00"})

    assert len(result.transactions) == 2

    txn1 = result.transactions[0]
    assert txn1.amount == Decimal("330")
    assert txn1.merchant == "國立臺灣科學教育館"
    assert txn1.category == "線上繳費"
    assert txn1.region == "TW"
    assert txn1.transaction_at == datetime(2026, 2, 19, 15, 40, tzinfo=TAIPEI_TZ)
    assert txn1.bank == "cathay"
    assert txn1.raw_data["card_type"] == "正卡"
    assert txn1.raw_data["mobile_card_last_four"] == "4623"

    txn2 = result.transactions[1]
    assert txn2.amount == Decimal("1040")
    assert txn2.merchant == "PRAGMATICENGINEER.COM"
    assert txn2.region == "NL"


def test_parsed_data_has_email_metadata():
    from spend_tracking.worker.services.parsers.cathay import CathayParser

    parser = CathayParser()
    result = parser.parse(CATHAY_HTML_FIXTURE, {"received_at": "2026-02-20T06:23:16+00:00"})

    assert result.parsed_data["bank"] == "cathay"
    assert result.parsed_data["email_type"] == "daily_transaction_summary"
    assert result.parsed_data["notification_date"] == "2026/02/20"
    assert result.parsed_data["card_last_four"] == "6903"
    assert result.parsed_data["transaction_count"] == 2


def test_malformed_html_returns_empty_result():
    from spend_tracking.worker.services.parsers.cathay import CathayParser

    parser = CathayParser()
    result = parser.parse("<html><body>no tables</body></html>", {"received_at": "2026-02-20T06:23:16+00:00"})

    assert len(result.transactions) == 0
    assert result.parsed_data["bank"] == "cathay"
    assert result.parsed_data["transaction_count"] == 0
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/worker/test_cathay_parser.py -v`
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Create parser package and implement CathayParser**

Create empty `__init__.py` files:
- `src/spend_tracking/worker/services/parsers/__init__.py`

Implement `src/spend_tracking/worker/services/parsers/cathay.py`:

```python
import re
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from html.parser import HTMLParser

from spend_tracking.shared.domain.models import Transaction
from spend_tracking.shared.interfaces.email_parser import EmailParser, ParseResult

TAIPEI_TZ = timezone(timedelta(hours=8))
CATHAY_ADDRESS_PREFIX = "cathay-"


class _TableCellExtractor(HTMLParser):
    """Extracts text content from all <td> elements."""

    def __init__(self):
        super().__init__()
        self.cells: list[str] = []
        self._in_td = False
        self._current = ""
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag == "td":
            self._in_td = True
            self._current = ""
        elif tag in ("style", "script"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag == "td" and self._in_td:
            self._in_td = False
            text = self._current.strip()
            if text:
                self.cells.append(text)
        elif tag in ("style", "script"):
            self._skip = False

    def handle_data(self, data):
        if self._in_td and not self._skip:
            self._current += data

    def handle_entityref(self, name):
        if self._in_td and name == "nbsp":
            pass  # skip &nbsp;


class CathayParser(EmailParser):
    def can_parse(self, to_address: str, subject: str) -> bool:
        local_part = to_address.split("@")[0]
        return local_part.startswith(CATHAY_ADDRESS_PREFIX)

    def parse(self, html: str, metadata: dict) -> ParseResult:
        extractor = _TableCellExtractor()
        extractor.feed(html)
        cells = extractor.cells

        notification_date = self._extract_notification_date(cells)
        card_last_four = self._extract_card_last_four(cells)
        transactions = self._extract_transactions(cells)

        return ParseResult(
            parsed_data={
                "bank": "cathay",
                "email_type": "daily_transaction_summary",
                "notification_date": notification_date,
                "card_last_four": card_last_four,
                "transaction_count": len(transactions),
            },
            transactions=transactions,
        )

    def _extract_notification_date(self, cells: list[str]) -> str | None:
        for cell in cells:
            if cell.startswith("通知日期："):
                return cell.replace("通知日期：", "")
        return None

    def _extract_card_last_four(self, cells: list[str]) -> str | None:
        for cell in cells:
            if "卡號後4碼" in cell:
                match = re.search(r"(\d{4})", cell)
                return match.group(1) if match else None
        return None

    def _extract_transactions(self, cells: list[str]) -> list[Transaction]:
        transactions = []
        i = 0
        while i < len(cells):
            # Look for the header pattern: 卡別
            if cells[i] == "卡別" and i + 9 < len(cells):
                # Header row: 卡別, 行動卡號後4碼, 授權日期, 授權時間, 消費地區
                # Data row:   values...
                # Label row:  消費金額, 商店名稱, 消費類別, 備註
                # Value row:  amount, merchant, category, notes
                card_type = cells[i + 5]
                mobile_card = cells[i + 6]
                auth_date = cells[i + 7]
                auth_time = cells[i + 8]
                region = cells[i + 9]

                # Find the amount/merchant block (starts after 消費金額 label)
                j = i + 10
                if j < len(cells) and cells[j] == "消費金額":
                    # Skip label row: 消費金額, 商店名稱, 消費類別, 備註
                    j += 4
                    if j < len(cells):
                        amount_str = cells[j]
                        merchant = cells[j + 1] if j + 1 < len(cells) else None
                        category = cells[j + 2] if j + 2 < len(cells) else None

                        amount = self._parse_amount(amount_str)
                        transaction_at = self._parse_datetime(auth_date, auth_time)

                        if amount is not None and transaction_at is not None:
                            transactions.append(
                                Transaction(
                                    id=None,
                                    source_type="email",
                                    source_id=None,
                                    bank="cathay",
                                    transaction_at=transaction_at,
                                    region=region,
                                    amount=amount,
                                    currency="TWD",
                                    merchant=merchant,
                                    category=category,
                                    notes=None,
                                    raw_data={
                                        "card_type": card_type,
                                        "mobile_card_last_four": mobile_card,
                                    },
                                    created_at=transaction_at,
                                )
                            )
                        i = j + 3
                        continue
            i += 1
        return transactions

    @staticmethod
    def _parse_amount(text: str) -> Decimal | None:
        match = re.search(r"NT\$([\d,]+)", text)
        if not match:
            return None
        return Decimal(match.group(1).replace(",", ""))

    @staticmethod
    def _parse_datetime(date_str: str, time_str: str) -> datetime | None:
        try:
            return datetime.strptime(
                f"{date_str} {time_str}", "%Y/%m/%d %H:%M"
            ).replace(tzinfo=TAIPEI_TZ)
        except (ValueError, AttributeError):
            return None
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/worker/test_cathay_parser.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add src/spend_tracking/worker/services/parsers/ tests/worker/test_cathay_parser.py
git commit -m "feat: add Cathay bank email parser"
```

---

### Task 6: Add Parser Registry

**Files:**
- Modify: `src/spend_tracking/worker/services/parsers/__init__.py`

**Step 1: Implement the registry**

```python
from spend_tracking.shared.interfaces.email_parser import EmailParser, ParseResult
from spend_tracking.worker.services.parsers.cathay import CathayParser

_PARSERS: list[EmailParser] = [
    CathayParser(),
]


def find_parser(to_address: str, subject: str) -> EmailParser | None:
    for parser in _PARSERS:
        if parser.can_parse(to_address, subject):
            return parser
    return None
```

**Step 2: Verify imports work**

Run: `python -c "from spend_tracking.worker.services.parsers import find_parser; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/spend_tracking/worker/services/parsers/__init__.py
git commit -m "feat: add parser registry"
```

---

### Task 7: Update ProcessEmail Service (TDD)

**Files:**
- Modify: `src/spend_tracking/worker/services/process_email.py`
- Modify: `tests/worker/test_process_email.py`

**Step 1: Write failing test for parser integration**

Add to `tests/worker/test_process_email.py`:

```python
def test_populates_parsed_data_when_parser_matches():
    from spend_tracking.worker.services.process_email import ProcessEmail

    storage = MagicMock()
    repository = MagicMock()
    transaction_repository = MagicMock()

    # Use Cathay-like address and a multipart email with HTML
    html = """<html><body>
    <table><tr><td>消費彙整通知</td></tr>
    <tr><td>通知日期：2026/02/20</td></tr>
    <tr><td>卡號後4碼： 6903</td></tr></table>
    <table><tbody>
    <tr><td>卡別</td><td>行動卡號後4碼</td><td>授權日期</td><td>授權時間</td><td>消費地區</td></tr>
    <tr><td>正卡</td><td>4623</td><td>2026/02/19</td><td>15:40</td><td>TW</td></tr>
    <tr><td>消費金額</td><td>商店名稱</td><td>消費類別</td><td>備註</td></tr>
    <tr><td colspan="2">NT$330</td><td>Test Store</td><td>線上繳費</td><td>&nbsp;</td></tr>
    </tbody></table>
    </body></html>"""

    storage.get_email_raw.return_value = _make_multipart_email(body_html=html)

    service = ProcessEmail(storage, repository, transaction_repository)
    service.execute(
        s3_key="cathay-key",
        address="cathay-cc@mail.david74.dev",
        sender="service@cathaybk.com.tw",
        received_at="2026-02-20T06:23:16+00:00",
    )

    saved_email = repository.save_email.call_args[0][0]
    assert saved_email.parsed_data is not None
    assert saved_email.parsed_data["bank"] == "cathay"
    assert saved_email.parsed_data["transaction_count"] == 1

    transaction_repository.save_transactions.assert_called_once()
    txns = transaction_repository.save_transactions.call_args[0][0]
    assert len(txns) == 1
    assert txns[0].merchant == "Test Store"


def test_no_parser_match_leaves_parsed_data_none():
    from spend_tracking.worker.services.process_email import ProcessEmail

    storage = MagicMock()
    repository = MagicMock()
    transaction_repository = MagicMock()

    storage.get_email_raw.return_value = _make_plain_email()

    service = ProcessEmail(storage, repository, transaction_repository)
    service.execute(
        s3_key="other-key",
        address="unknown@mail.david74.dev",
        sender="noreply@other.com",
        received_at="2026-02-21T10:00:00+00:00",
    )

    saved_email = repository.save_email.call_args[0][0]
    assert saved_email.parsed_data is None
    transaction_repository.save_transactions.assert_not_called()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/worker/test_process_email.py::test_populates_parsed_data_when_parser_matches -v`
Expected: FAIL (ProcessEmail constructor signature changed)

**Step 3: Update ProcessEmail to accept parsers and transaction repository**

Modify `src/spend_tracking/worker/services/process_email.py`:

```python
import logging
from datetime import datetime, timezone
from email import message_from_bytes
from email.header import decode_header
from email.message import Message

from spend_tracking.shared.domain.models import Email
from spend_tracking.shared.interfaces.email_repository import EmailRepository
from spend_tracking.shared.interfaces.email_storage import EmailStorage
from spend_tracking.shared.interfaces.transaction_repository import TransactionRepository
from spend_tracking.worker.services.parsers import find_parser

logger = logging.getLogger(__name__)


class ProcessEmail:
    def __init__(
        self,
        storage: EmailStorage,
        repository: EmailRepository,
        transaction_repository: TransactionRepository,
    ) -> None:
        self._storage = storage
        self._repository = repository
        self._transaction_repository = transaction_repository

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

        parser = find_parser(address, subject or "")
        if parser and body_html:
            try:
                result = parser.parse(body_html, {"received_at": received_at})
                parsed_data = result.parsed_data
                transactions = result.transactions
            except Exception:
                logger.exception("Parser failed for %s, falling back to raw storage", address)

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
            created_at=datetime.now(timezone.utc),
        )
        self._repository.save_email(email)
        logger.info("Saved email %s for %s", email.id, address)

        if transactions:
            for txn in transactions:
                txn.source_id = email.id
            self._transaction_repository.save_transactions(transactions)
            logger.info("Saved %d transactions for email %s", len(transactions), email.id)

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
                payload = msg.get_payload(decode=True)
                return payload.decode(msg.get_content_charset("utf-8"))
            return None

        for part in msg.walk():
            if part.get_content_type() == content_type:
                payload = part.get_payload(decode=True)
                return payload.decode(part.get_content_charset("utf-8"))
        return None
```

**Step 4: Update existing tests to pass the new argument**

In `tests/worker/test_process_email.py`, update ALL existing tests to add `transaction_repository = MagicMock()` and pass it as the third argument to `ProcessEmail(storage, repository, transaction_repository)`.

There are 4 existing tests to update:
- `test_processes_multipart_email`
- `test_processes_plain_text_only_email`
- `test_email_has_correct_metadata`
- `test_decodes_mime_encoded_subject`

Each needs the same change: add `transaction_repository = MagicMock()` and pass it to the constructor.

**Step 5: Run all tests to verify they pass**

Run: `pytest tests/ -v`
Expected: All tests PASS (existing 12 + 2 new = 14, plus 5 cathay parser = 19 total)

**Step 6: Commit**

```bash
git add src/spend_tracking/worker/services/process_email.py tests/worker/test_process_email.py
git commit -m "feat: integrate parser pipeline into worker service"
```

---

### Task 8: Update Worker Handler Wiring

**Files:**
- Modify: `src/spend_tracking/worker/handler.py`

**Step 1: Add the transaction repository to handler wiring**

```python
import json
import logging
import os

from spend_tracking.shared.adapters.email_repository_db import DbEmailRepository
from spend_tracking.shared.adapters.email_storage_s3 import S3EmailStorage
from spend_tracking.shared.adapters.transaction_repository_db import DbTransactionRepository
from spend_tracking.worker.services.process_email import ProcessEmail

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_storage = S3EmailStorage(os.environ["S3_BUCKET"])
_repository = DbEmailRepository(os.environ["SSM_DB_CONNECTION_STRING"])
_transaction_repository = DbTransactionRepository(os.environ["SSM_DB_CONNECTION_STRING"])
_service = ProcessEmail(_storage, _repository, _transaction_repository)


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

Both `DbEmailRepository` and `DbTransactionRepository` use the same SSM parameter for the connection string since they share the same database.

**Step 2: Run all tests to verify nothing broke**

Run: `pytest tests/ -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add src/spend_tracking/worker/handler.py
git commit -m "feat: wire transaction repository into worker handler"
```

---

### Task 9: Add Database Migration

**Files:**
- Create: `migrations/versions/002_add_transactions.py`

**Step 1: Create migration**

Run: `make migrate-new name="add_transactions"`

This generates a new migration file. Edit it to contain:

```python
"""add transactions

Revision ID: 002
Revises: 001
Create Date: 2026-02-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '002'
down_revision: Union[str, Sequence[str], None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE transactions (
            id              BIGSERIAL PRIMARY KEY,
            source_type     TEXT NOT NULL,
            source_id       BIGINT,
            bank            TEXT NOT NULL,
            transaction_at  TIMESTAMPTZ NOT NULL,
            region          TEXT,
            amount          NUMERIC(12,2) NOT NULL,
            currency        TEXT NOT NULL DEFAULT 'TWD',
            merchant        TEXT,
            category        TEXT,
            notes           TEXT,
            raw_data        JSONB,
            created_at      TIMESTAMPTZ DEFAULT now()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS transactions")
```

**Step 2: Run all tests one final time**

Run: `pytest tests/ -v`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add migrations/versions/002_add_transactions.py
git commit -m "feat: add transactions table migration"
```

---

### Task 10: Validate Against Real Email

**Files:** None (manual validation)

**Step 1: Run the parser against the real sample email**

```bash
python -c "
import email
from email import policy

with open('/tmp/cathy-email-example1.eml', 'rb') as f:
    msg = email.message_from_binary_file(f, policy=policy.default)

for part in msg.walk():
    if part.get_content_type() == 'text/html':
        html = part.get_content()
        break

from spend_tracking.worker.services.parsers.cathay import CathayParser
parser = CathayParser()
result = parser.parse(html, {'received_at': '2026-02-20T06:23:16+00:00'})

print(f'Parsed data: {result.parsed_data}')
print(f'Transactions: {len(result.transactions)}')
for t in result.transactions:
    print(f'  {t.transaction_at} | {t.amount} {t.currency} | {t.merchant} | {t.category} | {t.region}')
"
```

Expected: 4 transactions matching the email content:
- NT$330 國立臺灣科學教育館 (TW)
- NT$472 PRAGMATICENGINEER.COM (NL)
- NT$661 OPENAI *CHATGPT SUBSCR (US)
- NT$1,040 新光影城－聚食光 (TW)

**Step 2: If any transactions are missing or wrong, debug and fix the parser**

The real email HTML is more complex than the test fixture (deeply nested tables, CSS classes, quoted-printable encoding). The `_TableCellExtractor` should handle this since it just looks at `<td>` elements, but verify the cell ordering matches expectations.

**Step 3: Commit any fixes**

```bash
git add -A && git commit -m "fix: adjust parser for real Cathay email format"
```

(Only if changes were needed)
