from abc import ABC, abstractmethod

from spend_tracking.domains.models import LineMessage


class LineMessageRepository(ABC):
    @abstractmethod
    def save_line_message(self, message: LineMessage) -> None: ...
