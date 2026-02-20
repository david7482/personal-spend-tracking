from abc import ABC, abstractmethod


class EmailStorage(ABC):
    @abstractmethod
    def get_email_headers(self, s3_key: str) -> bytes:
        ...

    @abstractmethod
    def get_email_raw(self, s3_key: str) -> bytes:
        ...
