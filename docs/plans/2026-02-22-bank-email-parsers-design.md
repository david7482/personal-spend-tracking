# Bank Email Parsers — Design

## Goal

Parse structured transaction data from bank notification emails. Start with Cathay United Bank (國泰世華) daily transaction summaries; make the system extensible to other banks.

## Approach: Parser Plugin System

A registry of parser classes, one per bank. The worker service matches incoming emails to a parser, extracts structured data, and writes both `emails.parsed_data` JSONB and normalized `transactions` rows.

## Data Model

### New `transactions` table

```sql
CREATE TABLE transactions (
    id              BIGSERIAL PRIMARY KEY,
    source_type     TEXT NOT NULL,           -- 'email', 'manual', 'api', etc.
    source_id       BIGINT,                  -- email_id when source_type='email'
    bank            TEXT NOT NULL,            -- 'cathay', 'ctbc', etc.
    transaction_at  TIMESTAMPTZ NOT NULL,
    region          TEXT,                     -- 'TW', 'US', 'NL'
    amount          NUMERIC(12,2) NOT NULL,
    currency        TEXT NOT NULL DEFAULT 'TWD',
    merchant        TEXT,
    category        TEXT,
    notes           TEXT,
    raw_data        JSONB,                   -- parser-specific extras (card_last_four, card_type, etc.)
    created_at      TIMESTAMPTZ DEFAULT now()
);
```

No indexes beyond PK — add once access patterns are clear.

### `emails.parsed_data` JSONB

```json
{
  "bank": "cathay",
  "email_type": "daily_transaction_summary",
  "notification_date": "2026-02-20",
  "card_last_four": "6903",
  "transaction_count": 4
}
```

## Parser Architecture

### New files

```
src/spend_tracking/shared/
├── domain/models.py                        # Add Transaction dataclass
├── interfaces/
│   ├── email_parser.py                     # ABC: EmailParser
│   └── transaction_repository.py           # ABC: TransactionRepository
└── adapters/
    └── transaction_repository_db.py        # INSERT transactions

src/spend_tracking/worker/services/
├── process_email.py                        # Enhanced: calls parser + saves transactions
└── parsers/
    ├── __init__.py                          # Parser registry
    ├── base.py                              # Shared HTML parsing utilities
    └── cathay.py                            # CathayParser
```

### Parser interface

```python
class EmailParser(ABC):
    @abstractmethod
    def can_parse(self, to_address: str, subject: str) -> bool: ...

    @abstractmethod
    def parse(self, html: str, metadata: dict) -> ParseResult: ...

@dataclass
class ParseResult:
    parsed_data: dict               # → emails.parsed_data
    transactions: list[Transaction] # → transactions table
```

### Registry

A list of parser instances. The worker iterates, calls `can_parse(to_address, subject)` — first match wins. No match → V1 behavior (`parsed_data=None`).

### Worker flow

```
existing:  parse MIME → save email (parsed_data=None)
new:       parse MIME → match parser → extract data → save email (with parsed_data) → save transactions
```

## Cathay Parser Details

**Email type:** Daily transaction summary (消費彙整通知)

**Sender:** `service@pxbillrc01.cathaybk.com.tw`

**Matching:** `can_parse` checks the TO address prefix (e.g. `cathay-*@mail.david74.dev`).

**HTML structure:** Repeating table blocks per transaction:
- Header cells: 卡別, 行動卡號後4碼, 授權日期, 授權時間, 消費地區
- Data cells: 消費金額, 商店名稱, 消費類別, 備註

**Parsing:** Python stdlib `html.parser` — extract `<td>` contents, walk the cell list for repeating patterns. No external dependencies.

**Amount parsing:** Strip `NT$` prefix + commas → `Decimal`.

**Timezone:** `Asia/Taipei` (UTC+8) for `transaction_at`.

**`raw_data` per transaction:**
```json
{
  "card_last_four": "6903",
  "mobile_card_last_four": "4623",
  "card_type": "正卡"
}
```

**Error handling:** Parse failure → log error, fall back to V1 (`parsed_data=None`). Raw email always preserved in S3.

## Testing

**Cathay parser tests:**
- Parses 4 transactions with correct amounts, merchants, dates from fixture
- Handles empty notes
- `can_parse` matches correct TO address, rejects others
- Malformed HTML returns empty result

**Worker service tests:**
- Parser match → `parsed_data` and transactions saved
- No parser match → V1 behavior
- Parser failure → V1 fallback

Unit tests only, mocked adapters — matches existing project strategy.
