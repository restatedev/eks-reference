# The snapshots bucket, matching docs/01-prerequisites.md: dedicated to this
# cluster, public access blocked, SSL enforced. Default SSE-S3 encryption is
# implicit (all new S3 objects are SSE-S3 encrypted), and no lifecycle rules
# are configured, on the expectation that Restate prunes to NUM_RETAINED in the
# cluster manifest (2) rather than growing without bound.
#
# Whether pruning actually happens was NOT proven here. A live cluster measured
# 144 objects after one snapshot round and 288 after two, and the observed key
# layout is one directory per snapshot:
#
#   restate/snapshots/<partition-id>/lsn_<padded-lsn>-snap_<snapshot-id>/
#       metadata.json
#       <nnnnnn>.sst
#
# 288 = 48 partitions x 2 snapshots x 3 objects, and partition 10 was observed
# holding exactly two snapshot directories (lsn 2 and lsn 3121). That is exactly
# the NUM_RETAINED=2 cap, so it is equally consistent with pruning working and
# with only two rounds having been taken. A third round would separate the two
# and the cluster came down first.
#
# Do NOT reach for an age-based aws_s3_bucket_lifecycle_configuration as the
# safety net. Snapshots are per partition, and a partition with no traffic keeps
# its single snapshot indefinitely and legitimately — an expiration rule would
# delete the only bootstrap material that partition has, which is worse than an
# oversized bucket. If growth here matters to you, verify NUM_RETAINED empirically
# on your own cluster by taking three rounds and counting, and treat the bucket as
# Restate-managed rather than lifecycle-managed.
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
