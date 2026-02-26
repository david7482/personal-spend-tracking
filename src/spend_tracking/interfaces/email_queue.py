from abc import ABC, abstractmethod


class EmailQueue(ABC):
    @abstractmethod
    def send_message(self, message: dict) -> None: ...
