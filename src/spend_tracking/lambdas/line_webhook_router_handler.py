import logging
import os

import boto3

from spend_tracking.adapters.line_message_queue_sqs import SQSLineMessageQueue
from spend_tracking.adapters.line_message_repository_db import DbLineMessageRepository
from spend_tracking.lambdas.services.receive_line_webhook import ReceiveLineWebhook

logger = logging.getLogger()

_ssm = boto3.client("ssm")
_secret_response = _ssm.get_parameter(
    Name=os.environ["SSM_LINE_CHANNEL_SECRET"], WithDecryption=True
)
_channel_secret = _secret_response["Parameter"]["Value"]

_line_message_repository = DbLineMessageRepository(
    os.environ["SSM_DB_CONNECTION_STRING"]
)
_line_message_queue = SQSLineMessageQueue(os.environ["SQS_LINE_MESSAGE_QUEUE_URL"])

_service = ReceiveLineWebhook(
    channel_secret=_channel_secret,
    repository=_line_message_repository,
    queue=_line_message_queue,
)


def handler(event: dict, context: object) -> dict:
    body = event["body"]
    signature = event["headers"]["x-line-signature"]
    return _service.execute(body, signature)
