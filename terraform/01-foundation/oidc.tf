# IRSA needs the cluster's OIDC issuer registered as an IAM identity
# provider. By default it is treated as a PREREQUISITE and looked up: IAM
# allows exactly one provider per issuer URL, and most clusters already have
# it — any IRSA-based addon (the required EBS CSI driver's usual install
# included) or a previous `eksctl utils associate-iam-oidc-provider` created
# it, and creating again fails with EntityAlreadyExists.
#
# create_oidc_provider = true (fresh cluster only) makes this stage create it
# instead, replacing the runbook's eksctl step — but note the provider is
# CLUSTER-WIDE state: every IRSA role trusting this issuer, other workloads'
# included, depends on it, so a stage-01 destroy would take them all down
# with it. See the destroy section of terraform/README.md.

data "tls_certificate" "oidc" {
  count = var.create_oidc_provider ? 1 : 0
  url   = data.aws_eks_cluster.this.identity[0].oidc[0].issuer
}

resource "aws_iam_openid_connect_provider" "this" {
  count = var.create_oidc_provider ? 1 : 0

  url            = data.aws_eks_cluster.this.identity[0].oidc[0].issuer
  client_id_list = ["sts.amazonaws.com"]
  # AWS trusts EKS issuers via root CA these days, but the API still takes a
  # thumbprint list; recording the whole served chain keeps it valid across
  # certificate rotations.
  thumbprint_list = data.tls_certificate.oidc[0].certificates[*].sha1_fingerprint
}

data "aws_iam_openid_connect_provider" "existing" {
  count = var.create_oidc_provider ? 0 : 1
  url   = data.aws_eks_cluster.this.identity[0].oidc[0].issuer
}

locals {
  oidc_provider_arn = var.create_oidc_provider ? aws_iam_openid_connect_provider.this[0].arn : data.aws_iam_openid_connect_provider.existing[0].arn
  # the issuer without the scheme, as trust-policy condition keys want it
  oidc_issuer = trimprefix(data.aws_eks_cluster.this.identity[0].oidc[0].issuer, "https://")
}
