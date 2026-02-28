from decimal import Decimal
from typing import Any

from spend_tracking.domains.models import Transaction

_CURRENCY_SYMBOLS: dict[str, str] = {
    "TWD": "NT$",
    "USD": "US$",
    "JPY": "JPY ",
}


def _format_currency(currency: str, amount: Decimal) -> str:
    symbol = _CURRENCY_SYMBOLS.get(currency, f"{currency}$")
    return f"{symbol}{amount:,.0f}"


def build_flex_message(bank: str, transactions: list[Transaction]) -> dict[str, Any]:
    count = len(transactions)
    date_str = transactions[0].transaction_at.strftime("%Y/%m/%d")
    total = sum((t.amount for t in transactions), Decimal(0))
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
                "text": bank,
                "weight": "bold",
                "size": "lg",
                "color": "#FFFFFF",
            },
            {
                "type": "text",
                "text": f"{count} transactions - {date_str}",
                "size": "xs",
                "color": "#FFFFFFAA",
                "margin": "sm",
            },
        ],
        "backgroundColor": "#4A6B8A",
        "paddingAll": "18px",
        "paddingStart": "20px",
    }


def _build_body(
    transactions: list[Transaction],
) -> dict[str, Any]:
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
    merchant = txn.merchant or "-"
    date_str = txn.transaction_at.strftime("%m/%d")
    metadata = f"{txn.category} - {date_str}" if txn.category else date_str

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
                "text": _format_currency(txn.currency, txn.amount),
                "weight": "bold",
                "size": "md",
                "color": "#2C3E50",
                "align": "end",
                "gravity": "center",
                "flex": 2,
            },
        ],
    }


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
            contents.append({"type": "separator", "color": "#E0E0E0", "margin": "lg"})
        section_type = section.get("type")
        if section_type == "key_value":
            contents.extend(_build_kv_rows(section.get("items", [])))
        elif section_type == "table":
            contents.extend(
                _build_table_rows(section.get("headers", []), section.get("rows", []))
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


def _build_footer(currency: str, total: Decimal) -> dict[str, Any]:
    return {
        "type": "box",
        "layout": "horizontal",
        "contents": [
            {
                "type": "text",
                "text": "Total",
                "size": "sm",
                "color": "#8C8C8C",
                "gravity": "center",
            },
            {
                "type": "text",
                "text": _format_currency(currency, total),
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
