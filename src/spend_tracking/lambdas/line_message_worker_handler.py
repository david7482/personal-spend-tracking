import json
import logging

from spend_tracking.lambdas.services.process_line_message import ProcessLineMessage

logger = logging.getLogger()

_service = ProcessLineMessage()


def handler(event: dict, context: object) -> None:
    for record in event["Records"]:
        body = json.loads(record["body"])
        _service.execute(line_message_id=body["line_message_id"])
