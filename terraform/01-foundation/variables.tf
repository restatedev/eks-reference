# Both stages read the same ../terraform.tfvars (see terraform/README.md), so
# the variable set is declared identically in both stages — each simply
# ignores what it doesn't use. Keep the two files in sync.

variable "cluster_name" {
  description = "Name of the existing EKS cluster to deploy into (the cluster itself is a prerequisite, not managed here)."
  type        = string

  validation {
    # IAM role names cap at 64 characters and the derived
    # "<cluster>-restate-snapshots" name appends 18 (EKS itself allows
    # cluster names up to 100).
    condition     = length(var.cluster_name) <= 46
    error_message = "cluster_name must be at most 46 characters: the derived \"<cluster>-restate-snapshots\" IAM role name would exceed IAM's 64-character RoleName limit."
  }
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

variable "create_oidc_provider" {
  description = <<-EOT
    Whether stage 01 creates the cluster's IAM OIDC provider for IRSA.
    Defaults to false (looked up as a prerequisite): IAM allows one provider
    per issuer, and most clusters already have it — any IRSA-based addon (the
    required EBS CSI driver's usual install included) or a previous
    `eksctl utils associate-iam-oidc-provider` created it, so creating again
    fails with EntityAlreadyExists. Set true only on a fresh cluster with no
    provider, and read terraform/README.md's destroy caveat first.
  EOT
  type        = bool
  default     = false
}

variable "create_service_cidr_egress_policy" {
  description = <<-EOT
    Whether stage 02 applies resources/06-restate-service-cidr-egress.yaml,
    which lets the Restate pods reach SDK service ClusterIPs on 9080. Required
    wherever the CNI evaluates NetworkPolicy before Service DNAT (the EKS VPC
    CNI with enforcement on), because the operator opens egress to service pod
    IPs but not to the ClusterIP it registers each revision under — service
    registration times out without it. Defaults to true; the CIDR itself is
    read from the EKS cluster, not configured here. Set false only on a CNI
    that evaluates after DNAT (Calico, Cilium), where it is unnecessary.
  EOT
  type        = bool
  default     = true
}
