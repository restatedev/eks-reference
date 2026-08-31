output "restate_cluster_name" {
  description = "Name of the RestateCluster CR — also the namespace the operator creates for it."
  value       = local.restate_cluster_manifest.metadata.name
}

output "port_forward_hint" {
  description = "Reach ingress (8080) and the deliberately-unexposed admin API (9070) — see runbook step 6."
  value       = "kubectl -n ${local.restate_cluster_manifest.metadata.name} port-forward svc/restate 8080:8080 9070:9070"
}
