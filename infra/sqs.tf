resource "aws_sqs_queue" "email-dlq" {
  name = "${var.project_name}-email-dlq"
}

resource "aws_sqs_queue" "email-processing" {
  name                       = "${var.project_name}-email-processing"
  visibility_timeout_seconds = 300

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.email-dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_sqs_queue" "line-message-dlq" {
  name = "${var.project_name}-line-message-dlq"
}

resource "aws_sqs_queue" "line-message-processing" {
  name                       = "${var.project_name}-line-message-processing"
  visibility_timeout_seconds = 660

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.line-message-dlq.arn
    maxReceiveCount     = 3
  })
}
