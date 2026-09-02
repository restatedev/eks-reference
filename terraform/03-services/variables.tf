# Shared with the other stages via ../terraform.tfvars; the unused ones are
# declared so the shared file loads cleanly.

variable "cluster_name" {
  type = string
}

variable "region" {
  type = string
}

variable "snapshots_bucket" {
  type = string
}

variable "create_oidc_provider" {
  type    = bool
  default = false
}

variable "create_service_cidr_egress_policy" {
  type    = bool
  default = true
}

# Immutable image reference for the SDK service; passed per deployment from
# the application pipeline rather than kept in this file.
variable "service_image" {
  type = string
}
