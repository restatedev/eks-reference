# Stage 02 requires stage 01 to have been APPLIED (not just planned) first:
# the operator helm release installs the RestateCluster / RestateDeployment
# CRDs, and kubernetes_manifest fetches CRD schemas from the live cluster at
# plan time. See terraform/README.md.

provider "aws" {
  region = var.region
}

data "aws_eks_cluster" "this" {
  name = var.cluster_name

  lifecycle {
    postcondition {
      condition     = try(self.kubernetes_network_config[0].ip_family, "") == "ipv4"
      error_message = "This reference currently supports IPv4 EKS clusters only; the target cluster does not report ipFamily=ipv4."
    }
  }
}

# Exec auth for the same reason as stage 01: the RestateCluster wait
# (provision + pods Ready) can outlive a static 15-minute token.
provider "kubernetes" {
  host                   = data.aws_eks_cluster.this.endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.this.certificate_authority[0].data)

  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", var.cluster_name, "--region", var.region]
  }
}
