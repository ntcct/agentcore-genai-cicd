# agentcore-genai-cicd

A sample GenAI agent (Amazon Nova Micro via the Bedrock Converse API) on **Amazon Bedrock AgentCore Runtime**, with **separate pipelines for infrastructure and code** (same repo, path-filtered).

```
infra/**  ──► infra.yml       PR: fmt → validate → plan → PR comment
                              main: approval (env: production) → terraform apply
app/**,   ──► deploy-app.yml  PR: package → run zip on runner → HTTP contract test (no AWS)
scripts/**                    main: package → S3 upload → UpdateAgentRuntime (code only) → READY → smoke test
                              manual: rollback to a previous S3 version ID
```

| Concern | Owner | IAM role |
|---|---|---|
| Buckets, roles, runtime settings (env vars, network, lifecycle) | Terraform (`infra.yml`) | `agentcore-genai-cicd-github-actions` (broad, env `production`) |
| Agent code (zip in S3, runtime artifact) | `deploy-app.yml` + `scripts/deploy_code.py` | `agentcore-genai-cicd-app-deploy` (this bucket + this runtime only, env `app`) |

Terraform ignores `agent_runtime_artifact` and the zip object after creation, so the two pipelines never fight. `deploy_code.py` copies every other runtime setting unchanged when it updates the code. Both deploy jobs share the `agentcore-runtime` concurrency group so they never update the runtime at the same time.

## Cost choices

| Layer | Choice |
|---|---|
| Artifact | Direct code deploy (zip in S3) — no ECR, no Docker/ARM build |
| Model | `us.amazon.nova-micro-v1:0`, maxTokens 512 |
| Network | AgentCore `PUBLIC` mode, IAM SigV4 auth — no VPC/NAT |
| Runtime | Consumption-billed, idle timeout 300s, smoke-test sessions stopped |
| State / logs | S3 native lockfile (no DynamoDB), 7-day log retention |

## Layout

```
app/main.py               agent (stdlib HTTP server: GET /ping, POST /invocations)
scripts/package.py        deterministic Linux-ARM64 zip → dist/agent.zip
scripts/deploy_code.py    upload zip + update runtime code + smoke test (+ --s3-version-id rollback, --dry-run)
bootstrap/                one-time, local: state bucket, OIDC provider, infra CI role
infra/                    Terraform: artifact bucket, runtime role, runtime, app-deploy CI role
.github/workflows/        infra.yml, deploy-app.yml
```

## Repo variables

`AWS_REGION`, `TF_STATE_BUCKET`, `AWS_ROLE_ARN` (infra), `APP_DEPLOY_ROLE_ARN`, `RUNTIME_ID`, `ARTIFACT_BUCKET` (app). Values come from `terraform output` in `bootstrap/` and `infra/`.

## Rollback

```bash
aws s3api list-object-versions --bucket <artifact-bucket> --prefix agent/agent.zip
gh workflow run deploy-app.yml -f s3_version_id=<version-id>
```

## Teardown

1. `gh workflow run infra.yml -f action=destroy`
2. `cd bootstrap && terraform destroy` (empty the state bucket versions first)
