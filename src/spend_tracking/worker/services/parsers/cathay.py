import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html.parser import HTMLParser

from spend_tracking.shared.domain.models import Transaction
from spend_tracking.shared.interfaces.email_parser import EmailParser, ParseResult

TAIPEI_TZ = timezone(timedelta(hours=8))
CATHAY_ADDRESS_PREFIX = "cathay-"


class _TableCellExtractor(HTMLParser):
    """Extracts text content from all <td> elements."""

    def __init__(self) -> None:
        super().__init__()
        self.cells: list[str] = []
        self._in_td = False
        self._current = ""
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "td":
            self._in_td = True
            self._current = ""
        elif tag in ("style", "script"):
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._in_td:
            self._in_td = False
            self.cells.append(self._current.strip())
        elif tag in ("style", "script"):
            self._skip = False

    def handle_data(self, data: str) -> None:
        if self._in_td and not self._skip:
            self._current += data

    def handle_entityref(self, name: str) -> None:
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
