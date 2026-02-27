# Local Agent CLI — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extract shared agent core from `process_line_message.py` into `agent.py`, then build a local REPL CLI that reuses it with full trace logging.

**Architecture:** Shared `agent.py` module provides system prompt, tools, and a generator-based `run_agent()`. `ProcessLineMessage` and CLI both consume it. CLI uses in-memory history and ANSI-colored output.

**Tech Stack:** Python 3.12, Anthropic SDK (`beta.messages.tool_runner`), psycopg2, ANSI escape codes (no external deps)

---

### Task 1: Extract shared agent module

**Files:**
- Create: `src/spend_tracking/lambdas/services/agent.py`
- Create: `src/spend_tracking/lambdas/services/agent_test.py`
- Modify: `pyproject.toml` (add mypy override for new test module)

**Step 1: Write tests for the shared agent module**

Create `src/spend_tracking/lambdas/services/agent_test.py`:

```python
import json
from unittest.mock import MagicMock

from spend_tracking.lambdas.services.agent import (
    FALLBACK_MESSAGE,
    SYSTEM_PROMPT,
    build_tools,
    extract_text,
    run_agent,
    validate_sql,
)


def test_system_prompt_is_nonempty_string():
    assert isinstance(SYSTEM_PROMPT, str)
    assert len(SYSTEM_PROMPT) > 0


def test_validate_sql_allows_select():
    assert validate_sql("SELECT * FROM transactions") is True
    assert validate_sql("select count(*) from transactions") is True
    assert validate_sql("WITH cte AS (SELECT 1) SELECT * FROM cte") is True


def test_validate_sql_rejects_mutations():
    assert validate_sql("DROP TABLE transactions") is False
    assert validate_sql("DELETE FROM transactions") is False
    assert validate_sql("INSERT INTO transactions VALUES (1)") is False
    assert validate_sql("UPDATE transactions SET amount = 0") is False


def test_build_tools_returns_two_tools():
    tools = build_tools("postgresql://fake")
    assert len(tools) == 2


def test_extract_text_returns_text_from_message():
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(type="text", text="Hello world")]
    assert extract_text(mock_msg) == "Hello world"


def test_extract_text_joins_multiple_text_blocks():
    block1 = MagicMock(type="text", text="Hello")
    block2 = MagicMock(type="tool_use")
    block2.type = "tool_use"
    block3 = MagicMock(type="text", text="world")
    mock_msg = MagicMock()
    mock_msg.content = [block1, block2, block3]
    assert extract_text(mock_msg) == "Hello\nworld"


def test_extract_text_returns_fallback_when_no_text():
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(type="tool_use")]
    mock_msg.content[0].type = "tool_use"
    assert extract_text(mock_msg) == FALLBACK_MESSAGE


def test_run_agent_yields_messages_from_tool_runner():
    mock_msg1 = MagicMock()
    mock_msg2 = MagicMock()
    mock_runner = MagicMock()
    mock_runner.__iter__ = MagicMock(return_value=iter([mock_msg1, mock_msg2]))

    mock_client = MagicMock()
    mock_client.beta.messages.tool_runner.return_value = mock_runner

    tools = [MagicMock(), MagicMock()]
    messages = [{"role": "user", "content": "Hi"}]

    yielded = list(run_agent(mock_client, "claude-opus-4-6", tools, messages))

    assert yielded == [mock_msg1, mock_msg2]
    mock_client.beta.messages.tool_runner.assert_called_once()
```

**Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/lambdas/services/agent_test.py -v`
Expected: FAIL — `agent` module does not exist.

**Step 3: Implement `agent.py`**

Create `src/spend_tracking/lambdas/services/agent.py`:

```python
import json
from collections.abc import Generator

import psycopg2
from anthropic import Anthropic, beta_tool

SYSTEM_PROMPT = """\
You are a personal finance assistant. You help the user understand their spending \
by querying their transaction database and performing calculations.

Always respond in the same language the user writes in.

Guidelines:
- Keep responses concise (this is a chat app, not a report).
- Use query_db to look up real transaction data first.
- Use code_execution for calculations or formatting.
- When showing monetary values, include the currency symbol.
- If the user's question is unclear, ask for clarification.\
"""

