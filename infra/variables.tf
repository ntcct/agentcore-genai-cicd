variable "region" {
  type    = string
  default = "us-east-1"
}

variable "project" {
  type    = string
  default = "agentcore-genai-cicd"
}

variable "model_id" {
  description = "Bedrock inference profile ID. Nova Micro = cheapest text model."
  type        = string
  default     = "us.amazon.nova-micro-v1:0"
}

variable "artifact_path" {
  description = "Path to the agent zip built by scripts/package.py"
  type        = string
  default     = "../dist/agent.zip"
}

variable "log_retention_days" {
  type    = number
  default = 7
}
