import json

import boto3
import psycopg2

from spend_tracking.domains.models import ChatMessage
from spend_tracking.interfaces.chat_message_repository import ChatMessageRepository


class DbChatMessageRepository(ChatMessageRepository):
    def __init__(self, ssm_parameter_name: str) -> None:
        ssm = boto3.client("ssm")
        response = ssm.get_parameter(
            Name=ssm_parameter_name,
            WithDecryption=True,
        )
        self._connection_string = response["Parameter"]["Value"]

    def save(self, message: ChatMessage) -> None:
        with psycopg2.connect(self._connection_string) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO chat_messages "
                "(line_user_id, role, content, message_type, "
                "raw_event, timestamp, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "RETURNING id",
                (
                    message.line_user_id,
                    message.role,
                    message.content,
                    message.message_type,
                    json.dumps(message.raw_event) if message.raw_event else None,
                    message.timestamp,
                    message.created_at,
                ),
            )
            row = cur.fetchone()
            assert row is not None
            message.id = row[0]
            conn.commit()

    def load_history(
        self, line_user_id: str, limit: int = 20
    ) -> list[ChatMessage]:
        with psycopg2.connect(self._connection_string) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, line_user_id, role, content, message_type, "
                "raw_event, timestamp, created_at "
                "FROM chat_messages "
                "WHERE line_user_id = %s "
                "ORDER BY created_at DESC "
                "LIMIT %s",
                (line_user_id, limit),
            )
            rows = cur.fetchall()
        return [
            ChatMessage(
                id=row[0],
                line_user_id=row[1],
                role=row[2],
                content=row[3],
                message_type=row[4],
                raw_event=row[5],
                timestamp=row[6],
                created_at=row[7],
            )
            for row in reversed(rows)  # reverse to get chronological order
        ]

    def get_by_id(self, message_id: int) -> ChatMessage | None:
        with psycopg2.connect(self._connection_string) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id, line_user_id, role, content, message_type, "
                "raw_event, timestamp, created_at "
                "FROM chat_messages WHERE id = %s",
                (message_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return ChatMessage(
            id=row[0],
            line_user_id=row[1],
            role=row[2],
            content=row[3],
            message_type=row[4],
            raw_event=row[5],
            timestamp=row[6],
            created_at=row[7],
        )
