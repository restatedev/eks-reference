# The Kubernetes objects that need no CRD, decoded straight from the
# canonical manifests in resources/ — applied 1:1 with what `kubectl apply`
# would do on the runbook path. Comments live in the YAML; yamldecode strips
# them from what's sent to the API, which is fine.

locals {
  # resources/00-namespaces.yaml is a multi-document file; "\n---" only ever
  # appears in it as a document separator.
  namespace_file_docs = [
    for doc in split("\n---", file("${path.module}/../../resources/00-namespaces.yaml")) :
    yamldecode(doc) if trimspace(doc) != ""
  ]

  namespaces = {
    for m in local.namespace_file_docs :
    m.metadata.name => m if m.kind == "Namespace"
  }

  # the restate-apps inbound-isolation policy (why it exists: comments in the
  # YAML, and docs/00-architecture.md#cross-namespace-networking)
  network_policies = {
    for m in local.namespace_file_docs :
    "${m.metadata.namespace}/${m.metadata.name}" => m if m.kind == "NetworkPolicy"
  }
}

resource "kubernetes_manifest" "namespaces" {
  for_each = local.namespaces
  manifest = each.value
}

# A separate resource rather than one for_each over all documents: instances
# of a single for_each are created in parallel, and the NetworkPolicy must
# not race the creation of the namespace it lives in.
resource "kubernetes_manifest" "network_policies" {
  for_each   = local.network_policies
  manifest   = each.value
  depends_on = [kubernetes_manifest.namespaces]
}

resource "kubernetes_manifest" "gp3_storage_class" {
  manifest = yamldecode(file("${path.module}/../../resources/03-gp3-storageclass.yaml"))
}
