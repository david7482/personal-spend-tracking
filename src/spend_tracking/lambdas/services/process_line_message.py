import logging

logger = logging.getLogger(__name__)


class ProcessLineMessage:
    def execute(self, line_message_id: int) -> None:
        logger.info(
            "Processing LINE message (no-op)",
            extra={"line_message_id": line_message_id},
        )
