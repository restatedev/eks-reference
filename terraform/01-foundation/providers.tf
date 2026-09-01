provider "aws" {
  region = var.region
}

# The EKS cluster is a prerequisite, not something this config creates
# (docs/01-prerequisites.md). Everything Kubernetes-side hangs off this
# lookup.
data "aws_eks_cluster" "this" {
  name = var.cluster_name

  lifecycle {
    postcondition {
      condition     = try(self.kubernetes_network_config[0].ip_family, "") == "ipv4"
      error_message = "This reference currently supports IPv4 EKS clusters only; the target cluster does not report ipFamily=ipv4."
    }
  }
}

# Exec auth (`aws eks get-token`) instead of a aws_eks_cluster_auth token:
# those tokens expire after ~15 minutes, which a first apply of this stage
# (helm install + image pulls) can outlive. Exec re-mints on demand — same
# mechanism the kubeconfig from `aws eks update-kubeconfig` uses.
provider "kubernetes" {
  host                   = data.aws_eks_cluster.this.endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.this.certificate_authority[0].data)

  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", var.cluster_name, "--region", var.region]
  }
}

# helm provider 3.x syntax: `kubernetes` and `exec` are attributes (with `=`),
# not blocks — this file won't parse under provider 2.x, which is intentional
# (versions.tf pins ~> 3.0).
provider "helm" {
  kubernetes = {
    host                   = data.aws_eks_cluster.this.endpoint
    cluster_ca_certificate = base64decode(data.aws_eks_cluster.this.certificate_authority[0].data)

    exec = {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", var.cluster_name, "--region", var.region]
    }
  }
}
