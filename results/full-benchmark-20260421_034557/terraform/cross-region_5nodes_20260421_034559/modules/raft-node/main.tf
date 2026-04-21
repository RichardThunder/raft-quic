terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

locals {
  resource_prefix = trimspace(var.name_prefix) != "" ? "${trimspace(var.name_prefix)}-" : ""
}

data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

# ── Latest Amazon Linux 2023 (x86_64) ─────────────────────────────────────────
data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# ── Key pair ───────────────────────────────────────────────────────────────────
resource "aws_key_pair" "raft" {
  key_name   = "${local.resource_prefix}${var.key_pair_name}-${var.node_id}"
  public_key = var.ssh_public_key

  tags = { Project = "raft-quic", Node = var.node_id }
}

# ── IAM role/profile for SSM management ───────────────────────────────────────
resource "aws_iam_role" "raft_ssm" {
  name               = "${local.resource_prefix}${var.key_pair_name}-ssm-${var.node_id}"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
  tags               = { Project = "raft-quic", Node = var.node_id }
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.raft_ssm.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "raft_ssm" {
  name = "${local.resource_prefix}${var.key_pair_name}-ssm-${var.node_id}"
  role = aws_iam_role.raft_ssm.name
}

# ── Security group ─────────────────────────────────────────────────────────────
resource "aws_security_group" "raft" {
  name        = "${local.resource_prefix}raft-quic-${var.node_id}"
  description = "Raft-over-QUIC cluster node ${var.node_id}"

  # SSH
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  # HTTP management API
  ingress {
    from_port   = 8001
    to_port     = 8001
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  # TCP baseline service API
  ingress {
    from_port   = 9001
    to_port     = 9001
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  # Raft-over-TCP transport between nodes
  ingress {
    from_port   = 9007
    to_port     = 9007
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  # QUIC transport (UDP) — must explicitly allow UDP
  ingress {
    from_port   = 7001
    to_port     = 7001
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  # All outbound
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Project = "raft-quic", Node = var.node_id }
}

# ── EC2 instance ───────────────────────────────────────────────────────────────
resource "aws_instance" "node" {
  ami                         = data.aws_ami.al2023.id
  instance_type               = var.instance_type
  key_name                    = aws_key_pair.raft.key_name
  iam_instance_profile        = aws_iam_instance_profile.raft_ssm.name
  vpc_security_group_ids      = [aws_security_group.raft.id]
  associate_public_ip_address = true

  # Ensure the instance has a stable public IP on reboot.
  # (For production use an Elastic IP; for a PoC the auto-assigned IP is fine.)

  tags = {
    Name    = "${local.resource_prefix}raft-quic-${var.node_id}"
    Project = "raft-quic"
    Node    = var.node_id
  }
}
