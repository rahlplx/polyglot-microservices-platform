# ---------------------------------------------------------------------------
# Main Terraform Configuration
# ---------------------------------------------------------------------------
# Technology-Neutral Doctrine:
# This configuration is cloud-agnostic. All provider-specific values are
# parameterized via variables so the same module can target AWS (EKS+RDS),
# GCP (GKE+CloudSQL), or Azure (AKS+PostgreSQL Flexible) without code changes.
# Only the tfvars file differs per environment.
# ---------------------------------------------------------------------------

terraform {
  # Backend configuration is injected per-environment via tfvars or CLI flags.
  # Do NOT hardcode a backend here — maintain cloud neutrality.
  # Example: terraform init -backend-config=backend.hcl
}

# ---------------------------------------------------------------------------
# Provider Configuration
# ---------------------------------------------------------------------------

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Environment = var.environment
      ManagedBy   = "terraform"
      Project     = var.project_name
    }
  }
}

# ---------------------------------------------------------------------------
# Module Orchestration
# ---------------------------------------------------------------------------

module "vpc" {
  source = "./modules/vpc"

  environment   = var.environment
  region        = var.region
  vpc_cidr      = var.vpc_cidr
  project_name  = var.project_name
}

module "kubernetes" {
  source = "./modules/kubernetes"

  environment       = var.environment
  region            = var.region
  cluster_name      = var.cluster_name
  node_count        = var.node_count
  node_instance_type = var.node_instance_type
  vpc_id            = module.vpc.vpc_id
  subnet_ids        = module.vpc.private_subnet_ids

  depends_on = [module.vpc]
}

module "database" {
  source = "./modules/database"

  environment            = var.environment
  region                 = var.region
  cluster_name           = var.cluster_name
  database_instance_class = var.database_instance_class
  database_name          = var.database_name
  database_username      = var.database_username
  vpc_id                 = module.vpc.vpc_id
  subnet_ids             = module.vpc.private_subnet_ids

  depends_on = [module.vpc]
}
