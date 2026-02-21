from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass
class RegisteredAddress:
    id: int
    address: str
    prefix: str
    label: str | None
    is_active: bool
    created_at: datetime


@dataclass
class Email:
    id: int | None
    address: str
    sender: str
    subject: str | None
    body_html: str | None
    body_text: str | None
    raw_s3_key: str
    received_at: datetime
    parsed_data: dict | None
    created_at: datetime


@dataclass
class Transaction:
    id: int | None
    source_type: str
    source_id: int | None
    bank: str
    transaction_at: datetime
    region: str | None
    amount: Decimal
    currency: str
    merchant: str | None
    category: str | None
    notes: str | None
    raw_data: dict | None
    created_at: datetime
