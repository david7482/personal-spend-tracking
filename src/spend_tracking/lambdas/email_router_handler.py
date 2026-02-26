import logging
import os

from spend_tracking.adapters.email_queue_sqs import SQSEmailQueue
from spend_tracking.adapters.email_repository_db import DbEmailRepository
from spend_tracking.adapters.email_storage_s3 import S3EmailStorage
from spend_tracking.lambdas.services.validate_and_enqueue import ValidateAndEnqueue

logger = logging.getLogger()

_storage = S3EmailStorage(os.environ["S3_BUCKET"])
_repository = DbEmailRepository(os.environ["SSM_DB_CONNECTION_STRING"])
_queue = SQSEmailQueue(os.environ["SQS_QUEUE_URL"])
_service = ValidateAndEnqueue(_storage, _repository, _queue)


def handler(event: dict, context: object) -> None:
    for record in event["Records"]:
        s3_key = record["s3"]["object"]["key"]
        logger.info("Processing S3 object", extra={"s3_key": s3_key})
        _service.execute(s3_key)
