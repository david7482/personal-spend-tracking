import json
import logging
import os
from typing import Any

import boto3

from spend_tracking.lambdas.services.process_line_message import ProcessLineMessage
from spend_tracking.lambdas.services.receive_line_webhook import ReceiveLineWebhook

logger = logging.getLogger()

# Email handler dependencies — only initialize when email env vars are present
_router_service: Any = None
_worker_service: Any = None

if os.environ.get("S3_BUCKET"):
    from spend_tracking.adapters.email_queue_sqs import SQSEmailQueue
    from spend_tracking.adapters.email_repository_db import DbEmailRepository
    from spend_tracking.adapters.email_storage_s3 import S3EmailStorage
    from spend_tracking.adapters.notification_sender_line import (
        LineNotificationSender,
    )
    from spend_tracking.adapters.transaction_repository_db import (
        DbTransactionRepository,
    )
    from spend_tracking.lambdas.services.process_email import ProcessEmail
    from spend_tracking.lambdas.services.validate_and_enqueue import (
        ValidateAndEnqueue,
    )

    _storage = S3EmailStorage(os.environ["S3_BUCKET"])
    _repository = DbEmailRepository(os.environ["SSM_DB_CONNECTION_STRING"])

    # Router dependencies
    _queue = SQSEmailQueue(os.environ.get("SQS_QUEUE_URL", ""))
    _router_service = ValidateAndEnqueue(_storage, _repository, _queue)

    # Worker dependencies
    _transaction_repository = DbTransactionRepository(
        os.environ["SSM_DB_CONNECTION_STRING"]
    )

    _notification_sender = None
    _line_token_param = os.environ.get("SSM_LINE_CHANNEL_ACCESS_TOKEN")
    if _line_token_param:
        ssm = boto3.client("ssm")
        response = ssm.get_parameter(Name=_line_token_param, WithDecryption=True)
        _notification_sender = LineNotificationSender(
            channel_access_token=response["Parameter"]["Value"]
        )

    _worker_service = ProcessEmail(
        _storage, _repository, _transaction_repository, _notification_sender
    )

# LINE handler dependencies — only initialize when LINE env vars are present
_receive_line_webhook_service: ReceiveLineWebhook | None = None
_process_line_message_service: ProcessLineMessage | None = None

_line_channel_secret_param = os.environ.get("SSM_LINE_CHANNEL_SECRET")
if _line_channel_secret_param:
    from spend_tracking.adapters.line_message_queue_sqs import SQSLineMessageQueue
    from spend_tracking.adapters.line_message_repository_db import (
        DbLineMessageRepository,
    )

    _ssm = boto3.client("ssm")
    _secret_response = _ssm.get_parameter(
        Name=_line_channel_secret_param, WithDecryption=True
    )
    _channel_secret = _secret_response["Parameter"]["Value"]

    _line_message_repository = DbLineMessageRepository(
        os.environ["SSM_DB_CONNECTION_STRING"]
    )
    _line_message_queue = SQSLineMessageQueue(os.environ["SQS_LINE_MESSAGE_QUEUE_URL"])

    _receive_line_webhook_service = ReceiveLineWebhook(
        channel_secret=_channel_secret,
        repository=_line_message_repository,
        queue=_line_message_queue,
    )
    _process_line_message_service = ProcessLineMessage()


def email_router_handler(event: dict, context: object) -> None:
    for record in event["Records"]:
        s3_key = record["s3"]["object"]["key"]
        logger.info("Processing S3 object", extra={"s3_key": s3_key})
        _router_service.execute(s3_key)


def email_worker_handler(event: dict, context: object) -> None:
    for record in event["Records"]:
        body = json.loads(record["body"])
        extra = {
            "s3_key": body["s3_key"],
            "address": body["address"],
            "sender": body["sender"],
        }
        logger.info("Processing email", extra=extra)
        _worker_service.execute(
            s3_key=body["s3_key"],
            address=body["address"],
            sender=body["sender"],
            received_at=body["received_at"],
        )


def line_webhook_router_handler(event: dict, context: object) -> dict:
    body = event["body"]
    signature = event["headers"]["x-line-signature"]
    return _receive_line_webhook_service.execute(body, signature)  # type: ignore[union-attr]


def line_message_worker_handler(event: dict, context: object) -> None:
    for record in event["Records"]:
        body = json.loads(record["body"])
        _process_line_message_service.execute(  # type: ignore[union-attr]
            line_message_id=body["line_message_id"]
        )
