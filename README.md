# agentcore-genai-cicd

A sample GenAI agent (Amazon Nova Micro via the Bedrock Converse API) deployed to **Amazon Bedrock AgentCore Runtime** by **GitHub Actions + Terraform**.

```
PR ──► plan job: package zip → fmt → validate → plan → comment plan on PR
main ─► deploy job (env: production): package → plan → apply → wait READY → smoke-test invoke
manual ► workflow_dispatch: apply | destroy
```

| Layer | Choice | Why (cost) |
|---|---|---|
| Artifact | Direct code deploy (zip in S3) | No ECR, no Docker/ARM build |
| Model | `us.amazon.nova-micro-v1:0`, maxTokens 512 | Cheapest Bedrock text model |
| Network | AgentCore `PUBLIC` mode, IAM SigV4 auth | No VPC/NAT charges |
| Runtime | Consumption-billed, idle timeout 300s | Nothing billed while idle |
| State | S3 + native lockfile | No DynamoDB table |
| CI auth | GitHub OIDC → IAM role | No stored AWS keys |
| Logs | 7-day retention | Bounded CloudWatch cost |

## Layout

```
app/main.py              agent (stdlib HTTP server: GET /ping, POST /invocations)
scripts/package.py       deterministic Linux-ARM64 zip → dist/agent.zip
bootstrap/               one-time, run locally: state bucket, OIDC provider, CI role
infra/                   run by CI: artifact bucket, runtime role, AgentCore runtime, log group
.github/workflows/ci-cd.yml
```

## Invoke

```bash
aws bedrock-agentcore invoke-agent-runtime --agent-runtime-arn <arn> --qualifier DEFAULT \
  --runtime-session-id <33+ char id> --content-type application/json \
  --cli-binary-format raw-in-base64-out --payload '{"prompt":"Hello"}' response.json
```

## Teardown

1. Actions → ci-cd → Run workflow → `destroy`
2. `cd bootstrap && terraform destroy` (empty the state bucket versions first)
