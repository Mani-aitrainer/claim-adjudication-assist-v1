/* ECR repository with a lifecycle policy that keeps only the last 5 images. */

resource "aws_ecr_repository" "app" {
  name                 = var.project
  image_tag_mutability = "MUTABLE"

  # Same learning-project reasoning as the S3 bucket: images are rebuilt from the
  # Dockerfile in minutes, and `terraform destroy` otherwise fails on a repository that
  # still contains images. A real deployment would leave this false.
  force_delete = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "keep_last_5" {
  repository = aws_ecr_repository.app.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 5 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 5
        }
        action = { type = "expire" }
      }
    ]
  })
}
