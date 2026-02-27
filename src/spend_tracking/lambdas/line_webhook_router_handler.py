import logging
import os

import boto3

from spend_tracking.adapters.chat_message_repository_db import (
    DbChatMessageRepository,
)
from spend_tracking.adapters.line_message_queue_sqs import SQSLineMessageQueue
from spend_tracking.lambdas.services.receive_line_webhook import ReceiveLineWebhook

logger = logging.getLogger()

_ssm = boto3.client("ssm")

_secrets = _ssm.get_parameters(
    Names=[
        os.environ["SSM_LINE_CHANNEL_SECRET"],
        os.environ["SSM_LINE_CHANNEL_ACCESS_TOKEN"],
    ],
    WithDecryption=True,
)
_params = {p["Name"]: p["Value"] for p in _secrets["Parameters"]}
_channel_secret = _params[os.environ["SSM_LINE_CHANNEL_SECRET"]]
_channel_access_token = _params[os.environ["SSM_LINE_CHANNEL_ACCESS_TOKEN"]]

_chat_message_repository = DbChatMessageRepository(
    os.environ["SSM_DB_CONNECTION_STRING"]
)
_line_message_queue = SQSLineMessageQueue(os.environ["SQS_LINE_MESSAGE_QUEUE_URL"])

_service = ReceiveLineWebhook(
    channel_secret=_channel_secret,
    channel_access_token=_channel_access_token,
    repository=_chat_message_repository,
    queue=_line_message_queue,
)


def handler(event: dict, context: object) -> dict:
    body = event["body"]
    signature = event["headers"]["x-line-signature"]
    return _service.execute(body, signature)