FALLBACK_MESSAGE = "Sorry, I'm having trouble right now. Please try again later."


def validate_sql(sql: str) -> bool:
    """Only allow SELECT statements."""
    stripped = sql.strip().upper()
    return stripped.startswith("SELECT") or stripped.startswith("WITH")


def _make_query_db_tool(connection_string: str):  # type: ignore[no-untyped-def]
    """Create a query_db beta_tool function bound to a DB connection string."""

    @beta_tool
    def query_db(sql: str) -> str:
        """Run a read-only SQL query against the transactions table.
        Only SELECT statements are allowed.

        Schema — transactions:
          id              BIGSERIAL PK
          source_type     TEXT, currently always 'email'
          source_id       BIGINT, nullable, references emails.id
          bank            TEXT, lowercase bank name (e.g. 'cathay')
          transaction_at  TIMESTAMPTZ, when the transaction occurred (stored in UTC)
          region          TEXT, nullable, ISO country code (e.g. 'TW', 'NL')
          amount          NUMERIC(12,2), always positive
          currency        TEXT, default 'TWD' (e.g. 'TWD', 'USD')
          merchant        TEXT, nullable, may contain Chinese text
          category        TEXT, nullable, may contain Chinese text
                          (e.g. '線上繳費', '其他')
          notes           TEXT, nullable
          raw_data        JSONB, nullable, bank-specific payload
                          (Cathay: {"card_type": "正卡",
                           "mobile_card_last_four": "4623"})
          created_at      TIMESTAMPTZ, default now()

        Args:
            sql: A SELECT SQL query to run against the transactions table.
        Returns:
            JSON array of result rows, or an error message.
        """
        if not validate_sql(sql):
            return json.dumps({"error": "Only SELECT queries are allowed."})

        try:
            with (
                psycopg2.connect(connection_string) as conn,
                conn.cursor() as cur,
            ):
                cur.execute(sql)
                columns = [desc[0] for desc in cur.description or []]
                rows = cur.fetchall()
                result = [dict(zip(columns, row, strict=False)) for row in rows]
                return json.dumps(result, default=str)
        except Exception as e:
            return json.dumps({"error": str(e)})

    return query_db


def build_tools(db_connection_string: str) -> list:
    """Build the agent's tool list."""
    return [
        _make_query_db_tool(db_connection_string),
        {"type": "code_execution_20260120", "name": "code_execution"},
    ]


def extract_text(message: object) -> str:
    """Extract text content from Anthropic response message."""
    parts: list[str] = []
    for block in message.content:  # type: ignore[attr-defined]
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts) if parts else FALLBACK_MESSAGE


def run_agent(
    client: Anthropic,
    model: str,
    tools: list,
    messages: list[dict],
) -> Generator[object, None, None]:
    """Run the agent and yield each message from tool_runner."""
    runner = client.beta.messages.tool_runner(
        model=model,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=tools,
        messages=messages,  # type: ignore[arg-type]
    )
    for message in runner:
        yield message
```

**Step 4: Add mypy override for test module in `pyproject.toml`**

Add `"spend_tracking.lambdas.services.agent_test"` to the mypy overrides list.

**Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/lambdas/services/agent_test.py -v`
Expected: All 8 tests PASS.

**Step 6: Commit**

```bash
git add src/spend_tracking/lambdas/services/agent.py src/spend_tracking/lambdas/services/agent_test.py pyproject.toml
git commit -m "feat: extract shared agent module from process_line_message"
```

---

### Task 2: Refactor `ProcessLineMessage` to use `agent.py`

**Files:**
- Modify: `src/spend_tracking/lambdas/services/process_line_message.py`
- Modify: `src/spend_tracking/lambdas/services/process_line_message_test.py`

**Step 1: Update `process_line_message.py`**

Remove: `SYSTEM_PROMPT`, `FALLBACK_MESSAGE`, `_validate_sql`, `_make_query_db_tool`, `_extract_text` (all moved to `agent.py`). Keep: `LinePushSender`, `_build_messages`, `ProcessLineMessage`.

