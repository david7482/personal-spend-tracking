from abc import ABC, abstractmethod
from dataclasses import dataclass

from spend_tracking.domains.models import Transaction


@dataclass
class ParseResult:
    parsed_data: dict
    transactions: list[Transaction]


class EmailParser(ABC):
    @abstractmethod
    def can_parse(self, to_address: str, subject: str) -> bool: ...

    @abstractmethod
    def parse(self, html: str, metadata: dict) -> ParseResult: ...
