import json

import boto3

from spend_tracking.interfaces.line_message_queue import LineMessageQueue


class SQSLineMessageQueue(LineMessageQueue):
    def __init__(self, queue_url: str) -> None:
        self._sqs = boto3.client("sqs")
        self._queue_url = queue_url

    def send_message(self, message: dict) -> None:
        self._sqs.send_message(
            QueueUrl=self._queue_url,
            MessageBody=json.dumps(message),
        )
