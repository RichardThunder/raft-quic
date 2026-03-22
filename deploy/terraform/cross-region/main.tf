terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.0"
    }
  }
}

# ── Variables ──────────────────────────────────────────────────────────────────
variable "region_node1" {
  description = "Region for node1 (bootstrap)"
  default     = "ap-east-1"    # Hong Kong
}
variable "region_node2" {
  description = "Region for node2"
  default     = "us-east-1"    # US East (N. Virginia)
}
variable "region_node3" {
  description = "Region for node3"
  default     = "eu-west-1"    # EU (Ireland)
}

variable "instance_type" {
  default = "t3.micro"
}

# ── One provider alias per region ─────────────────────────────────────────────
# Terraform requires static alias names, so we enumerate all three explicitly.
provider "aws" {
  alias  = "ap"
  region = var.region_node1
}
provider "aws" {
  alias  = "us"
  region = var.region_node2
}
provider "aws" {
  alias  = "eu"
  region = var.region_node3
}

# ── Shared SSH key ─────────────────────────────────────────────────────────────
resource "tls_private_key" "ssh" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "local_sensitive_file" "ssh_key" {
  content         = tls_private_key.ssh.private_key_pem
  filename        = "${path.module}/raft-key.pem"
  file_permission = "0600"
}

# ── Node 1 – Hong Kong ─────────────────────────────────────────────────────────
module "node1" {
  source = "../modules/raft-node"
  providers = { aws = aws.ap }

  node_id        = "node1"
  instance_type  = var.instance_type
  ssh_public_key = tls_private_key.ssh.public_key_openssh
  key_pair_name  = "raft-quic-cross"
}

# ── Node 2 – US East ──────────────────────────────────────────────────────────
module "node2" {
  source = "../modules/raft-node"
  providers = { aws = aws.us }

  node_id        = "node2"
  instance_type  = var.instance_type
  ssh_public_key = tls_private_key.ssh.public_key_openssh
  key_pair_name  = "raft-quic-cross"
}

# ── Node 3 – EU West ──────────────────────────────────────────────────────────
module "node3" {
  source = "../modules/raft-node"
  providers = { aws = aws.eu }

  node_id        = "node3"
  instance_type  = var.instance_type
  ssh_public_key = tls_private_key.ssh.public_key_openssh
  key_pair_name  = "raft-quic-cross"
}

# ── Outputs ────────────────────────────────────────────────────────────────────
output "node_ips" {
  value = [
    module.node1.public_ip,
    module.node2.public_ip,
    module.node3.public_ip,
  ]
}

output "ssh_key_file" {
  value = local_sensitive_file.ssh_key.filename
}

output "ssh_user" {
  value = "ec2-user"
}

output "scenario" {
  value = "cross-region"
}

output "region_labels" {
  value = [var.region_node1, var.region_node2, var.region_node3]
}
