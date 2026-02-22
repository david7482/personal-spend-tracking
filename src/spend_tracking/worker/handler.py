import json
import logging
import os

import boto3

from spend_tracking.shared.adapters.email_repository_db import DbEmailRepository
from spend_tracking.shared.adapters.email_storage_s3 import S3EmailStorage
from spend_tracking.shared.adapters.notification_sender_line import (
    LineNotificationSender,
)
from spend_tracking.shared.adapters.transaction_repository_db import (
    DbTransactionRepository,
)
from spend_tracking.worker.services.process_email import ProcessEmail

logger = logging.getLogger()

_storage = S3EmailStorage(os.environ["S3_BUCKET"])
_repository = DbEmailRepository(os.environ["SSM_DB_CONNECTION_STRING"])
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

_service = ProcessEmail(
    _storage, _repository, _transaction_repository, _notification_sender
)


def handler(event: dict, context: object) -> None:
    for record in event["Records"]:
        body = json.loads(record["body"])
        extra = {
            "s3_key": body["s3_key"],
            "address": body["address"],
            "sender": body["sender"],
        }
        logger.info("Processing email", extra=extra)
        _service.execute(
            s3_key=body["s3_key"],
            address=body["address"],
            sender=body["sender"],
            received_at=body["received_at"],
        )
