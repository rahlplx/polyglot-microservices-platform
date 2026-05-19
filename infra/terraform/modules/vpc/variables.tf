variable "environment" {
  type = string
}

variable "region" {
  type = string
}

variable "vpc_cidr" {
  type = string
}

variable "project_name" {
  type = string
}

variable "public_subnet_count" {
  type    = number
  default = 3
}

variable "private_subnet_count" {
  type    = number
  default = 3
}

variable "common_tags" {
  type    = map(string)
  default = {}
}
