"""Local development gateway supervisor. Uses only Nomos's published config API."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def configure(directory, port, *, ttl=300, binary="nomos"):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    policy = directory / "policy.yaml"
    shutil.copyfile(ROOT / "policies/support.yaml", policy)
    agent_key, reviewer_key, secret = (secrets.token_hex(24) for _ in range(3))
    config = {
        "gateway": {"listen": f"127.0.0.1:{port}", "transport": "http", "rate_limit_per_minute": 10000},
        "runtime": {"deployment_mode": "unmanaged"},
        "policy": {"policy_bundle_path": str(policy)},
        "executor": {"workspace_root": str(directory), "sandbox_profile": "local"},
        "audit": {"sink": "sqlite:" + str(directory / "audit.db")},
        "approvals": {"enabled": True, "backend": "sqlite", "store_path": str(directory / "approvals.db"),
                      "ttl_seconds": ttl, "approver_principals": ["support-reviewer"]},
        "identity": {"principal": "support-worker", "agent": "dispatchdesk", "environment": "dev",
                     "api_keys": {agent_key: "support-worker", reviewer_key: "support-reviewer"},
                     "agent_secrets": {"dispatchdesk": secret}},
    }
    client = {"base_url": f"http://127.0.0.1:{port}", "bearer_token": agent_key,
              "agent_id": "dispatchdesk", "agent_secret": secret}
    for name, data in (("gateway.json", config), ("agent.json", client),
                       ("reviewer.json", {**client, "bearer_token": reviewer_key})):
        with (directory / name).open("x", encoding="utf-8") as handle:
            os.chmod(directory / name, 0o600)
            json.dump(data, handle, indent=2)
    return [binary, "serve", "-c", str(directory / "gateway.json")]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--nomos", default="nomos")
    parser.add_argument("--directory", default=".local/nomos")
    parser.add_argument("--port", type=int, default=17891)
    args = parser.parse_args()
    directory = Path(args.directory).resolve()
    if (directory / "gateway.json").exists():
        command = [args.nomos, "serve", "-c", str(directory / "gateway.json")]
    else:
        command = configure(directory, args.port, binary=args.nomos)
    print(f"Private configs in {directory}. Run the agent with agent.json; review separately with reviewer.json.", flush=True)
    raise SystemExit(subprocess.call(command))
