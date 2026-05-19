# ---------------------------------------------------------------------------
# Kubernetes Cluster Module
# ---------------------------------------------------------------------------
# Technology-Neutral Doctrine:
# This module provisions a managed Kubernetes cluster. While the implementation
# uses AWS EKS, the input/output interface is generic (cluster_name, node_count,
# node_instance_type) so the module can be swapped for GKE or AKS by replacing
# only the resource blocks — no variable or output changes needed by consumers.
# ---------------------------------------------------------------------------

resource "aws_eks_cluster" "main" {
  name     = var.cluster_name
  role_arn = aws_iam_role.cluster.arn
  version  = "1.29"

  vpc_config {
    subnet_ids = var.subnet_ids

    endpoint_private_access = true
    endpoint_public_access  = true
  }

  tags = merge(var.common_tags, {
    Name = "${var.cluster_name}-${var.environment}"
  })
}

# --- IAM Role for Cluster ---

resource "aws_iam_role" "cluster" {
  name = "${var.cluster_name}-${var.environment}-cluster-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "eks.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "cluster_policy" {
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
  role       = aws_iam_role.cluster.name
}

# --- Node Group ---

resource "aws_eks_node_group" "main" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = "${var.cluster_name}-${var.environment}-nodes"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = var.subnet_ids

  scaling_config {
    desired_size = var.node_count
    max_size     = var.node_count * 2
    min_size     = max(1, var.node_count - 1)
  }

  instance_types = [var.node_instance_type]

  tags = merge(var.common_tags, {
    Name = "${var.cluster_name}-${var.environment}-node"
  })

  depends_on = [
    aws_iam_role_policy_attachment.node_policy,
  ]
}

# --- IAM Role for Nodes ---

resource "aws_iam_role" "node" {
  name = "${var.cluster_name}-${var.environment}-node-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ec2.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "node_policy" {
  for_each = toset([
    "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
    "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
  ])

  policy_arn = each.value
  role       = aws_iam_role.node.name
}
