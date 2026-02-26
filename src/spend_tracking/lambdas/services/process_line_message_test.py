def test_execute_is_noop():
    from spend_tracking.lambdas.services.process_line_message import (
        ProcessLineMessage,
    )

    service = ProcessLineMessage()
    # Should not raise
    service.execute(line_message_id=42)
