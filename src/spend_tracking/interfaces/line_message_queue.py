from abc import ABC, abstractmethod


class LineMessageQueue(ABC):
    @abstractmethod
    def send_message(self, message: dict) -> None: ...
