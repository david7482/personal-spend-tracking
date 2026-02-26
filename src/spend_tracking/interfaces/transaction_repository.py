from abc import ABC, abstractmethod

from spend_tracking.domains.models import Transaction


class TransactionRepository(ABC):
    @abstractmethod
    def save_transactions(self, transactions: list[Transaction]) -> None: ...
