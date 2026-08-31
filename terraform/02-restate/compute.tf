# The RestateDeployment skeleton (resources/05-restate-compute.yaml) — only
# deployed once there is a service image. An empty service_image skips it,
# the same as stopping the runbook before step 5.
#
# Destroy note: the operator puts a finalizer on RestateDeployments to drain
# revisions gracefully (docs/03-deploying-services.md) — `terraform destroy`
# blocks until no revision has pinned invocations and the drain delay has
# passed. That's the graceful path working, not a hang.
resource "kubernetes_manifest" "restate_compute" {
  count = var.service_image == "" ? 0 : 1

  manifest = yamldecode(
    replace(
      file("${path.module}/../../resources/05-restate-compute.yaml"),
      "REPLACE_ME_SERVICE_IMAGE",
      var.service_image,
    )
  )

  # Not strictly required — the operator retries registration — but ordering
  # compute after the cluster is Ready avoids a burst of registration
  # failures in the operator logs on a fresh install.
  depends_on = [kubernetes_manifest.restate_cluster]
}
