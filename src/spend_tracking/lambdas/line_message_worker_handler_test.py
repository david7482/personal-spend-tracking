import json
from unittest.mock import patch


@patch("spend_tracking.lambdas.line_message_worker_handler._service")
def test_line_message_worker_handler_processes_each_record(mock_service):
    from spend_tracking.lambdas.line_message_worker_handler import handler

    event = {
        "Records": [
            {"body": json.dumps({"line_message_id": 42})},
            {"body": json.dumps({"line_message_id": 99})},
        ]
    }
    handler(event, None)

    assert mock_service.execute.call_count == 2
    mock_service.execute.assert_any_call(line_message_id=42)
    mock_service.execute.assert_any_call(line_message_id=99)
