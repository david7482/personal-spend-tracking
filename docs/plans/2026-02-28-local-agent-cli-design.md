# Local Agent CLI — Design

## Goal

Run the same AI spending assistant locally in a terminal REPL, with full trace logging of agent internals (tool calls, results, token usage) for debugging.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Architecture | Refactor shared agent core, CLI + LINE both consume it | Single source of truth for prompt, tools, runner logic |
| Conversation history | In-memory (local only) | No DB side effects; separate from LINE conversations |
| DB connection | `DATABASE_URL` env var | Simple, no AWS dependency for local dev |
| Anthropic key | `ANTHROPIC_API_KEY` env var | Standard Anthropic SDK convention |
| Entry point | `make chat` | Consistent with existing Makefile commands |
| Logging | ANSI-colored full trace to stdout | No external dependencies; easy to read |
| Agent interface | Generator yielding raw messages | Single iteration point; both consumers get intermediate access |

## Architecture

### New module: `agent.py`

`src/spend_tracking/lambdas/services/agent.py` — shared agent core.

Exports:
- `SYSTEM_PROMPT`, `FALLBACK_MESSAGE` — constants
- `build_tools(db_connection_string) -> list` — returns query_db + code_execution tools
- `run_agent(client, model, tools, messages) -> Generator` — yields each raw Anthropic message from tool_runner
- `extract_text(message) -> str` — pulls text content from a response message

Internal helpers: `_validate_sql()`, `_make_query_db_tool()`.

### Modified: `process_line_message.py`

Removes duplicated code (prompt, tools, SQL validation, text extraction). Imports from `agent.py`. `_build_messages()` stays here since it converts `ChatMessage` domain objects — CLI doesn't use this.

### New: `cli/chat.py`

`src/spend_tracking/cli/chat.py` — interactive REPL.

- Reads `DATABASE_URL` and `ANTHROPIC_API_KEY` from environment
- Maintains in-memory `messages: list[dict]` for conversation history
- On each user input: calls `run_agent()`, iterates yielded messages, prints full trace
- Appends final assistant text to history
- Exits on Ctrl+C / Ctrl+D

## Data Flow

```
cli/chat.py                          process_line_message.py
    |                                        |
    |  build_tools(conn_str)                 |  build_tools(conn_str)
    |  run_agent(client, model, tools, msgs) |  run_agent(...)
    |       |                                |       |
    |       v                                |       v
    |   agent.py (generator)                 |   agent.py (generator)
    |       |                                |       |
    |  print each message                    |  keep last, extract text
    |  with full trace                       |  save to DB, push to LINE
    v                                        v
 terminal output                       LINE reply
```

## CLI Output Format

```
You: How much did I spend last week?

-- Tool: query_db ---------------------
SELECT ... FROM transactions WHERE ...

-- Result -----------------------------
[{"amount": 150.00, "merchant": "7-11"}, ...]

-- Response ---------------------------
Last week you spent NT$1,234 across 8 transactions...

-- Meta -------------------------------
model: claude-opus-4-6 | tokens: 1,204 in / 287 out
```

Uses ANSI colors to distinguish sections. No external dependencies.

## Testing

- `agent.py`: unit tests for `run_agent()` (mocked client), `build_tools()`, `extract_text()`
- `process_line_message.py`: existing tests updated for refactored imports
- `cli/chat.py`: manual testing only (interactive REPL)
