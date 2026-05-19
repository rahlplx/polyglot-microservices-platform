# ---------------------------------------------------------------------------
# Terraform & Provider Version Constraints
# ---------------------------------------------------------------------------
# Technology-Neutral Doctrine:
# Version constraints pin the minimum required versions for reproducibility.
# The AWS provider is used as the default implementation, but the module
# interface is designed so that GCP or Azure providers could be substituted
# without changing variable or output definitions.
# ---------------------------------------------------------------------------

terraform {
  required_version = ">= 1.7.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.40.0, < 6.0.0"
    }

    # Kubernetes provider — used for post-creation cluster configuration
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = ">= 2.30.0, < 3.0.0"
    }

    # Helm provider — for deploying platform charts (ArgoCD, SPIRE, etc.)
    helm = {
      source  = "hashicorp/helm"
      version = ">= 2.14.0, < 3.0.0"
    }

    # PostgreSQL provider — for database initialization (roles, extensions)
    postgresql = {
      source  = "cyrilgdn/postgresql"
      version = ">= 1.23.0, < 2.0.0"
    }

    # Random provider — for generating passwords and unique identifiers
    random = {
      source  = "hashicorp/random"
      version = ">= 3.6.0, < 4.0.0"
    }
  }
}
