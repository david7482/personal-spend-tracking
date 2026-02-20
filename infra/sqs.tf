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
