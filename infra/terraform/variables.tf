# ---------------------------------------------------------------------------
# Input Variables
# ---------------------------------------------------------------------------
# Technology-Neutral Doctrine:
# Variables are defined generically (e.g., node_instance_type instead of
# aws_instance_type) so the same variable set maps to any cloud provider.
# Provider-specific mappings happen in the module implementations.
# ---------------------------------------------------------------------------

# --- Project ---

variable "project_name" {
  description = "Project name used as a prefix for all resources"
  type        = string
  default     = "polyglot-platform"
}

variable "environment" {
  description = "Deployment environment (production, staging, development)"
  type        = string

  validation {
    condition     = contains(["production", "staging", "development"], var.environment)
    error_message = "Environment must be one of: production, staging, development."
  }
}

# --- Cluster ---

variable "cluster_name" {
  description = "Kubernetes cluster name"
  type        = string
  default     = "polyglot-platform"
}

variable "region" {
  description = "Cloud region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "node_count" {
  description = "Number of worker nodes in the Kubernetes cluster"
  type        = number
  default     = 3

  validation {
    condition     = var.node_count >= 1
    error_message = "Node count must be at least 1."
  }
}

variable "node_instance_type" {
  description = "Instance type for Kubernetes worker nodes (cloud-agnostic label)"
  type        = string
  default     = "m5.large"
}

# --- VPC ---

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "public_subnet_count" {
  description = "Number of public subnets"
  type        = number
  default     = 3
}

variable "private_subnet_count" {
  description = "Number of private subnets"
  type        = number
  default     = 3
}

# --- Database ---

variable "database_instance_class" {
  description = "Database instance class (cloud-agnostic, maps to RDS/CloudSQL tier)"
  type        = string
  default     = "db.r6g.large"
}

variable "database_name" {
  description = "Default database name to create"
  type        = string
  default     = "platform"
}

variable "database_username" {
  description = "Master database username"
  type        = string
  default     = "platform_admin"
  sensitive   = true
}

variable "database_password" {
  description = "Master database password"
  type        = string
  sensitive   = true
}

variable "database_allocated_storage" {
  description = "Allocated storage in GB for the database instance"
  type        = number
  default     = 100
}

variable "database_multi_az" {
  description = "Enable Multi-AZ deployment for database HA"
  type        = bool
  default     = true
}

# --- Tags ---

variable "common_tags" {
  description = "Common tags applied to all resources"
  type        = map(string)
  default     = {}
}
