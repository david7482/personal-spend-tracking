import logging
from datetime import datetime, timezone
from email import message_from_bytes
from email.message import Message

from spend_tracking.shared.domain.models import Email
from spend_tracking.shared.interfaces.email_repository import EmailRepository
from spend_tracking.shared.interfaces.email_storage import EmailStorage

logger = logging.getLogger(__name__)


class ProcessEmail:
    def __init__(
        self,
        storage: EmailStorage,
        repository: EmailRepository,
    ) -> None:
        self._storage = storage
        self._repository = repository

    def execute(
        self,
        s3_key: str,
        address: str,
        sender: str,
        received_at: str,
    ) -> None:
        raw = self._storage.get_email_raw(s3_key)
        msg = message_from_bytes(raw)

        subject = msg.get("Subject")
        body_text = self._extract_body(msg, "text/plain")
        body_html = self._extract_body(msg, "text/html")

        email = Email(
            id=None,
            address=address,
            sender=sender,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            raw_s3_key=s3_key,
            received_at=datetime.fromisoformat(received_at),
            parsed_data=None,
            created_at=datetime.now(timezone.utc),
        )
        self._repository.save_email(email)
        logger.info("Saved email %s for %s", email.id, address)

    @staticmethod
    def _extract_body(msg: Message, content_type: str) -> str | None:
        if not msg.is_multipart():
            if msg.get_content_type() == content_type:
                payload = msg.get_payload(decode=True)
                return payload.decode(msg.get_content_charset("utf-8"))
            return None

        for part in msg.walk():
            if part.get_content_type() == content_type:
                payload = part.get_payload(decode=True)
                return payload.decode(part.get_content_charset("utf-8"))
        return None
