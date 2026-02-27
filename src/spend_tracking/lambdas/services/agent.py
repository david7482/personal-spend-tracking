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
