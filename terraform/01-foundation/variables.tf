# Both stages read the same ../terraform.tfvars (see terraform/README.md), so
# the variable set is declared identically in both stages — each simply
# ignores what it doesn't use. Keep the two files in sync.

variable "cluster_name" {
  description = "Name of the existing EKS cluster to deploy into (the cluster itself is a prerequisite, not managed here)."
  type        = string
}

variable "region" {
  description = "AWS region of the EKS cluster and the snapshots bucket."
  type        = string
}

variable "snapshots_bucket" {
  description = <<-EOT
    Name for the S3 snapshots bucket (created by stage 01). Must be dedicated
    to this Restate cluster: the snapshot prefix is identical in every install
    of this manifest and a snapshot repository belongs to exactly one cluster
    (docs/01-prerequisites.md).
  EOT
  type        = string
}

variable "service_image" {
  description = <<-EOT
    Container image for the SDK service (resources/05-restate-compute.yaml),
    used by stage 02. Leave empty to skip deploying compute — the equivalent
    of stopping the runbook before step 5.
  EOT
  type        = string
  default     = ""
}

variable "create_oidc_provider" {
  description = <<-EOT
    Whether stage 01 creates the cluster's IAM OIDC provider for IRSA. Set to
    false if the cluster already has one (e.g. from a previous
    `eksctl utils associate-iam-oidc-provider` on the runbook path) — it is
    then looked up instead of created.
  EOT
  type        = bool
  default     = true
}
