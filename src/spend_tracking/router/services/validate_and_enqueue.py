import logging
from datetime import UTC
from email.parser import BytesHeaderParser
from email.utils import getaddresses, parsedate_to_datetime

from spend_tracking.shared.interfaces.email_queue import EmailQueue
from spend_tracking.shared.interfaces.email_repository import EmailRepository
from spend_tracking.shared.interfaces.email_storage import EmailStorage

logger = logging.getLogger(__name__)


class ValidateAndEnqueue:
    def __init__(
        self,
        storage: EmailStorage,
        repository: EmailRepository,
        queue: EmailQueue,
    ) -> None:
        self._storage = storage
        self._repository = repository
        self._queue = queue

    def execute(self, s3_key: str) -> bool:
        raw_headers = self._storage.get_email_headers(s3_key)

        parser = BytesHeaderParser()
        headers = parser.parsebytes(raw_headers)

        to_values = headers.get_all("To", [])
        delivered_to = headers.get_all("Delivered-To", [])
        all_recipients = getaddresses(to_values + delivered_to)

        for _, addr in all_recipients:
            registered = self._repository.get_registered_address(addr)
            if registered and registered.is_active:
                sender_values = headers.get_all("From", [])
                senders = getaddresses(sender_values)
                sender = senders[0][1] if senders else "unknown"

                date_str = headers.get("Date", "")
                try:
                    received_at = parsedate_to_datetime(date_str).isoformat()
                except Exception:
                    from datetime import datetime

                    received_at = datetime.now(UTC).isoformat()

                self._queue.send_message(
                    {
                        "s3_key": s3_key,
                        "address": addr,
                        "sender": sender,
                        "received_at": received_at,
                    }
                )
                logger.info(
                    "Enqueued email",
                    extra={"address": addr, "sender": sender, "s3_key": s3_key},
                )
                return True

        logger.warning("No registered address found", extra={"s3_key": s3_key})
        return False
