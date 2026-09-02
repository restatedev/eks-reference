# The example RestateDeployment from resources/05-restate-compute.yaml with its
# image placeholder filled in. Kept in its own state, separate from the cluster
# stages, so an image bump is an application change rather than an
# infrastructure one.
locals {
  service_manifest = yamldecode(
    replace(
      file("${path.module}/../../resources/05-restate-compute.yaml"),
      "REPLACE_ME_SERVICE_IMAGE",
      var.service_image,
    )
  )
}

resource "kubernetes_manifest" "service" {
  manifest = local.service_manifest

  wait {
    condition {
      type   = "Ready"
      status = "True"
    }
  }

  timeouts {
    create = "10m"
    update = "10m"
    # deletion waits on the operator's drain finalizer
    delete = "30m"
  }
}
