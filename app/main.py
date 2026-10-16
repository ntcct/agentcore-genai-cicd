"""Minimal GenAI agent for Amazon Bedrock AgentCore Runtime (HTTP protocol).

Implements the AgentCore HTTP contract with the Python standard library only:
  GET  /ping         -> health check
  POST /invocations  -> {"prompt": "..."}  =>  {"result": "...", "usage": {...}}

The only third-party dependency is boto3 (pure Python), so the deployment
zip is portable to the ARM64 AgentCore runtime without a container build.
"""

import json
import logging
import os
import signal
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import boto3
from botocore.config import Config

MODEL_ID = os.environ.get("MODEL_ID", "us.amazon.nova-micro-v1:0")
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "512"))  # always set explicitly (quota reservation)
MAX_PROMPT_CHARS = 4000  # basic input validation / cost guard
PORT = 8080
SYSTEM_PROMPT = "You are a concise, helpful assistant. Answer in at most 5 sentences."

logging.basicConfig(stream=sys.stdout, level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("agent")

bedrock = boto3.client(
    "bedrock-runtime",
    config=Config(retries={"max_attempts": 5, "mode": "adaptive"}),
)


def ask_model(prompt: str) -> dict:
    """Call Bedrock Converse API and return text plus token usage."""
    response = bedrock.converse(
        modelId=MODEL_ID,
        system=[{"text": SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": MAX_TOKENS, "temperature": 0.3},
    )
    text = "".join(
        block.get("text", "") for block in response["output"]["message"]["content"]
    )
    return {"result": text, "model": MODEL_ID, "usage": response.get("usage", {})}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: dict) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):  # noqa: N802 (http.server naming)
        if self.path == "/ping":
            self._send(200, {"status": "Healthy"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path != "/invocations":
            self._send(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length) or b"{}")
            prompt = data.get("prompt")
            if not isinstance(prompt, str) or not prompt.strip():
                self._send(400, {"error": "body must be JSON with a non-empty 'prompt' string"})
                return
            if len(prompt) > MAX_PROMPT_CHARS:
                self._send(400, {"error": f"prompt exceeds {MAX_PROMPT_CHARS} characters"})
                return
            result = ask_model(prompt.strip())
            log.info("invocation ok, usage=%s", result["usage"])  # no prompt/PII in logs
            self._send(200, result)
        except json.JSONDecodeError:
            self._send(400, {"error": "invalid JSON"})
        except Exception:  # surface a generic error, keep details in logs
            log.exception("invocation failed")
            self._send(500, {"error": "internal error"})

    def log_message(self, fmt, *args):  # quieter access logs
        log.debug(fmt, *args)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    # Graceful shutdown on SIGTERM (AgentCore contract)
    signal.signal(signal.SIGTERM, lambda *_: server.shutdown())
    log.info("agent listening on :%d, model=%s", PORT, MODEL_ID)
    server.serve_forever()


if __name__ == "__main__":
    main()
