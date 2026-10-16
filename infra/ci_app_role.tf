# Narrow role for the app (code) pipeline: upload zip, update THIS runtime, invoke it.
# It cannot create/delete resources or change IAM.

locals {
  github_oidc_provider_arn = "arn:aws:iam::${local.account_id}:oidc-provider/token.actions.githubusercontent.com"
  runtime_arn              = aws_bedrockagentcore_agent_runtime.agent.agent_runtime_arn
}

data "aws_iam_policy_document" "app_deploy_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    # Only deploy-app.yml jobs running in the "app" environment
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["${var.github_sub_prefix}:environment:app"]
    }
  }
}

resource "aws_iam_role" "app_deploy" {
  name                 = "${var.project}-app-deploy"
  assume_role_policy   = data.aws_iam_policy_document.app_deploy_trust.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "app_deploy" {
  statement {
    sid       = "UploadCode"
    actions   = ["s3:PutObject", "s3:GetObject", "s3:GetObjectVersion"]
    resources = ["${aws_s3_bucket.artifacts.arn}/agent/*"]
  }

  statement {
    sid       = "ListVersions"
    actions   = ["s3:ListBucket", "s3:ListBucketVersions"]
    resources = [aws_s3_bucket.artifacts.arn]
  }

  statement {
    sid = "UpdateAndInvokeRuntime"
    actions = [
      "bedrock-agentcore:GetAgentRuntime",
      "bedrock-agentcore:UpdateAgentRuntime",
      "bedrock-agentcore:ListAgentRuntimeVersions",
      "bedrock-agentcore:InvokeAgentRuntime",
      "bedrock-agentcore:StopRuntimeSession",
    ]
    resources = [local.runtime_arn, "${local.runtime_arn}/*"]
  }

  # UpdateAgentRuntime re-submits the (unchanged) execution role
  statement {
    sid       = "PassRuntimeRole"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.runtime.arn]
    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["bedrock-agentcore.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "app_deploy" {
  name   = "app-deploy"
  role   = aws_iam_role.app_deploy.id
  policy = data.aws_iam_policy_document.app_deploy.json
}
