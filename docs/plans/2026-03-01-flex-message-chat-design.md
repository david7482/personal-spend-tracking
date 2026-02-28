# Flex Message Chat Agent — Design

## Goal

Improve the LINE chat agent's readability by using Flex message format for data-rich responses and supporting multiple messages (up to 5) per push API call.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| How agent produces Flex output | `format_response` tool | Agent explicitly controls when to use rich formatting vs plain text |
| Plain text fallback | Keep as LINE text message | Simple replies stay as text; only `format_response` calls produce Flex bubbles |
| Section types | `key_value`, `table` | Covers finance use cases (summaries, transaction lists, breakdowns) |
| Multi-message strategy | One `format_response` call = one Flex bubble | Agent can call it multiple times; all bubbles + trailing text bundled into one push (up to 5) |
| Flex JSON construction | Closure accumulator in `build_tools` | Tool function appends built Flex JSON to a shared list; caller holds reference — no message scanning needed |
| Conversation history | Text-only | DB stores the text portion of replies; Flex formatting is presentation-only |

## Architecture

### format_response Tool

A `beta_tool` function created inside `build_tools` via closure. The agent calls it to declare structured data for rich display.

**Signature:**
```
format_response(title: str, sections: list[dict]) -> str
```

**Section types:**
- `{"type": "key_value", "items": [{"label": "Total", "value": "NT$12,345"}, ...]}`
- `{"type": "table", "headers": ["Merchant", "Amount"], "rows": [["7-ELEVEN", "NT$89"], ...]}`

**Behavior:** Builds a Flex bubble JSON dict from the arguments, appends it to a `flex_bubbles: list[dict]` captured by closure, returns a short ack string (e.g. `"Formatted: {title}"`).

### build_tools Signature Change

```python
def build_tools(db_connection_string: str) -> tuple[list, list[dict]]:
    flex_bubbles: list[dict] = []
    # ... format_response tool appends to flex_bubbles ...
    return [tools...], flex_bubbles
```

Callers (`ProcessLineMessage`, CLI) receive both the tool list and the accumulator.

### Flex Bubble Builder

New function in `flex_message.py`:

```
build_chat_flex_bubble(title: str, sections: list[dict]) -> dict
```

Converts tool arguments into a LINE Flex bubble:
- **Header:** Title text on colored background (`#4A6B8A`, consistent with existing transaction notifications)
- **Body:** Iterates sections:
  - `key_value`: Horizontal box per item — label (gray, left) + value (bold, right)
  - `table`: Header row (bold) + data rows with separators between them

### Push Sender Changes

`LinePushSender` gets a new method:

```python
def send_messages(self, line_user_id: str, messages: list[dict]) -> None:
```

Accepts a list of LINE message dicts (`{"type": "flex", ...}` or `{"type": "text", ...}`), up to 5. Posts to `https://api.line.me/v2/bot/message/push`. Existing `send_text` remains for backward compatibility.

### ProcessLineMessage Changes

After the agent loop:
1. Collect `flex_bubbles` from the closure (already built as Flex JSON dicts)
2. Extract trailing text via `extract_text(final_message)`
3. Build message list:
   - Each flex bubble → `{"type": "flex", "altText": title, "contents": bubble}`
   - Text (if non-fallback and flex bubbles exist, or always if no flex bubbles) → `{"type": "text", "text": text}`
4. Truncate to 5 messages max
5. Send via `send_messages()`
6. Save the text portion to DB as the `assistant` chat message

### System Prompt Update

Add to the agent's system prompt:
- Use `format_response` for data-rich responses (spending summaries, transaction lists, category breakdowns)
- Skip it for simple conversational replies (greetings, clarifications, follow-up questions)
- Can call it multiple times (up to 4 bubbles, leaving room for a trailing text message)

### CLI Impact

The local CLI (`cli/chat.py`) calls `build_tools` too. It receives the updated return type but ignores `flex_bubbles` — the CLI only prints the text response as before.

## Data Flow

```
User asks "How much did I spend this month?"
    ↓
Agent calls: get_current_datetime() → knows today
Agent calls: query_db("SELECT ...") → gets transaction data
Agent calls: format_response(title="February Spending", sections=[
    {"type": "key_value", "items": [{"label": "Total", "value": "NT$12,345"}, ...]},
    {"type": "table", "headers": ["Category", "Amount"], "rows": [...]}
])
    → closure appends Flex bubble to flex_bubbles list
    → returns "Formatted: February Spending"
Agent produces text: "You spent NT$12,345 in February, mostly on dining."
    ↓
ProcessLineMessage:
    flex_bubbles = [bubble_dict]
    text = "You spent NT$12,345 in February, mostly on dining."
    messages = [
        {"type": "flex", "altText": "February Spending", "contents": bubble_dict},
        {"type": "text", "text": "You spent NT$12,345 in February..."}
    ]
    → single push API call with 2 messages
    → save text to DB as assistant message
```

## Testing

- `flex_message_test.py`: Test `build_chat_flex_bubble` with key_value and table sections, verify Flex JSON structure
- `agent_test.py` (or existing `process_line_message_test.py`): Test `build_tools` returns tuple, test `format_response` tool populates flex_bubbles list
- `process_line_message_test.py`: Test message assembly (flex + text), test text-only fallback, test 5-message truncation
- `notification_sender_line_test.py` (or inline): Test `send_messages` posts correct payload
