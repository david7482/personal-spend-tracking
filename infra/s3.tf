resource "aws_s3_bucket" "raw_emails" {
  bucket = "david74-spend-tracking-raw-emails"
}

resource "aws_s3_bucket_policy" "allow_ses" {
  bucket = aws_s3_bucket.raw_emails.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowSESPuts"
        Effect    = "Allow"
        Principal = { Service = "ses.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.raw_emails.arn}/*"
      }
    ]
  })
}

resource "aws_s3_bucket_notification" "email_received" {
  bucket = aws_s3_bucket.raw_emails.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.router.arn
    events              = ["s3:ObjectCreated:*"]
  }

  depends_on = [aws_lambda_permission.allow_s3]
}
