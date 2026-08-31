# IAM for snapshots (IRSA) — replaces runbook step 2 (`aws iam create-policy`
# + `eksctl create iamserviceaccount --role-only`).
#
# Names are cluster-qualified on purpose: IAM policies/roles are
# account-global, and this role's trust is tied to THIS cluster's OIDC
# provider — a second EKS cluster in the account needs its own pair. Stage 02
# re-derives the role by this same "<cluster>-restate-snapshots" convention
# instead of reading this stage's state (that's what keeps the stages
# decoupled), so rename it in both stages or not at all.

locals {
  snapshots_name = "${var.cluster_name}-restate-snapshots"
}

# The policy document is the repo's canonical JSON with the same placeholder
# substitution the runbook does with sed — resources/ stays the single source
# of truth for both paths.
resource "aws_iam_policy" "snapshots" {
  name = local.snapshots_name
  policy = replace(
    file("${path.module}/../../resources/01-restate-snapshots-iam-policy.json"),
    "REPLACE_ME_SNAPSHOTS_BUCKET",
    var.snapshots_bucket,
  )
}

# Trust policy: only the ServiceAccount the operator creates for the
# StatefulSet ("restate" in namespace "restate") may assume this role — see
# docs/00-architecture.md#iam-for-snapshots.
data "aws_iam_policy_document" "irsa_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_issuer}:sub"
      values   = ["system:serviceaccount:restate:restate"]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_issuer}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "snapshots" {
  name               = local.snapshots_name
  assume_role_policy = data.aws_iam_policy_document.irsa_trust.json
}

resource "aws_iam_role_policy_attachment" "snapshots" {
  role       = aws_iam_role.snapshots.name
  policy_arn = aws_iam_policy.snapshots.arn
}
