# ---------------------------------------------------------------------------
# Database Module — PostgreSQL (RDS / CloudSQL Generic)
# ---------------------------------------------------------------------------
# Technology-Neutral Doctrine:
# This module provisions a managed PostgreSQL instance. The interface uses
# generic naming (database_instance_class, database_name) so the module
# can be re-targeted to Google Cloud SQL or Azure Database for PostgreSQL
# by swapping the resource blocks. Consumers see only the host/port/name
# outputs and remain cloud-agnostic.
# ---------------------------------------------------------------------------

# --- Security Group ---

resource "aws_security_group" "database" {
  name_prefix = "${var.cluster_name}-${var.environment}-db-"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
    description = "PostgreSQL access from VPC"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.common_tags, {
    Name = "${var.cluster_name}-${var.environment}-db-sg"
  })

  lifecycle {
    create_before_destroy = true
  }
}

# --- DB Subnet Group ---

resource "aws_db_subnet_group" "main" {
  name       = "${var.cluster_name}-${var.environment}-db-subnet"
  subnet_ids = var.subnet_ids

  tags = merge(var.common_tags, {
    Name = "${var.cluster_name}-${var.environment}-db-subnet-group"
  })
}

# --- RDS Instance ---

resource "aws_db_instance" "main" {
  identifier     = "${var.cluster_name}-${var.environment}-postgres"
  engine         = "postgres"
  engine_version = "16.1"

  instance_class    = var.database_instance_class
  allocated_storage = var.database_allocated_storage
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = var.database_name
  username = var.database_username
  password = var.database_password

  multi_az               = var.database_multi_az
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.database.id]

  backup_retention_period = 7
  backup_window           = "03:00-04:00"
  maintenance_window      = "Mon:04:00-Mon:05:00"

  deletion_protection      = var.environment == "production" ? true : false
  skip_final_snapshot      = var.environment == "production" ? false : true
  final_snapshot_identifier = var.environment == "production" ? "${var.cluster_name}-${var.environment}-final-snapshot" : null

  performance_insights_enabled          = true
  performance_insights_retention_period = 7

  tags = merge(var.common_tags, {
    Name = "${var.cluster_name}-${var.environment}-postgres"
  })
}

# --- Variables ---

variable "environment" {
  type = string
}

variable "region" {
  type = string
}

variable "cluster_name" {
  type = string
}

variable "database_instance_class" {
  type = string
}

variable "database_name" {
  type = string
}

variable "database_username" {
  type = string
}

variable "database_password" {
  type      = string
  sensitive = true
}

variable "database_allocated_storage" {
  type    = number
  default = 100
}

variable "database_multi_az" {
  type    = bool
  default = true
}

variable "vpc_id" {
  type = string
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "subnet_ids" {
  type = list(string)
}

variable "common_tags" {
  type    = map(string)
  default = {}
}

# --- Outputs ---

output "host" {
  description = "Hostname of the primary database instance"
  value       = aws_db_instance.main.address
}

output "port" {
  description = "Port the database is listening on"
  value       = aws_db_instance.main.port
}

output "database_name" {
  description = "Name of the default database"
  value       = aws_db_instance.main.db_name
}

output "connection_string" {
  description = "PostgreSQL connection string"
  value       = "postgresql://${var.database_username}:${var.database_password}@${aws_db_instance.main.address}:${aws_db_instance.main.port}/${var.database_name}"
  sensitive   = true
}
