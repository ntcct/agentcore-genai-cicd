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

# GitHub immutable OIDC subject prefix: repo:<owner>@<owner_id>/<repo>@<repo_id>
# gh api repos/<owner>/<repo>/actions/oidc/customization/sub --jq .sub_claim_prefix
variable "github_sub_prefix" {
  type    = string
  default = "repo:ntcct@54580275/agentcore-genai-cicd@1421537516"
}
