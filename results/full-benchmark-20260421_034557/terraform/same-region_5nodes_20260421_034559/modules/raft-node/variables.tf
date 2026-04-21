variable "node_id" {
  description = "Logical node name, e.g. node1"
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.micro"
}

variable "ssh_public_key" {
  description = "OpenSSH public key material to install on the instance"
  type        = string
}

variable "key_pair_name" {
  description = "Name prefix for the AWS key pair resource"
  type        = string
  default     = "raft-quic"
}

variable "name_prefix" {
  description = "Optional prefix to isolate resource names for parallel test runs"
  type        = string
  default     = ""
}
