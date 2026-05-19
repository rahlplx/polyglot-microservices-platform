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
