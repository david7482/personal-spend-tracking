from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass
class RegisteredAddress:
    address: str
    prefix: str
    label: str | None
    is_active: bool
    created_at: datetime


@dataclass
class Email:
    id: UUID
    address: str
    sender: str
    subject: str | None
    body_html: str | None
    body_text: str | None
    raw_s3_key: str
    received_at: datetime
    parsed_data: dict | None
    created_at: datetime
