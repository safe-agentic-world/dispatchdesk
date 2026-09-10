import argparse
import json
from pathlib import Path
import sys

from .agent import OllamaPlanner, run_agent
from .gates import load_gate
from .store import Store


def main():
    parser = argparse.ArgumentParser(description="DispatchDesk: local support agent; no external sends or payments")
    parser.add_argument("--db", default=".local/support.db")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    commands.add_parser("status")
    run = commands.add_parser("run")
    run.add_argument("--goal", required=True)
    run.add_argument("--model", default="codellama:7b")
    run.add_argument("--endpoint", default="http://127.0.0.1:11434")
    run.add_argument("--nomos-config", help="agent client config; omit for standalone read/draft mode")
    run.add_argument("--session", default=".local/session.json")
    run.add_argument("--resume", action="store_true")
    run.add_argument("--max-steps", type=int, default=8)
    review = commands.add_parser("review")
    review.add_argument("approval_id")
    review.add_argument("--decision", choices=["APPROVE", "DENY"], required=True)
    review.add_argument("--config", required=True, help="reviewer client config, never an agent tool")
    args = parser.parse_args()
    try:
        if args.command == "review":
            gate = load_gate(args.config)
            result = gate.client.decide_approval(args.approval_id, args.decision)
            print(json.dumps(result, indent=2))
            return 0
        store = Store(args.db)
        if args.command == "init":
            store.seed()
            print("Created synthetic tickets T100 (acme) and T200 (other tenant). No real customer data.")
        elif args.command == "status":
            print(json.dumps(store.counts(), indent=2))
        else:
            state = run_agent(store, OllamaPlanner(args.model, args.endpoint), load_gate(args.nomos_config),
                              args.goal, args.session, max_steps=args.max_steps, resume=args.resume)
            print(json.dumps({"status": state["status"], "steps": state["steps"],
                              "events": state["events"], "pending": state["pending"]}, indent=2))
            return {"finished": 0, "waiting_for_review": 3, "step_limit": 4, "denied": 5}[state["status"]]
        return 0
    except Exception as exc:
        # Errors may contain HTTP payloads; keep CLI diagnostics free of credentials.
        print(f"Stopped safely ({type(exc).__name__}). Check configuration and private session state; no automatic retry.",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
