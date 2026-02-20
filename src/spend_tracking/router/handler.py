import logging
import os

from spend_tracking.router.services.validate_and_enqueue import ValidateAndEnqueue
from spend_tracking.shared.adapters.email_queue_sqs import SQSEmailQueue
from spend_tracking.shared.adapters.email_repository_db import DbEmailRepository
from spend_tracking.shared.adapters.email_storage_s3 import S3EmailStorage

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_storage = S3EmailStorage(os.environ["S3_BUCKET"])
_queue = SQSEmailQueue(os.environ["SQS_QUEUE_URL"])
_repository = DbEmailRepository(os.environ["SSM_DB_CONNECTION_STRING"])
_service = ValidateAndEnqueue(_storage, _repository, _queue)


def handler(event, context):
    for record in event["Records"]:
        s3_key = record["s3"]["object"]["key"]
        logger.info("Processing S3 object: %s", s3_key)
        _service.execute(s3_key)
