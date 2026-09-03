# The RestateCluster CR — the canonical resources/04-restate-cluster.yaml
# with the same REPLACE_ME substitutions the runbook has you make by hand.
# Plain replace() rather than templatefile() on purpose: file() performs no
# interpolation, so Kubernetes-isms like $(POD_NAMESPACE) in the manifest
# pass through verbatim instead of tripping template parsing.

# Fail-fast lookup by the "<cluster>-restate-snapshots" naming convention
# stage 01 establishes (terraform/01-foundation/iam.tf): if stage 01 hasn't
# been applied, this errors at plan time, instead of the pods failing to
# snapshot much later.
data "aws_iam_role" "snapshots" {
  name = "${var.cluster_name}-restate-snapshots"
}

locals {
  restate_cluster_manifest = yamldecode(
    replace(replace(replace(
      file("${path.module}/../../resources/04-restate-cluster.yaml"),
      "REPLACE_ME_SNAPSHOTS_BUCKET", var.snapshots_bucket),
      "REPLACE_ME_AWS_REGION", var.region),
    "REPLACE_ME_SNAPSHOTS_ROLE_ARN", data.aws_iam_role.snapshots.arn)
  )
}

resource "kubernetes_manifest" "restate_cluster" {
  manifest = local.restate_cluster_manifest

  # Gate initial provisioning on the cluster's Ready condition. The CR has no
  # observedGeneration, so updates that roll the StatefulSet use the explicit
  # generation-sensitive procedure in docs/05-operations.md instead.
  wait {
    condition {
      type   = "Ready"
      status = "True"
    }
  }

  # First boot pulls a ~large image on three nodes, forms the metadata
  # cluster, provisions 48 partitions — give it room.
  timeouts {
    create = "15m"
  }
}
