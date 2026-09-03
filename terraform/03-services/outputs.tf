output "service_name" {
  value = local.service_manifest.metadata.name
}

output "ingress_port_forward_hint" {
  description = "Open a local connection to Restate ingress; the invocation path depends on the deployed SDK service."
  value       = "kubectl -n restate port-forward svc/restate 8080:8080"
}
