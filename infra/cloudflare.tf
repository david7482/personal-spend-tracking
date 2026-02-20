data "cloudflare_zone" "main" {
  filter = {
    name = "david74.dev"
  }
}

resource "cloudflare_dns_record" "ses_verification" {
  zone_id = data.cloudflare_zone.main.zone_id
  name    = "_amazonses.${var.email_domain}"
  type    = "TXT"
  content = "\"${aws_ses_domain_identity.email.verification_token}\""
  ttl     = 3600
}

resource "cloudflare_dns_record" "ses_mx" {
  zone_id  = data.cloudflare_zone.main.zone_id
  name     = var.email_domain
  type     = "MX"
  content  = "inbound-smtp.us-east-1.amazonaws.com"
  ttl      = 3600
  priority = 10
}
