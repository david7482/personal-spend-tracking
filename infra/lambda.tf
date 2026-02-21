data "archive_file" "placeholder" {
  type        = "zip"
  output_path = "${path.module}/placeholder.zip"

  source {
    content  = "def handler(event, context): pass"
    filename = "spend_tracking/router/handler.py"
  }
}

resource "aws_lambda_function" "router" {
  function_name = "${var.project_name}-router"
  role          = aws_iam_role.router.arn
  handler       = "spend_tracking.router.handler.handler"
  runtime       = "python3.12"
  timeout       = 30
  memory_size   = 128
  filename      = data.archive_file.placeholder.output_path

  environment {
    variables = {
      S3_BUCKET               = aws_s3_bucket.raw_emails.id
      SQS_QUEUE_URL           = aws_sqs_queue.email-processing.url
      SSM_DB_CONNECTION_STRING = aws_ssm_parameter.db_connection_string.name
    }
  }

  logging_config {
    log_format            = "JSON"
    application_log_level = "INFO"
    system_log_level      = "WARN"
  }

  lifecycle {
    ignore_changes = [filename, source_code_hash]
  }
}

resource "aws_lambda_permission" "allow_s3" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.router.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = aws_s3_bucket.raw_emails.arn
}

resource "aws_lambda_function" "worker" {
  function_name = "${var.project_name}-worker"
  role          = aws_iam_role.worker.arn
  handler       = "spend_tracking.worker.handler.handler"
  runtime       = "python3.12"
  timeout       = 60
  memory_size   = 256
  filename      = data.archive_file.placeholder.output_path

  environment {
    variables = {
      S3_BUCKET               = aws_s3_bucket.raw_emails.id
      SSM_DB_CONNECTION_STRING = aws_ssm_parameter.db_connection_string.name
    }
  }

  logging_config {
    log_format            = "JSON"
    application_log_level = "INFO"
    system_log_level      = "WARN"
  }

  lifecycle {
    ignore_changes = [filename, source_code_hash]
  }
}

resource "aws_lambda_event_source_mapping" "worker_sqs" {
  event_source_arn = aws_sqs_queue.email-processing.arn
  function_name    = aws_lambda_function.worker.arn
  batch_size       = 1
}
