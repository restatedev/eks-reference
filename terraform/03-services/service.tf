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

  timeouts {
    create = "10m"
    update = "10m"
    # deletion waits on the operator's drain finalizer
    delete = "30m"
  }
}

# The provider's condition waiter does not compare status.observedGeneration
# with metadata.generation. On an update it can therefore accept Ready=True
# from the previous revision before the operator has observed the new pod
# template. Use the repository's generation-aware gate after every manifest
# change instead.
resource "terraform_data" "wait_for_service" {
  triggers_replace = sha256(jsonencode(local.service_manifest))

  depends_on = [kubernetes_manifest.service]

  provisioner "local-exec" {
    command = "'${path.module}/../../scripts/wait-restatedeployment.sh'"

    environment = {
      AWS_REGION          = var.region
      CLUSTER_NAME        = var.cluster_name
      RSD_NAME            = local.service_manifest.metadata.name
      RSD_NAMESPACE       = local.service_manifest.metadata.namespace
      RSD_TIMEOUT_SECONDS = "600"
    }
  }
}
