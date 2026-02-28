# Flex Message Chat Agent — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the LINE chat agent use Flex message format for data-rich responses and support multiple messages per push.

**Architecture:** Add a `format_response` beta_tool that builds Flex bubbles via closure accumulator. After the agent loop, `ProcessLineMessage` bundles Flex bubbles + trailing text into a single multi-message push API call (up to 5 messages).

**Tech Stack:** Python 3.12, Anthropic beta_tool, LINE Messaging API (Flex Message, Push Message)

---

### Task 1: Add `build_chat_flex_bubble` to flex_message.py

Build the Flex bubble JSON builder that converts `format_response` tool arguments (title + sections) into a LINE Flex bubble dict. This is the rendering engine for chat responses.

**Files:**
- Test: `src/spend_tracking/lambdas/services/flex_message_test.py`
- Modify: `src/spend_tracking/lambdas/services/flex_message.py`

**Step 1: Write failing tests for `build_chat_flex_bubble`**

Add to the bottom of `flex_message_test.py`:

```python
def test_build_chat_flex_bubble_key_value_section():
    from spend_tracking.lambdas.services.flex_message import build_chat_flex_bubble

    result = build_chat_flex_bubble(
        title="Monthly Summary",
        sections=[
            {
                "type": "key_value",
                "items": [
                    {"label": "Total", "value": "NT$12,345"},
                    {"label": "Count", "value": "15"},
                ],
            }
        ],
    )

    assert result["type"] == "bubble"
    assert result["size"] == "mega"

    # Header has title
    header_texts = [c["text"] for c in result["header"]["contents"]]
    assert header_texts[0] == "Monthly Summary"

    # Body has key_value rows
    body = result["body"]["contents"]
    assert len(body) == 2  # two k/v rows
    # First row: label on left, value on right
    assert body[0]["contents"][0]["text"] == "Total"
    assert body[0]["contents"][1]["text"] == "NT$12,345"


def test_build_chat_flex_bubble_table_section():
    from spend_tracking.lambdas.services.flex_message import build_chat_flex_bubble

    result = build_chat_flex_bubble(
        title="Top Merchants",
        sections=[
            {
                "type": "table",
                "headers": ["Merchant", "Amount"],
                "rows": [
                    ["7-ELEVEN", "NT$89"],
                    ["Starbucks", "NT$150"],
                ],
            }
        ],
    )

    body = result["body"]["contents"]
    # header row + separator + data row + separator + data row = 5
    assert len(body) == 5
    # Header row is bold
    assert body[0]["contents"][0]["weight"] == "bold"
    # Separators between rows
    assert body[1]["type"] == "separator"
    assert body[3]["type"] == "separator"
    # Data rows
    assert body[2]["contents"][0]["text"] == "7-ELEVEN"
    assert body[2]["contents"][1]["text"] == "NT$89"


def test_build_chat_flex_bubble_mixed_sections():
    from spend_tracking.lambdas.services.flex_message import build_chat_flex_bubble

    result = build_chat_flex_bubble(
        title="February Report",
        sections=[
            {
                "type": "key_value",
                "items": [{"label": "Total", "value": "NT$5,000"}],
            },
            {
                "type": "table",
                "headers": ["Category", "Amount"],
                "rows": [["Food", "NT$3,000"]],
            },
        ],
    )

    body = result["body"]["contents"]
    # 1 kv row + section_separator + header_row + separator + data_row = 5
    assert len(body) == 5
    # First item is key_value
    assert body[0]["contents"][0]["text"] == "Total"
    # Separator between sections
    assert body[1]["type"] == "separator"
```

**Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/lambdas/services/flex_message_test.py::test_build_chat_flex_bubble_key_value_section -v`
Expected: FAIL — `ImportError: cannot import name 'build_chat_flex_bubble'`

**Step 3: Implement `build_chat_flex_bubble`**

Add to the bottom of `flex_message.py`:

```python
def build_chat_flex_bubble(
    title: str, sections: list[dict[str, Any]]
) -> dict[str, Any]:
    """Build a Flex bubble for chat agent responses.

    Args:
        title: Bubble header text.
        sections: List of section dicts. Each must have a "type" key:
            - "key_value": {"items": [{"label": str, "value": str}, ...]}
            - "table": {"headers": [str, ...], "rows": [[str, ...], ...]}
    """
    return {
        "type": "bubble",
        "size": "mega",
        "header": _build_chat_header(title),
        "body": _build_chat_body(sections),
    }


