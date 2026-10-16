data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  # Runtime names: letters, digits, underscores only
  runtime_name = replace(var.project, "-", "_")
  # "us.amazon.nova-micro-v1:0" -> "amazon.nova-micro-v1:0"
  base_model_id = join(".", slice(split(".", var.model_id), 1, length(split(".", var.model_id))))
}

# ---------------- Artifact bucket (agent code zip) ----------------
resource "aws_s3_bucket" "artifacts" {
  bucket        = "${var.project}-artifacts-${local.account_id}"
  force_destroy = true # sample project: allow clean destroy
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    id     = "expire-old-builds"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration { noncurrent_days = 14 }
  }
}

# Uploading a new zip creates a new S3 version -> runtime update below.
resource "aws_s3_object" "agent_zip" {
  bucket      = aws_s3_bucket.artifacts.id
  key         = "agent/agent.zip"
  source      = var.artifact_path
  source_hash = filemd5(var.artifact_path)

  depends_on = [aws_s3_bucket_versioning.artifacts]
}

# ---------------- Runtime execution role (least privilege) ----------------
data "aws_iam_policy_document" "runtime_trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }
    # Confused-deputy protection
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:aws:bedrock-agentcore:${var.region}:${local.account_id}:*"]
    }
  }
}

resource "aws_iam_role" "runtime" {
  name               = "${var.project}-runtime"
  assume_role_policy = data.aws_iam_policy_document.runtime_trust.json
}

data "aws_iam_policy_document" "runtime" {
  statement {
    sid     = "InvokeModel"
    actions = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = [
      "arn:aws:bedrock:${var.region}:${local.account_id}:inference-profile/${var.model_id}",
      "arn:aws:bedrock:*::foundation-model/${local.base_model_id}", # cross-region routing targets
    ]
  }

  statement {
    sid       = "ReadCode"
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["${aws_s3_bucket.artifacts.arn}/*"]
  }

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
    resources = ["arn:aws:logs:${var.region}:${local.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*"]
  }

  statement {
    sid       = "DescribeLogGroups"
    actions   = ["logs:DescribeLogGroups"]
    resources = ["*"]
  }

  statement {
    sid       = "Metrics"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = ["bedrock-agentcore"]
    }
  }

  statement {
    sid       = "Traces"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "runtime" {
  name   = "runtime"
  role   = aws_iam_role.runtime.id
  policy = data.aws_iam_policy_document.runtime.json
}

# IAM is eventually consistent; give the new role time to propagate.
resource "time_sleep" "iam_propagation" {
  create_duration = "20s"
  triggers = {
    policy = aws_iam_role_policy.runtime.policy
  }
}

# ---------------- AgentCore Runtime (direct code deployment, no container) ----------------
resource "aws_bedrockagentcore_agent_runtime" "agent" {
  agent_runtime_name = local.runtime_name
  description        = "Sample GenAI agent deployed by GitHub Actions + Terraform"
  role_arn           = aws_iam_role.runtime.arn

  agent_runtime_artifact {
    code_configuration {
      entry_point = ["main.py"]
      runtime     = "PYTHON_3_13"
      code {
        s3 {
          bucket     = aws_s3_object.agent_zip.bucket
          prefix     = aws_s3_object.agent_zip.key
          version_id = aws_s3_object.agent_zip.version_id
        }
      }
    }
  }

  environment_variables = {
    MODEL_ID   = var.model_id
    MAX_TOKENS = "512"
    LOG_LEVEL  = "INFO"
  }

  # PUBLIC = no VPC/NAT cost. Inbound calls still require IAM SigV4 auth.
  network_configuration {
    network_mode = "PUBLIC"
  }

  protocol_configuration {
    server_protocol = "HTTP"
  }

  # Shorter idle timeout = less billed session memory
  lifecycle_configuration {
    idle_runtime_session_timeout = 300
    max_lifetime                 = 3600
  }

  depends_on = [time_sleep.iam_propagation]
}

# Pre-create the runtime log group to enforce retention (default is never expire).
resource "aws_cloudwatch_log_group" "runtime" {
  name              = "/aws/bedrock-agentcore/runtimes/${aws_bedrockagentcore_agent_runtime.agent.agent_runtime_id}-DEFAULT"
  retention_in_days = var.log_retention_days
}
