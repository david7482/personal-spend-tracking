# LINE Agentic Message Worker — Design

## Goal

Replace the no-op `ProcessLineMessage` service with an AI agent powered by the Anthropic SDK. The agent processes incoming LINE messages, uses tools (DB queries, code execution) to answer spending questions, and replies via the LINE Push API.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Agentic loop | Anthropic `tool_runner` (beta) | Handles tool call loop, error passing, and conversation management automatically. Only one client-side tool (`query_db`), so the built-in runner is a good fit. |
| Reply method | LINE Push API only | Reply tokens expire in 1 minute; agent loop can take longer. Push API uses `line_user_id` with no expiry. |
| Conversation memory | Unified `chat_messages` table | Rename `line_messages` → `chat_messages` with a `role` column. Both user and assistant messages stored in one table. Agent loads last 20 messages as context. |
| Code execution | Anthropic server-side `code_execution_20250825` | Runs in Anthropic's sandbox. No security concerns in Lambda. Free 1,550 hours/month. |
| DB tool scope | Read-only, transactions table only | `query_db` tool runs SELECT queries against the `transactions` table. SQL validated to reject non-SELECT statements. |
| Claude model | Configurable via `ANTHROPIC_MODEL` env var | Default: `claude-opus-4-6`. Switchable without redeployment. |
| API key storage | SSM Parameter Store | Consistent with existing secrets (LINE tokens, DB connection string). |
| Lambda timeout | 10 minutes (600s) | Agent loop with tool calls can be long. SQS visibility timeout bumped to 660s. |
| Response format | Text only (for now) | Start simple. Flex Messages and images can be added later. |
| Loading indicator | LINE loading animation API | Webhook router calls `/v2/bot/chat/loading/start` for immediate user feedback. |

## Data Model

### `chat_messages` table (replaces `line_messages`)

```sql
CREATE TABLE chat_messages (
    id SERIAL PRIMARY KEY,
    line_user_id TEXT NOT NULL,
    role TEXT NOT NULL,               -- 'user' or 'assistant'
    content TEXT,                      -- message text
    message_type TEXT NOT NULL,        -- LINE message type: 'text', 'image', etc.
    raw_event JSONB,                   -- LINE event (user) or Anthropic metadata (assistant)
    timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_chat_messages_user_time
    ON chat_messages (line_user_id, created_at DESC);
```

- `role`: `'user'` for incoming LINE messages, `'assistant'` for agent replies.
- `raw_event`: LINE webhook event JSON for user messages; Anthropic response metadata (model, usage, stop_reason) for assistant messages.
- Existing `line_messages` data migrated with `role = 'user'`, `message` renamed to `content`, `reply_token` dropped.

## Architecture

### Data Flow

```
LINE User sends message
  -> Webhook Router Lambda:
      1. Verify HMAC-SHA256 signature
      2. Save message to chat_messages (role='user')
      3. POST /v2/bot/chat/loading/start (loading animation)
      4. Enqueue {chat_message_id} to SQS
  -> Message Worker Lambda:
      1. Load user message from DB by chat_message_id
      2. Load last 20 chat_messages for this line_user_id
      3. Build Anthropic messages array from history
      4. Run tool_runner with: code_execution + query_db
      5. Extract text from final response
      6. Save assistant message to chat_messages (role='assistant')
      7. Send text reply via LINE Push API
```

### Components Changed

**New/Modified Services:**
- `ProcessLineMessage` — rewritten: Anthropic client, tool_runner, conversation history, LINE Push
- `ReceiveLineWebhook` — modified: add loading animation call, needs LINE channel access token

**New Adapters:**
- `ChatMessageRepository` (interface + DB adapter) — replaces `LineMessageRepository`. Supports `save()` and `load_history(line_user_id, limit)`.

**Removed:**
- `LineMessageRepository` interface and `DbLineMessageRepository` adapter (replaced by `ChatMessageRepository`)
- `LineMessageQueue` interface and `SQSLineMessageQueue` adapter (queue still used, but message format changes from `line_message_id` to `chat_message_id`)

**Tools:**
- `query_db` — `@beta_tool` function. Opens read-only psycopg2 connection, validates SQL is SELECT-only, executes against transactions table, returns JSON rows.
- `code_execution` — server-side Anthropic tool `{"type": "code_execution_20250825", "name": "code_execution"}`.

### System Prompt

```
You are a personal finance assistant. You help the user understand their spending
by querying their transaction database and performing calculations.

Always respond in the same language the user writes in.

You have access to:
- query_db: Run read-only SQL against the transactions table. Columns: id, source_type,
  source_id, bank, transaction_at, region, amount, currency, merchant, category, notes,
  raw_data, created_at.
- code_execution: Run Python/bash code for calculations, data analysis, and visualizations.

Guidelines:
- Keep responses concise (this is a chat app, not a report).
- Use query_db to look up real transaction data before answering spending questions.
- Use code_execution for calculations, aggregations, or formatting that SQL alone can't do.
- Amounts are stored as DECIMAL. Currency is a string like 'TWD', 'USD'.
- When showing monetary values, include the currency symbol.
- If the user's question is unclear, ask for clarification.
```

### Infrastructure Changes

| Resource | Change |
|----------|--------|
| `line_message_worker` Lambda | timeout: 60 → 600, memory: 128 → 256, add env vars: `SSM_ANTHROPIC_API_KEY`, `SSM_LINE_CHANNEL_ACCESS_TOKEN`, `ANTHROPIC_MODEL` |
| `line_webhook_router` Lambda | add env var: `SSM_LINE_CHANNEL_ACCESS_TOKEN` |
| `line-message-processing` SQS | visibility_timeout: 300 → 660 |
| SSM Parameter Store | new: `/spend-tracking/anthropic-api-key` (SecureString) |
| IAM policy | add SSM read for anthropic-api-key parameter |
| `pyproject.toml` | add `anthropic` dependency |
| Alembic | migration 006: rename table, add role column, rename message → content, drop reply_token, add index |

## Error Handling

- **Tool errors** (bad SQL, connection failures): Caught by tool_runner, passed to Claude as `is_error: true`. Claude explains the error to the user naturally.
- **Anthropic API errors** (rate limit, timeout): Caught in service. Log error, send fallback LINE Push message: "Sorry, I'm having trouble right now. Please try again."
- **Lambda timeout**: 10-min budget is generous. If exceeded, SQS retries up to 3 times before DLQ.
- **Loading animation**: Fire-and-forget. Failure to send loading animation should not block message processing.

## Testing

- **ProcessLineMessage**: Mock Anthropic client, DB, LINE Push. Test flow: load history → build messages → extract reply → save → push.
- **query_db tool**: Test SQL validation (reject non-SELECT), test query execution, test error handling.
- **ChatMessageRepository**: Test save (user + assistant), test load_history ordering and limit.
- **ReceiveLineWebhook**: Test loading animation call is made after saving message.
- **Conversation history building**: Test message ordering, limit, role mapping to Anthropic format.
