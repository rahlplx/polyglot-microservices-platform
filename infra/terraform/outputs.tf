# ---------------------------------------------------------------------------
# Output Values
# ---------------------------------------------------------------------------
# Technology-Neutral Doctrine:
# Outputs expose cloud-agnostic identifiers. Concrete resource ARNs or IDs
# are included for operational convenience but are not required for
# cross-environment portability.
# ---------------------------------------------------------------------------

# --- VPC ---

output "vpc_id" {
  description = "ID of the created VPC"
  value       = module.vpc.vpc_id
}

output "vpc_cidr" {
  description = "CIDR block of the created VPC"
  value       = module.vpc.vpc_cidr
}

output "public_subnet_ids" {
  description = "IDs of the public subnets"
  value       = module.vpc.public_subnet_ids
}

output "private_subnet_ids" {
  description = "IDs of the private subnets"
  value       = module.vpc.private_subnet_ids
}

# --- Kubernetes ---

output "cluster_endpoint" {
  description = "Endpoint for the Kubernetes API server"
  value       = module.kubernetes.cluster_endpoint
}

output "cluster_name" {
  description = "Name of the Kubernetes cluster"
  value       = module.kubernetes.cluster_name
}

output "cluster_certificate_authority_data" {
  description = "Base64-encoded certificate authority data for the cluster"
  value       = module.kubernetes.cluster_certificate_authority_data
  sensitive   = true
}

# --- Database ---

output "database_host" {
  description = "Hostname of the primary database instance"
  value       = module.database.host
}

output "database_port" {
  description = "Port the database is listening on"
  value       = module.database.port
}

output "database_name" {
  description = "Name of the default database"
  value       = module.database.database_name
}

output "database_connection_string" {
  description = "Connection string for the primary database (sensitive)"
  value       = module.database.connection_string
  sensitive   = true
}