Replace imports and update `execute()` to use `build_tools()`, `run_agent()`, `extract_text()` from `agent.py`:

```python
import json
import logging
from datetime import UTC, datetime

from anthropic import Anthropic

from spend_tracking.domains.models import ChatMessage
from spend_tracking.interfaces.chat_message_repository import ChatMessageRepository
from spend_tracking.lambdas.services.agent import (
    FALLBACK_MESSAGE,
    build_tools,
    extract_text,
    run_agent,
)

logger = logging.getLogger(__name__)


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


def _build_messages(history: list[ChatMessage], current: ChatMessage) -> list[dict]:
    """Build Anthropic messages array from conversation history."""
    messages: list[dict] = []
    for msg in history:
        if msg.content is not None:
            messages.append({"role": msg.role, "content": msg.content})
    if current.content is not None:
        messages.append({"role": "user", "content": current.content})
    return messages


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
            tools = build_tools(self._db_connection_string)
            final_message = None
            for message in run_agent(
                self._client, self._model, tools, messages
            ):
                final_message = message
            reply_text = (
                extract_text(final_message) if final_message else FALLBACK_MESSAGE
            )
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
                    "input_tokens": getattr(message.usage, "input_tokens", None),  # type: ignore[attr-defined]
                    "output_tokens": getattr(message.usage, "output_tokens", None),  # type: ignore[attr-defined]
                },
            }
        except Exception:
            return None
```

**Step 2: Update test imports in `process_line_message_test.py`**

The `test_query_db_rejects_non_select` and `test_build_messages_from_history` tests import from `process_line_message`. Update:
- `_validate_sql` import changes to `validate_sql` from `agent`
- `_build_messages` stays in `process_line_message` (no change needed for that test)
- The two `ProcessLineMessage` tests should work unchanged since the class API is identical

Update `test_query_db_rejects_non_select`:
```python
def test_query_db_rejects_non_select():
    from spend_tracking.lambdas.services.agent import validate_sql

    assert validate_sql("SELECT * FROM transactions") is True
    assert validate_sql("select count(*) from transactions") is True
    assert validate_sql("WITH cte AS (SELECT 1) SELECT * FROM cte") is True
    assert validate_sql("DROP TABLE transactions") is False
    assert validate_sql("DELETE FROM transactions") is False
    assert validate_sql("INSERT INTO transactions VALUES (1)") is False
    assert validate_sql("UPDATE transactions SET amount = 0") is False
```

**Step 3: Run all tests**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/lambdas/services/process_line_message_test.py src/spend_tracking/lambdas/services/agent_test.py -v`
Expected: All tests PASS.

**Step 4: Run full CI**

Run: `make ci`
Expected: PASS (lint, format, typecheck, all tests, build).

**Step 5: Commit**

```bash
git add src/spend_tracking/lambdas/services/process_line_message.py src/spend_tracking/lambdas/services/process_line_message_test.py
git commit -m "refactor: use shared agent module in ProcessLineMessage"
```

---

### Task 3: Build the local CLI REPL

**Files:**
- Create: `src/spend_tracking/cli/__init__.py` (empty)
- Create: `src/spend_tracking/cli/chat.py`
- Modify: `Makefile` (add `chat` target)

**Step 1: Create the CLI package**

Create empty `src/spend_tracking/cli/__init__.py`.

**Step 2: Implement `chat.py`**

Create `src/spend_tracking/cli/chat.py`:

```python
import json
import os
import sys

from anthropic import Anthropic

from spend_tracking.lambdas.services.agent import (
    SYSTEM_PROMPT,
    build_tools,
    extract_text,
    run_agent,
)

