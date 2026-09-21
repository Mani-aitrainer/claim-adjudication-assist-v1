/* Documents bucket — versioned, SSE, public access blocked. */

resource "aws_s3_bucket" "documents" {
  bucket = "${var.project}-documents-${var.account_id}"

  # Learning-project choice: this bucket holds only synthetic claim/policy PDFs that
  # `make fixtures` regenerates for free, and the whole stack is meant to be destroyed
  # and recreated the same day. Without this, `terraform destroy` fails on a non-empty
  # bucket and you have to empty it by hand (versions AND delete markers) first.
  # A real deployment would leave this false.
  force_destroy = true
}

resource "aws_s3_bucket_versioning" "documents" {
  bucket = aws_s3_bucket.documents.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket                  = aws_s3_bucket.documents.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
