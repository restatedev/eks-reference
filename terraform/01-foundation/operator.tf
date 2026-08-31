# The restate-operator helm release — runbook step 3: same chart, same
# pinned version, same values file. The chart also installs the
# RestateCluster / RestateDeployment CRDs (installCrds in the values file),
# which is exactly why the CRs live in a separate stage (02-restate):
# kubernetes_manifest fetches a CRD's schema from the live cluster at PLAN
# time, so the CRs cannot even be planned until this release has been
# applied.
resource "helm_release" "restate_operator" {
  name      = "restate-operator"
  chart     = "oci://ghcr.io/restatedev/restate-operator-helm"
  version   = "3.0.1"
  namespace = "restate-operator"

  values = [file("${path.module}/../../resources/02-restate-operator.values.yaml")]

  # The target namespace comes from resources/00-namespaces.yaml rather than
  # create_namespace — same ownership split as the runbook path.
  depends_on = [kubernetes_manifest.namespaces]
}