# ANSI color codes
DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[36m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
MAGENTA = "\033[35m"
RESET = "\033[0m"


def _header(label: str, color: str = CYAN) -> str:
    return f"\n{color}{BOLD}── {label} {'─' * (50 - len(label))}{RESET}"


def _print_message_trace(message: object) -> None:
    """Print detailed trace of a single agent message."""
    for block in message.content:  # type: ignore[attr-defined]
        block_type = getattr(block, "type", None)

        if block_type == "text":
            print(f"{_header('Response', GREEN)}")
            print(block.text)

        elif block_type == "tool_use":
            print(f"{_header(f'Tool: {block.name}', CYAN)}")
            formatted = json.dumps(block.input, indent=2, default=str)
            print(f"{DIM}{formatted}{RESET}")

        elif block_type == "tool_result":
            print(f"{_header('Result', YELLOW)}")
            content = getattr(block, "content", None)
            if isinstance(content, str):
                try:
                    parsed = json.loads(content)
                    print(f"{DIM}{json.dumps(parsed, indent=2, default=str)}{RESET}")
                except json.JSONDecodeError:
                    print(f"{DIM}{content}{RESET}")
            elif content is not None:
                print(f"{DIM}{content}{RESET}")

        elif block_type == "code_execution_tool_result":
            print(f"{_header('Code Execution', MAGENTA)}")
            stdout = getattr(block, "stdout", None)
            stderr = getattr(block, "stderr", None)
            if stdout:
                print(f"{DIM}{stdout}{RESET}")
            if stderr:
                print(f"{DIM}stderr: {stderr}{RESET}")

        elif block_type == "server_tool_use":
            print(f"{_header(f'Tool: {getattr(block, "name", block_type)}', CYAN)}")

    # Print usage metadata
    usage = getattr(message, "usage", None)
    model = getattr(message, "model", None)
    stop_reason = getattr(message, "stop_reason", None)
    if usage:
        input_t = getattr(usage, "input_tokens", "?")
        output_t = getattr(usage, "output_tokens", "?")
        print(
            f"\n{DIM}model: {model} | "
            f"tokens: {input_t} in / {output_t} out | "
            f"stop: {stop_reason}{RESET}"
        )


def main() -> None:
    db_url = os.environ.get("DATABASE_URL")
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    if not db_url:
        print("Error: DATABASE_URL environment variable is required.", file=sys.stderr)
        sys.exit(1)
    if not api_key:
        print(
            "Error: ANTHROPIC_API_KEY environment variable is required.",
            file=sys.stderr,
        )
        sys.exit(1)

    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")

    client = Anthropic(api_key=api_key)
    tools = build_tools(db_url)
    messages: list[dict] = []

    print(f"{BOLD}Spend Tracking Agent{RESET}")
    print(f"{DIM}Model: {model} | DB: {db_url.split('@')[-1] if '@' in db_url else '***'}{RESET}")
    print(f"{DIM}System prompt:{RESET}")
    print(f"{DIM}{SYSTEM_PROMPT}{RESET}")
    print(f"{DIM}Type your message. Ctrl+C or Ctrl+D to exit.{RESET}\n")

    try:
        while True:
            try:
                user_input = input(f"{BOLD}You: {RESET}")
            except EOFError:
                break

            if not user_input.strip():
                continue

            messages.append({"role": "user", "content": user_input})

            final_message = None
            try:
                for message in run_agent(client, model, tools, messages):
                    _print_message_trace(message)
                    final_message = message
            except Exception as e:
                print(f"\n{BOLD}Error:{RESET} {e}", file=sys.stderr)
                messages.pop()
                continue

            if final_message:
                reply = extract_text(final_message)
                messages.append({"role": "assistant", "content": reply})

            print()
    except KeyboardInterrupt:
        print(f"\n{DIM}Bye!{RESET}")


if __name__ == "__main__":
    main()
```

**Step 3: Add `chat` target to `Makefile`**

Add after the existing `format` target:

```makefile
chat:
	PYTHONPATH=src poetry run python -m spend_tracking.cli.chat
```

**Step 4: Run CI**

Run: `make ci`
Expected: PASS. The CLI module has no test file (interactive REPL), but lint/typecheck/format should pass.

**Step 5: Manual smoke test**

Run: `DATABASE_URL=<your-connection-string> ANTHROPIC_API_KEY=<your-key> make chat`
Expected: REPL starts, you can type a question, see tool calls + results + response with colors.

**Step 6: Commit**

```bash
git add src/spend_tracking/cli/__init__.py src/spend_tracking/cli/chat.py Makefile
git commit -m "feat: add local agent CLI with full trace logging"
```