def _build_chat_header(title: str) -> dict[str, Any]:
    return {
        "type": "box",
        "layout": "vertical",
        "contents": [
            {
                "type": "text",
                "text": title,
                "weight": "bold",
                "size": "lg",
                "color": "#FFFFFF",
            },
        ],
        "backgroundColor": "#4A6B8A",
        "paddingAll": "18px",
        "paddingStart": "20px",
    }


def _build_chat_body(sections: list[dict[str, Any]]) -> dict[str, Any]:
    contents: list[dict[str, Any]] = []
    for i, section in enumerate(sections):
        if i > 0:
            contents.append(
                {"type": "separator", "color": "#E0E0E0", "margin": "lg"}
            )
        section_type = section.get("type")
        if section_type == "key_value":
            contents.extend(_build_kv_rows(section.get("items", [])))
        elif section_type == "table":
            contents.extend(
                _build_table_rows(
                    section.get("headers", []), section.get("rows", [])
                )
            )
    return {
        "type": "box",
        "layout": "vertical",
        "spacing": "md",
        "paddingAll": "20px",
        "contents": contents,
    }


def _build_kv_rows(items: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in items:
        rows.append(
            {
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {
                        "type": "text",
                        "text": item.get("label", ""),
                        "size": "sm",
                        "color": "#8C8C8C",
                        "flex": 2,
                    },
                    {
                        "type": "text",
                        "text": item.get("value", ""),
                        "weight": "bold",
                        "size": "sm",
                        "color": "#2C3E50",
                        "align": "end",
                        "flex": 3,
                    },
                ],
            }
        )
    return rows


