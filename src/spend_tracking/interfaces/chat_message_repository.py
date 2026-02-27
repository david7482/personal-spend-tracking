from abc import ABC, abstractmethod

from spend_tracking.domains.models import ChatMessage


class ChatMessageRepository(ABC):
    @abstractmethod
    def save(self, message: ChatMessage) -> None: ...

    @abstractmethod
    def load_history(
        self, line_user_id: str, limit: int = 20
    ) -> list[ChatMessage]: ...

    @abstractmethod
    def get_by_id(self, message_id: int) -> ChatMessage | None: ...
