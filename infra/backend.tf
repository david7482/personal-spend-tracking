terraform {
  backend "s3" {
    bucket = "david74-terraform-remote-state-storage"
    workspace_key_prefix = "personal-spend-tracking"
    key                  = "terraform.tfstate"
    region = "us-west-2"
  }
}