def _build_table_rows(
    headers: list[str], rows: list[list[str]]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    # Header row
    result.append(
        {
            "type": "box",
            "layout": "horizontal",
            "contents": [
                {
                    "type": "text",
                    "text": h,
                    "weight": "bold",
                    "size": "xs",
                    "color": "#8C8C8C",
                    "flex": 1,
                }
                for h in headers
            ],
        }
    )
    # Data rows with separators
    for row in rows:
        result.append({"type": "separator", "color": "#F0F0F0"})
        result.append(
            {
                "type": "box",
                "layout": "horizontal",
                "contents": [
                    {
                        "type": "text",
                        "text": cell,
                        "size": "sm",
                        "color": "#2C3E50",
                        "flex": 1,
                        "wrap": True,
                    }
                    for cell in row
                ],
            }
        )
    return result
```

**Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/lambdas/services/flex_message_test.py -v`
Expected: All tests PASS (both existing and new)

**Step 5: Commit**

```bash
git add src/spend_tracking/lambdas/services/flex_message.py src/spend_tracking/lambdas/services/flex_message_test.py
git commit -m "feat: add build_chat_flex_bubble for agent Flex responses"
```

---

### Task 2: Change `build_tools` to return tuple with flex_bubbles accumulator

Update `build_tools` to create a `format_response` beta_tool via closure and return `(tools, flex_bubbles)`.

**Files:**
- Test: `src/spend_tracking/lambdas/services/process_line_message_test.py`
- Modify: `src/spend_tracking/lambdas/services/agent.py`

**Step 1: Write failing tests for new `build_tools` return type and format_response tool**

Add to `process_line_message_test.py`:

```python
def test_build_tools_returns_tuple_with_flex_bubbles():
    from spend_tracking.lambdas.services.agent import build_tools

    result = build_tools("postgresql://fake")
    assert isinstance(result, tuple)
    assert len(result) == 2
    tools, flex_bubbles = result
    assert isinstance(tools, list)
    assert isinstance(flex_bubbles, list)
    assert len(flex_bubbles) == 0


def test_format_response_tool_populates_flex_bubbles():
    from spend_tracking.lambdas.services.agent import build_tools

    tools, flex_bubbles = build_tools("postgresql://fake")
    # Find the format_response tool
    fmt_tool = None
    for t in tools:
        if hasattr(t, "name") and t.name == "format_response":
            fmt_tool = t
            break
    assert fmt_tool is not None

    # Call it
    result = fmt_tool.func(
        title="Test Title",
        sections=[
            {
                "type": "key_value",
                "items": [{"label": "Total", "value": "NT$100"}],
            }
        ],
    )

    assert "Test Title" in result
    assert len(flex_bubbles) == 1
    assert flex_bubbles[0]["type"] == "bubble"
    assert flex_bubbles[0]["header"]["contents"][0]["text"] == "Test Title"
```

**Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/lambdas/services/process_line_message_test.py::test_build_tools_returns_tuple_with_flex_bubbles -v`
Expected: FAIL — `result` is a list, not a tuple

**Step 3: Update `build_tools` in agent.py**

Change the `build_tools` function:

```python
def build_tools(db_connection_string: str) -> tuple[list, list[dict]]:
    """Build the agent's tool list and flex message accumulator."""
    from spend_tracking.lambdas.services.flex_message import build_chat_flex_bubble

    flex_bubbles: list[dict] = []

    @beta_tool
    def format_response(title: str, sections: list[dict]) -> str:  # type: ignore[type-arg]
        """Format a rich response as a visual card in the chat.

        Use this for data-rich responses like spending summaries, transaction
        lists, or category breakdowns. Each call creates one visual card.
        You can call this up to 4 times per response.

        Skip this for simple conversational replies (greetings, clarifications,
        follow-up questions) — just respond with plain text instead.

        Args:
            title: Card header text (e.g. "February Spending", "Top Merchants").
            sections: List of content sections. Each section is a dict with a
                "type" key and type-specific fields:

                key_value — label/value pairs for summary stats:
                  {"type": "key_value",
                   "items": [{"label": "Total", "value": "NT$12,345"}, ...]}

                table — rows with column headers for lists:
                  {"type": "table",
                   "headers": ["Merchant", "Amount"],
                   "rows": [["7-ELEVEN", "NT$89"], ...]}

        Returns:
            Confirmation string.
        """
        bubble = build_chat_flex_bubble(title, sections)
        flex_bubbles.append(bubble)
        return f"Formatted: {title}"

    return [
        get_current_datetime,
        _make_query_db_tool(db_connection_string),
        format_response,
        {"type": "code_execution_20260120", "name": "code_execution"},
    ], flex_bubbles
```

**Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/lambdas/services/process_line_message_test.py::test_build_tools_returns_tuple_with_flex_bubbles src/spend_tracking/lambdas/services/process_line_message_test.py::test_format_response_tool_populates_flex_bubbles -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/spend_tracking/lambdas/services/agent.py src/spend_tracking/lambdas/services/process_line_message_test.py
git commit -m "feat: add format_response tool with closure accumulator to build_tools"
```

---

### Task 3: Add `send_messages` to LinePushSender

Add a multi-message push method alongside the existing `send_text`.

**Files:**
- Test: `src/spend_tracking/lambdas/services/process_line_message_test.py`
- Modify: `src/spend_tracking/lambdas/services/process_line_message.py`

**Step 1: Write failing test for `send_messages`**

Add to `process_line_message_test.py`:

```python
import json
from unittest.mock import patch


@patch("spend_tracking.lambdas.services.process_line_message.urlopen")
def test_send_messages_posts_multiple_messages(mock_urlopen):
    from spend_tracking.lambdas.services.process_line_message import LinePushSender

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_response

    sender = LinePushSender(channel_access_token="test-token")
    messages = [
        {"type": "flex", "altText": "Summary", "contents": {"type": "bubble"}},
        {"type": "text", "text": "Hello"},
    ]
    sender.send_messages("U123", messages)

    mock_urlopen.assert_called_once()
    request = mock_urlopen.call_args[0][0]
    body = json.loads(request.data)
    assert body["to"] == "U123"
    assert len(body["messages"]) == 2
    assert body["messages"][0]["type"] == "flex"
    assert body["messages"][1]["type"] == "text"
```

**Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/lambdas/services/process_line_message_test.py::test_send_messages_posts_multiple_messages -v`
Expected: FAIL — `LinePushSender has no attribute 'send_messages'`

**Step 3: Add `send_messages` to LinePushSender**

In `process_line_message.py`, add the `urlopen`/`Request` import at the top of the file (move from inside `send_text`) and add the new method:

Change the import section at the top (add `from urllib.request import Request, urlopen`) and update `LinePushSender`:

```python
from urllib.request import Request, urlopen

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
MAX_LINE_MESSAGES = 5


class LinePushSender:
    """Sends messages via LINE Push API."""

    def __init__(self, channel_access_token: str) -> None:
        self._token = channel_access_token

    def send_text(self, line_user_id: str, text: str) -> None:
        self.send_messages(line_user_id, [{"type": "text", "text": text}])

    def send_messages(self, line_user_id: str, messages: list[dict]) -> None:
        payload = {
            "to": line_user_id,
            "messages": messages[:MAX_LINE_MESSAGES],
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
                "LINE push sent",
                extra={
                    "line_user_id": line_user_id,
                    "status": response.status,
                    "message_count": len(messages),
                },
            )
```

Remove the old `from urllib.request import Request, urlopen` that was inside `send_text`.

**Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/lambdas/services/process_line_message_test.py -v`
Expected: All tests PASS. The existing `test_execute_*` tests still use `send_text` via mock, so they remain valid.

**Step 5: Commit**

```bash
git add src/spend_tracking/lambdas/services/process_line_message.py src/spend_tracking/lambdas/services/process_line_message_test.py
git commit -m "feat: add send_messages multi-message push to LinePushSender"
```

---

### Task 4: Update ProcessLineMessage to assemble Flex + text messages

Wire the flex_bubbles accumulator and `send_messages` into the execute flow.

**Files:**
- Test: `src/spend_tracking/lambdas/services/process_line_message_test.py`
- Modify: `src/spend_tracking/lambdas/services/process_line_message.py`

**Step 1: Write failing tests for Flex message assembly**

Add to `process_line_message_test.py`:

```python
def test_execute_sends_flex_and_text_when_format_response_used():
    from spend_tracking.lambdas.services.process_line_message import (
        ProcessLineMessage,
    )

    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = _make_user_message()
    mock_repo.load_history.return_value = []

    mock_final_message = MagicMock()
    mock_final_message.content = [MagicMock(type="text", text="Summary text")]
    mock_final_message.model = "claude-opus-4-6"
    mock_final_message.stop_reason = "end_turn"
    mock_final_message.usage = MagicMock(input_tokens=100, output_tokens=50)

    mock_runner = MagicMock()
    mock_runner.__iter__ = MagicMock(return_value=iter([mock_final_message]))

    mock_client = MagicMock()
    mock_client.beta.messages.tool_runner.return_value = mock_runner

    mock_push = MagicMock()

    # Pre-populate flex_bubbles to simulate format_response calls
    fake_bubble = {"type": "bubble", "header": {"contents": [{"text": "Test"}]}}

    service = ProcessLineMessage(
        client=mock_client,
        model="claude-opus-4-6",
        chat_message_repository=mock_repo,
        line_push_sender=mock_push,
        db_connection_string="postgresql://fake",
    )

    # Monkey-patch build_tools to return pre-populated flex_bubbles
    import spend_tracking.lambdas.services.process_line_message as plm

    original_build_tools = plm.build_tools
    plm.build_tools = lambda conn: (original_build_tools(conn)[0], [fake_bubble])
    try:
        service.execute(chat_message_id=42)
    finally:
        plm.build_tools = original_build_tools

    mock_push.send_messages.assert_called_once()
    messages = mock_push.send_messages.call_args[0][1]
    assert len(messages) == 2
    assert messages[0]["type"] == "flex"
    assert messages[1]["type"] == "text"
    assert messages[1]["text"] == "Summary text"

    # DB still saves text content
    saved = mock_repo.save.call_args[0][0]
    assert saved.content == "Summary text"


def test_execute_sends_text_only_when_no_flex():
    """When agent doesn't use format_response, falls back to text-only."""
    from spend_tracking.lambdas.services.process_line_message import (
        ProcessLineMessage,
    )

    mock_repo = MagicMock()
    mock_repo.get_by_id.return_value = _make_user_message()
    mock_repo.load_history.return_value = []

    mock_final_message = MagicMock()
    mock_final_message.content = [MagicMock(type="text", text="Simple reply")]
    mock_final_message.model = "claude-opus-4-6"
    mock_final_message.stop_reason = "end_turn"
    mock_final_message.usage = MagicMock(input_tokens=100, output_tokens=50)

    mock_runner = MagicMock()
    mock_runner.__iter__ = MagicMock(return_value=iter([mock_final_message]))

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

    # Should use send_messages with text only
    mock_push.send_messages.assert_called_once()
    messages = mock_push.send_messages.call_args[0][1]
    assert len(messages) == 1
    assert messages[0]["type"] == "text"
```

**Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/lambdas/services/process_line_message_test.py::test_execute_sends_flex_and_text_when_format_response_used -v`
Expected: FAIL — `ProcessLineMessage.execute` still calls `send_text`, not `send_messages`

**Step 3: Update `ProcessLineMessage.execute`**

In `process_line_message.py`, update the `execute` method to use `build_tools` tuple return and assemble messages:

```python
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
            tools, flex_bubbles = build_tools(self._db_connection_string)
            final_message = None
            for message in run_agent(self._client, self._model, tools, messages):
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
            flex_bubbles = []

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

        line_messages = _assemble_line_messages(flex_bubbles, reply_text)
        self._push.send_messages(user_msg.line_user_id, line_messages)

        logger.info(
            "Processed LINE message",
            extra={
                "chat_message_id": chat_message_id,
                "assistant_message_id": assistant_msg.id,
                "reply_length": len(reply_text),
                "flex_count": len(flex_bubbles),
            },
        )
```

Add the `_assemble_line_messages` helper:

```python
def _assemble_line_messages(
    flex_bubbles: list[dict], reply_text: str
) -> list[dict]:
    """Bundle Flex bubbles and text into a LINE messages array (max 5)."""
    messages: list[dict] = []
    for bubble in flex_bubbles:
        title = bubble.get("header", {}).get("contents", [{}])[0].get("text", "Info")
        messages.append(
            {"type": "flex", "altText": title, "contents": bubble}
        )
    messages.append({"type": "text", "text": reply_text})
    return messages[:MAX_LINE_MESSAGES]
```

**Step 4: Update existing test to match new API**

The existing `test_execute_loads_message_runs_agent_saves_and_pushes` test asserts `send_text`. Update it to assert `send_messages` instead:

Change line:
```python
    mock_push.send_text.assert_called_once_with("U123", "Agent reply")
```
To:
```python
    mock_push.send_messages.assert_called_once()
    sent_messages = mock_push.send_messages.call_args[0][1]
    assert len(sent_messages) == 1
    assert sent_messages[0] == {"type": "text", "text": "Agent reply"}
```

Also update `test_execute_handles_api_error_sends_fallback`:

Change lines:
```python
    mock_push.send_text.assert_called_once()
    fallback_text = mock_push.send_text.call_args[0][1]
    assert "try again" in fallback_text.lower() or "trouble" in fallback_text.lower()
```
To:
```python
    mock_push.send_messages.assert_called_once()
    sent_messages = mock_push.send_messages.call_args[0][1]
    assert len(sent_messages) == 1
    fallback_text = sent_messages[0]["text"]
    assert "try again" in fallback_text.lower() or "trouble" in fallback_text.lower()
```

**Step 5: Run all tests to verify they pass**

Run: `PYTHONPATH=src poetry run pytest src/spend_tracking/lambdas/services/process_line_message_test.py -v`
Expected: All tests PASS

**Step 6: Commit**

```bash
git add src/spend_tracking/lambdas/services/process_line_message.py src/spend_tracking/lambdas/services/process_line_message_test.py
git commit -m "feat: assemble Flex bubbles + text in ProcessLineMessage"
```

---

### Task 5: Update CLI to handle new build_tools return type

The CLI calls `build_tools` and needs to destructure the tuple. It ignores `flex_bubbles`.

**Files:**
- Modify: `src/spend_tracking/cli/chat.py`

**Step 1: Update CLI to destructure build_tools tuple**

In `chat.py` line 121, change:

```python
    tools = build_tools(db_url)
```
To:
```python
    tools, _flex_bubbles = build_tools(db_url)
```

**Step 2: Run lint and typecheck**

Run: `PYTHONPATH=src poetry run ruff check src/spend_tracking/cli/chat.py && PYTHONPATH=src poetry run mypy`
Expected: No errors

**Step 3: Commit**

```bash
git add src/spend_tracking/cli/chat.py
git commit -m "fix: update CLI for new build_tools tuple return type"
```

---

### Task 6: Update system prompt with format_response guidance

Add instructions telling the agent when and how to use `format_response`.

**Files:**
- Modify: `src/spend_tracking/lambdas/services/agent.py`

**Step 1: Update SYSTEM_PROMPT**

Change `SYSTEM_PROMPT` in `agent.py`:

```python
SYSTEM_PROMPT = """\
You are a personal finance assistant. You help the user understand their spending \
by querying their transaction database and performing calculations.

Always respond in the same language the user writes in.

Guidelines:
- Keep responses concise (this is a chat app, not a report).
- Use query_db to look up real transaction data first.
- Use code_execution for calculations or formatting.
- When showing monetary values, include the currency symbol.
- If the user's question is unclear, ask for clarification.
- Use format_response for data-rich answers (spending summaries, transaction \
lists, category breakdowns). You can call it up to 4 times per response.
- For simple replies (greetings, clarifications, follow-ups), just use plain text.\
"""
```

**Step 2: Run full CI**

Run: `make ci`
Expected: All checks pass (lint, format, typecheck, test, build)

**Step 3: Commit**

```bash
git add src/spend_tracking/lambdas/services/agent.py
git commit -m "feat: update system prompt with format_response guidance"
```
