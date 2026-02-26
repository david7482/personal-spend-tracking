import json

import boto3
import psycopg2

from spend_tracking.domains.models import LineMessage
from spend_tracking.interfaces.line_message_repository import LineMessageRepository


class DbLineMessageRepository(LineMessageRepository):
    def __init__(self, ssm_parameter_name: str) -> None:
        ssm = boto3.client("ssm")
        response = ssm.get_parameter(
            Name=ssm_parameter_name,
            WithDecryption=True,
        )
        self._connection_string = response["Parameter"]["Value"]

    def save_line_message(self, message: LineMessage) -> None:
        with psycopg2.connect(self._connection_string) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO line_messages "
                "(line_user_id, message_type, message, reply_token, "
                "raw_event, timestamp, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "RETURNING id",
                (
                    message.line_user_id,
                    message.message_type,
                    message.message,
                    message.reply_token,
                    json.dumps(message.raw_event),
                    message.timestamp,
                    message.created_at,
                ),
            )
            row = cur.fetchone()
            assert row is not None
            message.id = row[0]
            conn.commit()
