terraform {
  backend "s3" {
    bucket = "david74-terraform-remote-state-storage"
    key    = "spend-tracking/terraform.tfstate"
    region = "us-west-2"
  }
}
