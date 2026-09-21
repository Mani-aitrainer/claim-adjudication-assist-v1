output "cluster_name" {
  value = aws_eks_cluster.this.name
}

output "cluster_endpoint" {
  value = aws_eks_cluster.this.endpoint
}

output "cluster_ca_data" {
  value = aws_eks_cluster.this.certificate_authority[0].data
}

output "oidc_provider_arn" {
  value = aws_iam_openid_connect_provider.eks.arn
}

output "oidc_issuer_url" {
  value = aws_eks_cluster.this.identity[0].oidc[0].issuer
}

# EKS attaches the cluster security group to every managed node group's ENIs, so it
# doubles as the node security group for RDS/Redis ingress rules.
output "node_security_group_id" {
  value = aws_security_group.cluster.id
}
