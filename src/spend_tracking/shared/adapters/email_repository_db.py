import json

import boto3
import psycopg2

from spend_tracking.shared.domain.models import Email, RegisteredAddress
from spend_tracking.shared.interfaces.email_repository import EmailRepository


class DbEmailRepository(EmailRepository):
    def __init__(self, ssm_parameter_name: str) -> None:
        ssm = boto3.client("ssm")
        response = ssm.get_parameter(
            Name=ssm_parameter_name,
            WithDecryption=True,
        )
        self._connection_string = response["Parameter"]["Value"]

    def get_registered_address(self, address: str) -> RegisteredAddress | None:
        with psycopg2.connect(self._connection_string) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT address, prefix, label, is_active, created_at "
                    "FROM registered_addresses WHERE address = %s",
                    (address,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return RegisteredAddress(
                    address=row[0],
                    prefix=row[1],
                    label=row[2],
                    is_active=row[3],
                    created_at=row[4],
                )

    def save_email(self, email: Email) -> None:
        with psycopg2.connect(self._connection_string) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO emails "
                    "(id, address, sender, subject, body_html, body_text, "
                    "raw_s3_key, received_at, parsed_data, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        str(email.id),
                        email.address,
                        email.sender,
                        email.subject,
                        email.body_html,
                        email.body_text,
                        email.raw_s3_key,
                        email.received_at,
                        json.dumps(email.parsed_data) if email.parsed_data else None,
                        email.created_at,
                    ),
                )
            conn.commit()
