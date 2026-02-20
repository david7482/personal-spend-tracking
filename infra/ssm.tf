resource "aws_ssm_parameter" "db_connection_string" {
  name  = "/${var.project_name}/db-connection-string"
  type  = "SecureString"
  value = "placeholder"

  lifecycle {
    ignore_changes = [value]
  }
}
