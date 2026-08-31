output "snapshots_bucket" {
  description = "S3 bucket for partition snapshots."
  value       = aws_s3_bucket.snapshots.bucket
}

output "snapshots_role_arn" {
  description = "IRSA role the restate ServiceAccount assumes (stage 02 re-derives this by its conventional name, not from state)."
  value       = aws_iam_role.snapshots.arn
}

output "oidc_provider_arn" {
  description = "IAM OIDC provider backing IRSA (created or looked up, per create_oidc_provider)."
  value       = local.oidc_provider_arn
}
