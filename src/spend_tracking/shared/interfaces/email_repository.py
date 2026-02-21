from abc import ABC, abstractmethod

from spend_tracking.shared.domain.models import Email, RegisteredAddress


class EmailRepository(ABC):
    @abstractmethod
    def get_registered_address(self, address: str) -> RegisteredAddress | None: ...

    @abstractmethod
    def save_email(self, email: Email) -> None: ...
