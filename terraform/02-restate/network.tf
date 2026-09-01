# The Service-CIDR egress policy (resources/06-restate-service-cidr-egress.yaml).
#
# Required wherever the CNI evaluates NetworkPolicy before Service DNAT — the
# EKS VPC CNI with enforcement enabled — because the operator's pod-label egress
# rule does not cover the ClusterIP it registers each service revision under.
# Without it, kubernetes_manifest.restate_compute applies cleanly and the
# RestateDeployment then sits NotReady while registration times out. The file's
# header has the mechanism.
#
# Unlike the manual path, nothing here is a placeholder to fill in: EKS reports
# the cluster's Service CIDR, so the policy is always generated with the correct
# value for this cluster. That also means it cannot drift from the cluster it
# was applied to.
#
# Applied by default. On a cluster whose CNI evaluates policy after DNAT
# (Calico, Cilium) it is unnecessary rather than harmful — it widens Restate's
# egress by one port to one CIDR of virtual IPs. Set
# create_service_cidr_egress_policy = false to skip it.
locals {
  # data.aws_eks_cluster is already declared in providers.tf for exec auth.
  service_ipv4_cidr = data.aws_eks_cluster.this.kubernetes_network_config[0].service_ipv4_cidr

  service_cidr_egress_manifest = yamldecode(
    replace(
      file("${path.module}/../../resources/06-restate-service-cidr-egress.yaml"),
      "REPLACE_ME_SERVICE_CIDR",
      local.service_ipv4_cidr,
    )
  )
}

resource "kubernetes_manifest" "service_cidr_egress" {
  count = var.create_service_cidr_egress_policy ? 1 : 0

  manifest = local.service_cidr_egress_manifest

  # The operator creates the namespace this policy lives in as part of
  # reconciling the RestateCluster, so it cannot be applied any earlier —
  # the same ordering constraint the runbook has at the end of step 4.
  depends_on = [kubernetes_manifest.restate_cluster]
}
