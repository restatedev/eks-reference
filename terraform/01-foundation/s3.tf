# The snapshots bucket, matching docs/01-prerequisites.md: dedicated to this
# cluster, public access blocked, SSL enforced. Default SSE-S3 encryption is
# implicit (all new S3 objects are SSE-S3 encrypted), and no lifecycle rules
# are wanted — Restate itself retains a bounded number of snapshots per
# partition (NUM_RETAINED in the cluster manifest).
#
# The runbook path assumes a pre-created bucket; here Terraform owns it.
# force_destroy stays at its false default on purpose: `terraform destroy`
# refuses to delete a bucket that still holds snapshots — empty it
# deliberately first if you really mean to.
resource "aws_s3_bucket" "snapshots" {
  bucket = var.snapshots_bucket
}

resource "aws_s3_bucket_public_access_block" "snapshots" {
  bucket = aws_s3_bucket.snapshots.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

data "aws_iam_policy_document" "bucket_ssl_only" {
  statement {
    sid     = "DenyInsecureTransport"
    effect  = "Deny"
    actions = ["s3:*"]

    resources = [
      aws_s3_bucket.snapshots.arn,
      "${aws_s3_bucket.snapshots.arn}/*",
    ]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "snapshots" {
  bucket = aws_s3_bucket.snapshots.id
  policy = data.aws_iam_policy_document.bucket_ssl_only.json

  # public-access-block first, so a bucket policy never exists without the
  # block-public-policy guard already in place
  depends_on = [aws_s3_bucket_public_access_block.snapshots]
}
