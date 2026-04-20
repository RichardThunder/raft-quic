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
  default     = "us-east-1" # N. Virginia
}
variable "region_node2" {
  description = "Region for node2"
  default     = "us-west-2" # Oregon
}
variable "region_node3" {
  description = "Region for node3"
  default     = "eu-west-1" # EU (Ireland)
}

variable "instance_type" {
  default = "t3.micro"
}

variable "cluster_size" {
  description = "Number of nodes in cross-region cluster"
  type        = number
  default     = 3

  validation {
    condition     = var.cluster_size >= 3
    error_message = "cross-region cluster_size must be >= 3."
  }
}

variable "name_prefix" {
  description = "Optional resource name prefix for parallel isolated runs"
  type        = string
  default     = ""
}

locals {
  extra_nodes = var.cluster_size - 3

  # Keep one node in each region, then distribute remaining nodes round-robin.
  ap_count = 1 + floor((local.extra_nodes + 2) / 3)
  us_count = 1 + floor((local.extra_nodes + 1) / 3)
  eu_count = 1 + floor((local.extra_nodes + 0) / 3)
}

# ── One provider alias per region ─────────────────────────────────────────────
provider "aws" {
  alias      = "ap"
  region     = var.region_node1
  sts_region = "us-east-1"
}
provider "aws" {
  alias      = "us"
  region     = var.region_node2
  sts_region = "us-east-1"
}
provider "aws" {
  alias      = "eu"
  region     = var.region_node3
  sts_region = "us-east-1"
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

# ── AP region nodes ────────────────────────────────────────────────────────────
module "node_ap" {
  count     = local.ap_count
  source    = "../modules/raft-node"
  providers = { aws = aws.ap }

  node_id        = "node${count.index + 1}"
  instance_type  = var.instance_type
  ssh_public_key = tls_private_key.ssh.public_key_openssh
  key_pair_name  = "raft-quic-cross"
  name_prefix    = var.name_prefix
}

# ── US region nodes ────────────────────────────────────────────────────────────
module "node_us" {
  count     = local.us_count
  source    = "../modules/raft-node"
  providers = { aws = aws.us }

  node_id        = "node${local.ap_count + count.index + 1}"
  instance_type  = var.instance_type
  ssh_public_key = tls_private_key.ssh.public_key_openssh
  key_pair_name  = "raft-quic-cross"
  name_prefix    = var.name_prefix
}

# ── EU region nodes ────────────────────────────────────────────────────────────
module "node_eu" {
  count     = local.eu_count
  source    = "../modules/raft-node"
  providers = { aws = aws.eu }

  node_id        = "node${local.ap_count + local.us_count + count.index + 1}"
  instance_type  = var.instance_type
  ssh_public_key = tls_private_key.ssh.public_key_openssh
  key_pair_name  = "raft-quic-cross"
  name_prefix    = var.name_prefix
}

# ── Outputs ────────────────────────────────────────────────────────────────────
output "node_ips" {
  value = concat(
    module.node_ap[*].public_ip,
    module.node_us[*].public_ip,
    module.node_eu[*].public_ip,
  )
}

output "node_ids" {
  value = concat(
    [for i in range(local.ap_count) : "node${i + 1}"],
    [for i in range(local.us_count) : "node${local.ap_count + i + 1}"],
    [for i in range(local.eu_count) : "node${local.ap_count + local.us_count + i + 1}"],
  )
}

output "instance_ids" {
  value = concat(
    module.node_ap[*].instance_id,
    module.node_us[*].instance_id,
    module.node_eu[*].instance_id,
  )
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
  value = concat(
    [for _ in module.node_ap : var.region_node1],
    [for _ in module.node_us : var.region_node2],
    [for _ in module.node_eu : var.region_node3],
  )
}
