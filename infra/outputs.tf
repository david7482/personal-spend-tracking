output "ses_verification_token" {
  value       = aws_ses_domain_identity.email.verification_token
  description = "Add as TXT record _amazonses.mail.david74.dev in Cloudflare"
}

output "router_function_name" {
  value = aws_lambda_function.router.function_name
}

output "worker_function_name" {
  value = aws_lambda_function.worker.function_name
}

output "raw_emails_bucket" {
  value = aws_s3_bucket.raw_emails.id
}

output "sqs_queue_url" {
  value = aws_sqs_queue.processing.url
}
