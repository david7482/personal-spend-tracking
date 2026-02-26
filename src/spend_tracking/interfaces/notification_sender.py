from abc import ABC, abstractmethod

from spend_tracking.domains.models import Transaction


class NotificationSender(ABC):
    @abstractmethod
    def send_transaction_notification(
        self,
        recipient_id: str,
        bank: str,
        transactions: list[Transaction],
    ) -> None: ...
