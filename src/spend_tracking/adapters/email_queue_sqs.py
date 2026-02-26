import json

import boto3

from spend_tracking.shared.interfaces.email_queue import EmailQueue


class SQSEmailQueue(EmailQueue):
    def __init__(self, queue_url: str) -> None:
        self._sqs = boto3.client("sqs")
        self._queue_url = queue_url

    def send_message(self, message: dict) -> None:
        self._sqs.send_message(
            QueueUrl=self._queue_url,
            MessageBody=json.dumps(message),
        )
