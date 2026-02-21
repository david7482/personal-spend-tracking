import json
import logging
import os

from spend_tracking.shared.adapters.email_repository_db import DbEmailRepository
from spend_tracking.shared.adapters.email_storage_s3 import S3EmailStorage
from spend_tracking.worker.services.process_email import ProcessEmail

logger = logging.getLogger()

_storage = S3EmailStorage(os.environ["S3_BUCKET"])
_repository = DbEmailRepository(os.environ["SSM_DB_CONNECTION_STRING"])
_service = ProcessEmail(_storage, _repository)


def handler(event, context):
    for record in event["Records"]:
        body = json.loads(record["body"])
        logger.info("Processing email", extra={"s3_key": body["s3_key"], "address": body["address"], "sender": body["sender"]})
        _service.execute(
            s3_key=body["s3_key"],
            address=body["address"],
            sender=body["sender"],
            received_at=body["received_at"],
        )
