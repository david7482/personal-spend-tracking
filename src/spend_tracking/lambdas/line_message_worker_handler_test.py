import json
import os
from unittest.mock import MagicMock, patch

_mock_boto3_client = MagicMock()
_mock_boto3_client.get_parameters.return_value = {
    "Parameters": [
        {"Name": "/test/anthropic-key", "Value": "fake-key"},
        {"Name": "/test/line-token", "Value": "fake-token"},
        {"Name": "/test/db", "Value": "postgresql://fake"},
    ]
}
_mock_boto3_client.get_parameter.return_value = {
    "Parameter": {"Value": "postgresql://fake"}
}

with (
    patch.dict(
        os.environ,
        {
            "SSM_ANTHROPIC_API_KEY": "/test/anthropic-key",
            "SSM_LINE_CHANNEL_ACCESS_TOKEN": "/test/line-token",
            "SSM_DB_CONNECTION_STRING": "/test/db",
            "ANTHROPIC_MODEL": "claude-haiku-4-5-20251001",
        },
    ),
    patch("boto3.client", return_value=_mock_boto3_client),
    patch("anthropic.Anthropic"),
):
    from spend_tracking.lambdas.line_message_worker_handler import handler


@patch("spend_tracking.lambdas.line_message_worker_handler._service")
def test_line_message_worker_handler_processes_each_record(mock_service):
    event = {
        "Records": [
            {"body": json.dumps({"chat_message_id": 42})},
            {"body": json.dumps({"chat_message_id": 99})},
        ]
    }
    handler(event, None)

    assert mock_service.execute.call_count == 2
    mock_service.execute.assert_any_call(chat_message_id=42)
    mock_service.execute.assert_any_call(chat_message_id=99)
