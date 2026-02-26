import json
import logging
from urllib.request import Request, urlopen

from spend_tracking.domains.models import Transaction
from spend_tracking.interfaces.notification_sender import NotificationSender
from spend_tracking.lambdas.services.flex_message import build_flex_message

logger = logging.getLogger(__name__)

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"


class LineNotificationSender(NotificationSender):
    def __init__(self, channel_access_token: str) -> None:
        self._token = channel_access_token

    def send_transaction_notification(
        self,
        recipient_id: str,
        bank: str,
        transactions: list[Transaction],
    ) -> None:
        try:
            flex_contents = build_flex_message(bank, transactions)
            count = len(transactions)
            alt_text = f"{bank} - {count} transactions"

            payload = {
                "to": recipient_id,
                "messages": [
                    {
                        "type": "flex",
                        "altText": alt_text,
                        "contents": flex_contents,
                    }
                ],
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
                    "LINE notification sent",
                    extra={
                        "recipient_id": recipient_id,
                        "status": response.status,
                        "transaction_count": count,
                    },
                )
        except Exception:
            logger.exception(
                "LINE notification failed",
                extra={"recipient_id": recipient_id, "bank": bank},
            )
