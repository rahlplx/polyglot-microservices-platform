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
