import json
from unittest.mock import patch


@patch("spend_tracking.lambdas.handler._receive_line_webhook_service")
def test_line_webhook_router_handler_delegates_to_service(mock_service):
    from spend_tracking.lambdas.handler import line_webhook_router_handler

    mock_service.execute.return_value = {"statusCode": 200, "body": "OK"}

    event = {
        "headers": {"x-line-signature": "test-signature"},
        "body": '{"events": []}',
    }
    result = line_webhook_router_handler(event, None)

    assert result["statusCode"] == 200
    mock_service.execute.assert_called_once_with('{"events": []}', "test-signature")


@patch("spend_tracking.lambdas.handler._receive_line_webhook_service")
def test_line_webhook_router_handler_returns_401_on_bad_signature(mock_service):
    from spend_tracking.lambdas.handler import line_webhook_router_handler

    mock_service.execute.return_value = {
        "statusCode": 401,
        "body": "Invalid signature",
    }

    event = {
        "headers": {"x-line-signature": "bad-sig"},
        "body": "{}",
    }
    result = line_webhook_router_handler(event, None)

    assert result["statusCode"] == 401


@patch("spend_tracking.lambdas.handler._process_line_message_service")
def test_line_message_worker_handler_processes_each_record(mock_service):
    from spend_tracking.lambdas.handler import line_message_worker_handler

    event = {
        "Records": [
            {"body": json.dumps({"line_message_id": 42})},
            {"body": json.dumps({"line_message_id": 99})},
        ]
    }
    line_message_worker_handler(event, None)

    assert mock_service.execute.call_count == 2
    mock_service.execute.assert_any_call(line_message_id=42)
    mock_service.execute.assert_any_call(line_message_id=99)
