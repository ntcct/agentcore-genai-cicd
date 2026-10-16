"""Deploy agent code to an existing AgentCore Runtime (no Terraform).

Steps:
  1. Upload dist/agent.zip to S3 (skipped if identical to what's deployed).
  2. Read the runtime's current config and call UpdateAgentRuntime with ONLY
     the code artifact changed. Everything else (role, network, env vars,
     lifecycle...) is copied as-is, so Terraform-managed settings are kept.
  3. Wait for READY, then smoke-test the new version.

Rollback: --s3-version-id <id> redeploys an earlier zip without uploading.

Usage:
  python scripts/deploy_code.py --runtime-id <id> --bucket <bucket> [--dry-run]
"""

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
KEY = "agent/agent.zip"

# Fields UpdateAgentRuntime accepts that we carry over unchanged from GetAgentRuntime
CARRY_OVER = [
    "roleArn", "networkConfiguration", "description", "authorizerConfiguration",
    "requestHeaderConfiguration", "protocolConfiguration", "lifecycleConfiguration",
    "metadataConfiguration", "environmentVariables", "filesystemConfigurations",
    "capacityProviderConfiguration", "platformVersion",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def set_output(name: str, value: str) -> None:
    """Expose a value to later GitHub Actions steps (no-op locally)."""
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def upload_if_changed(s3, bucket: str, zip_path: Path) -> str:
    digest = sha256(zip_path)
    try:
        head = s3.head_object(Bucket=bucket, Key=KEY)
        if head.get("Metadata", {}).get("sha256") == digest:
            print(f"zip unchanged (sha256 {digest[:12]}), reusing S3 version {head['VersionId']}")
            return head["VersionId"]
    except s3.exceptions.ClientError:
        pass  # no object yet
    resp = s3.put_object(
        Bucket=bucket, Key=KEY, Body=zip_path.read_bytes(),
        ContentType="application/zip", Metadata={"sha256": digest},
    )
    print(f"uploaded s3://{bucket}/{KEY} version {resp['VersionId']} (sha256 {digest[:12]})")
    return resp["VersionId"]


def build_update(current: dict, bucket: str, version_id: str) -> dict:
    artifact = current["agentRuntimeArtifact"]
    if "codeConfiguration" not in artifact:
        sys.exit("runtime uses a container artifact; this script only handles code (zip) deployments")
    code_cfg = json.loads(json.dumps(artifact["codeConfiguration"]))  # deep copy
    code_cfg["code"]["s3"] = {"bucket": bucket, "prefix": KEY, "versionId": version_id}

    update = {"agentRuntimeId": current["agentRuntimeId"],
              "agentRuntimeArtifact": {"codeConfiguration": code_cfg}}
    for field in CARRY_OVER:
        if current.get(field):
            update[field] = current[field]
    # Strip read-only, service-managed keys from VPC config if present
    nmc = update.get("networkConfiguration", {}).get("networkModeConfig")
    if nmc:
        update["networkConfiguration"]["networkModeConfig"] = {
            k: nmc[k] for k in ("securityGroups", "subnets") if k in nmc
        }
    return update


def wait_ready(ctl, runtime_id: str, timeout_s: int = 600) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        rt = ctl.get_agent_runtime(agentRuntimeId=runtime_id)
        print(f"status={rt['status']} version={rt['agentRuntimeVersion']}")
        if rt["status"] == "READY":
            return rt
        if "FAILED" in rt["status"]:
            sys.exit(f"runtime update failed: {rt.get('failureReason')}")
        time.sleep(10)
    sys.exit("timed out waiting for READY")


def smoke_test(data, runtime_arn: str) -> None:
    session_id = f"deploy-smoke-{uuid.uuid4()}"
    resp = data.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn, qualifier="DEFAULT", runtimeSessionId=session_id,
        contentType="application/json",
        payload=json.dumps({"prompt": "Reply with one short friendly sentence."}).encode(),
    )
    body = json.loads(resp["response"].read())
    print("smoke test:", json.dumps(body))
    try:  # release the session right away (stops idle memory billing)
        data.stop_runtime_session(agentRuntimeArn=runtime_arn, qualifier="DEFAULT",
                                  runtimeSessionId=session_id)
    except Exception as exc:  # non-fatal
        print(f"warning: stop_runtime_session failed: {exc}")
    if "result" not in body:
        sys.exit("smoke test failed: no 'result' in response")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--runtime-id", required=True)
    p.add_argument("--bucket", required=True)
    p.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    p.add_argument("--zip", default=str(ROOT / "dist" / "agent.zip"))
    p.add_argument("--s3-version-id", help="rollback: deploy this existing S3 version instead of uploading")
    p.add_argument("--dry-run", action="store_true", help="print the update request, change nothing")
    args = p.parse_args()

    s3 = boto3.client("s3", region_name=args.region)
    ctl = boto3.client("bedrock-agentcore-control", region_name=args.region)
    data = boto3.client("bedrock-agentcore", region_name=args.region)

    current = ctl.get_agent_runtime(agentRuntimeId=args.runtime_id)
    deployed = current["agentRuntimeArtifact"].get("codeConfiguration", {}).get("code", {}).get("s3", {})
    print(f"current version {current['agentRuntimeVersion']}, S3 version {deployed.get('versionId')}")

    if args.dry_run:
        version_id = args.s3_version_id or "<new-upload>"
        print(json.dumps(build_update(current, args.bucket, version_id), indent=1, default=str))
        return

    version_id = args.s3_version_id or upload_if_changed(s3, args.bucket, Path(args.zip))
    if deployed.get("versionId") == version_id and deployed.get("prefix") == KEY:
        print("runtime already runs this code; nothing to deploy")
        set_output("runtime_version", current["agentRuntimeVersion"])
        return

    ctl.update_agent_runtime(**build_update(current, args.bucket, version_id))
    rt = wait_ready(ctl, args.runtime_id)
    smoke_test(data, rt["agentRuntimeArn"])
    set_output("runtime_version", rt["agentRuntimeVersion"])
    print(f"deployed runtime version {rt['agentRuntimeVersion']} (S3 version {version_id})")


if __name__ == "__main__":
    main()
