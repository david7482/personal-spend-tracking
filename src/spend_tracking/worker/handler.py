import json
import logging
import os

from spend_tracking.shared.adapters.email_repository_db import DbEmailRepository
from spend_tracking.shared.adapters.email_storage_s3 import S3EmailStorage
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
_service = ProcessEmail(_storage, _repository, _transaction_repository)


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
