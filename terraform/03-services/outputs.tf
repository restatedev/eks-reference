output "service_name" {
  value = local.service_manifest.metadata.name
}

output "invoke_hint" {
  value = "kubectl -n restate port-forward svc/restate 8080:8080 & curl localhost:8080/Greeter/greet --json '\"Restate\"'"
}
