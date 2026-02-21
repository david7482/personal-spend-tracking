import logging
from datetime import UTC, datetime
from email import message_from_bytes
from email.header import decode_header
from email.message import Message

from spend_tracking.shared.domain.models import Email
from spend_tracking.shared.interfaces.email_repository import EmailRepository
from spend_tracking.shared.interfaces.email_storage import EmailStorage
from spend_tracking.shared.interfaces.transaction_repository import (
    TransactionRepository,
)
from spend_tracking.worker.services.parsers import find_parser

logger = logging.getLogger(__name__)


class ProcessEmail:
    def __init__(
        self,
        storage: EmailStorage,
        repository: EmailRepository,
        transaction_repository: TransactionRepository,
    ) -> None:
        self._storage = storage
        self._repository = repository
        self._transaction_repository = transaction_repository

    def execute(
        self,
        s3_key: str,
        address: str,
        sender: str,
        received_at: str,
    ) -> None:
        raw = self._storage.get_email_raw(s3_key)
        msg = message_from_bytes(raw)

        subject = self._decode_header(msg.get("Subject"))
        body_text = self._extract_body(msg, "text/plain")
        body_html = self._extract_body(msg, "text/html")

        parsed_data = None
        transactions = []

        parser = find_parser(address, subject or "")
        if parser and body_html:
            try:
                result = parser.parse(body_html, {"received_at": received_at})
                parsed_data = result.parsed_data
                transactions = result.transactions
            except Exception:
                logger.exception(
                    "Parser failed for %s, falling back",
                    address,
                )

        email = Email(
            id=None,
            address=address,
            sender=sender,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            raw_s3_key=s3_key,
            received_at=datetime.fromisoformat(received_at),
            parsed_data=parsed_data,
            created_at=datetime.now(UTC),
        )
        self._repository.save_email(email)
        logger.info(
            "Saved email",
            extra={"email_id": email.id, "address": address, "s3_key": s3_key},
        )

        if transactions:
            for txn in transactions:
                txn.source_id = email.id
            self._transaction_repository.save_transactions(transactions)
            logger.info(
                "Saved %d transactions for email %s",
                len(transactions),
                email.id,
            )

    @staticmethod
    def _decode_header(value: str | None) -> str | None:
        if value is None:
            return None
        parts = decode_header(value)
        decoded = []
        for data, charset in parts:
            if isinstance(data, bytes):
                decoded.append(data.decode(charset or "utf-8", errors="replace"))
            else:
                decoded.append(data)
        return "".join(decoded)

    @staticmethod
    def _extract_body(msg: Message, content_type: str) -> str | None:
        if not msg.is_multipart():
            if msg.get_content_type() == content_type:
                payload: bytes | None = msg.get_payload(decode=True)  # type: ignore[assignment]
                if payload is None:
                    return None
                return payload.decode(msg.get_content_charset("utf-8"))
            return None

        for part in msg.walk():
            if part.get_content_type() == content_type:
                payload = part.get_payload(decode=True)  # type: ignore[assignment]
                if payload is None:
                    return None
                return payload.decode(part.get_content_charset("utf-8"))
        return None
