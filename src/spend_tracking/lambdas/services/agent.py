import json
from collections.abc import Generator
from datetime import timedelta, timezone

import psycopg2
from anthropic import Anthropic, beta_tool

USER_TZ = timezone(timedelta(hours=8))

SYSTEM_PROMPT = """\
You are a personal finance assistant. You help the user understand their spending \
by querying their transaction database and performing calculations.

Always respond in the same language the user writes in. If the user writes in \
Chinese, use Traditional Chinese (繁體中文), not Simplified Chinese.

Guidelines:
- Keep responses concise (this is a chat app, not a report).
- Use query_db to look up real transaction data first.
- Use code_execution for calculations or formatting.
- When showing monetary values, include the currency symbol.
- If the user's question is unclear, ask for clarification.
- Use format_response for data-rich answers (spending summaries, transaction \
lists, category breakdowns). You can call it up to 4 times per response.
- For simple replies (greetings, clarifications, follow-ups), just use plain text.
- Never use Markdown formatting (bold, italic, headers, bullet lists, etc.) in \
plain text responses — LINE cannot render it. Use plain text only.\
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

        Timezone: The user is in UTC+8 (Asia/Taipei). transaction_at is stored
        in UTC. When filtering by date (e.g. "yesterday", "today"), use
        timezone-aware literals. Example for "yesterday" in UTC+8:
          WHERE transaction_at >= '2026-02-27 00:00+08'
            AND transaction_at < '2026-02-28 00:00+08'

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


@beta_tool
def get_current_datetime() -> str:
    """Get the current date and time in the user's timezone (Asia/Taipei, UTC+8).

    Call this before constructing date-based SQL queries so you know
    what "today", "yesterday", "this week", etc. mean.

    Returns:
        JSON with current date, datetime, and timezone offset.
    """
    from datetime import datetime as dt

    now = dt.now(USER_TZ)
    return json.dumps(
        {
            "date": now.strftime("%Y-%m-%d"),
            "datetime": now.isoformat(),
            "timezone": "Asia/Taipei (UTC+8)",
            "weekday": now.strftime("%A"),
        }
    )


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
    yield from runner
