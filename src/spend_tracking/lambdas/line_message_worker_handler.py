import json
import logging
import os

import boto3
from anthropic import Anthropic

from spend_tracking.adapters.chat_message_repository_db import (
    DbChatMessageRepository,
)
from spend_tracking.lambdas.services.process_line_message import (
    LinePushSender,
    ProcessLineMessage,
)

logger = logging.getLogger()

_ssm = boto3.client("ssm")

_secrets = _ssm.get_parameters(
    Names=[
        os.environ["SSM_ANTHROPIC_API_KEY"],
        os.environ["SSM_LINE_CHANNEL_ACCESS_TOKEN"],
        os.environ["SSM_DB_CONNECTION_STRING"],
    ],
    WithDecryption=True,
)
_params = {p["Name"]: p["Value"] for p in _secrets["Parameters"]}

_anthropic_api_key = _params[os.environ["SSM_ANTHROPIC_API_KEY"]]
_line_channel_access_token = _params[os.environ["SSM_LINE_CHANNEL_ACCESS_TOKEN"]]
_db_connection_string = _params[os.environ["SSM_DB_CONNECTION_STRING"]]

_model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-6")

_client = Anthropic(api_key=_anthropic_api_key)
_chat_message_repository = DbChatMessageRepository(
    os.environ["SSM_DB_CONNECTION_STRING"]
)
_line_push_sender = LinePushSender(_line_channel_access_token)

_service = ProcessLineMessage(
    client=_client,
    model=_model,
    chat_message_repository=_chat_message_repository,
    line_push_sender=_line_push_sender,
    db_connection_string=_db_connection_string,
)


def handler(event: dict, context: object) -> None:
    for record in event["Records"]:
        body = json.loads(record["body"])
        _service.execute(chat_message_id=body["chat_message_id"])
