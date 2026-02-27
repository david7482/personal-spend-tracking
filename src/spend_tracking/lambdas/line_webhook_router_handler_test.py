import os
from unittest.mock import MagicMock, patch

_mock_boto3_client = MagicMock()
_mock_boto3_client.get_parameters.return_value = {
    "Parameters": [
        {"Name": "/test/secret", "Value": "fake-secret"},
        {"Name": "/test/token", "Value": "fake-token"},
    ]
}
_mock_boto3_client.get_parameter.return_value = {"Parameter": {"Value": "fake-db"}}

with (
    patch.dict(
        os.environ,
        {
            "SSM_LINE_CHANNEL_SECRET": "/test/secret",
            "SSM_LINE_CHANNEL_ACCESS_TOKEN": "/test/token",
            "SSM_DB_CONNECTION_STRING": "/test/db",
            "SQS_LINE_MESSAGE_QUEUE_URL": "https://test-queue",
        },
    ),
    patch("boto3.client", return_value=_mock_boto3_client),
):
    from spend_tracking.lambdas.line_webhook_router_handler import handler


@patch("spend_tracking.lambdas.line_webhook_router_handler._service")
def test_line_webhook_router_handler_delegates_to_service(mock_service):
    mock_service.execute.return_value = {"statusCode": 200, "body": "OK"}

    event = {
        "headers": {"x-line-signature": "test-signature"},
        "body": '{"events": []}',
    }
    result = handler(event, None)

    assert result["statusCode"] == 200
    mock_service.execute.assert_called_once_with('{"events": []}', "test-signature")


@patch("spend_tracking.lambdas.line_webhook_router_handler._service")
def test_line_webhook_router_handler_returns_401_on_bad_signature(mock_service):
    mock_service.execute.return_value = {
        "statusCode": 401,
        "body": "Invalid signature",
    }

    event = {
        "headers": {"x-line-signature": "bad-sig"},
        "body": "{}",
    }
    result = handler(event, None)

    assert result["statusCode"] == 401
