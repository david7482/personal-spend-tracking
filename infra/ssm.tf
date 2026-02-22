resource "aws_ssm_parameter" "db_connection_string" {
  name  = "/${var.project_name}/db-connection-string"
  type  = "SecureString"
  value = "placeholder"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "line_channel_access_token" {
  name  = "/${var.project_name}/line-channel-access-token"
  type  = "SecureString"
  value = "placeholder"

  lifecycle {
    ignore_changes = [value]
  }
}
