# DispatchDesk

[![Customer compatibility](https://github.com/safe-agentic-world/dispatchdesk/actions/workflows/ci.yml/badge.svg)](https://github.com/safe-agentic-world/dispatchdesk/actions/workflows/ci.yml)

A local AI support agent that reads tickets, drafts replies, and pauses risky
operations for review. Its tools own real SQLite state: drafts, an outbox, and
a refund ledger. **No email is delivered and no money moves.**

DispatchDesk is a separately packaged customer-style application maintained by
the Nomos author, not evidence of an independent customer or production adoption.
It works without Nomos in read/draft mode. An optional adapter lets it act as an
external consumer of Nomos's released CLI and public Python SDK.

## Run Without Nomos

Requires Python 3.10+ and [Ollama](https://ollama.com/) with a local model.
The code uses Ollama's [structured JSON API](https://docs.ollama.com/capabilities/structured-outputs),
not native tool-calling support. The model proposes one action, sees the actual
result, and decides what to do next. No paid APIs, cloud telemetry, or model
downloads are triggered by the application.

```bash
git clone https://github.com/safe-agentic-world/dispatchdesk.git
cd dispatchdesk
python -m venv .venv
# macOS/Linux:
.venv/bin/python -m pip install -e .
.venv/bin/dispatchdesk init
.venv/bin/dispatchdesk run --goal "Read ticket T100 and draft a helpful reply. Do not send it." --model codellama:7b
.venv/bin/dispatchdesk status
```

On Windows use `py -3 -m venv .venv`, `.venv\Scripts\python.exe`, and
`.venv\Scripts\dispatchdesk.exe`. Use `python3` instead of `python` where needed.
Use `ollama list` to select an installed model. Install a model yourself if none
is available; model downloads can be large. Model quality affects completion,
not authorization: malformed proposals stop, denied calls do not execute, and
the agent has an eight-step default limit.

The synthetic fixtures are T100 (Acme, damaged mug, 2500 cents paid) and T200
(another tenant). Standalone mode refuses cross-tenant access, sending, and refunds.

## Add Nomos

Install the [Nomos CLI](https://github.com/safe-agentic-world/nomos#install)
(tested baseline: v0.13.3). Install the optional SDK from an immutable upstream
commit; no sibling checkout or edits to Nomos are required:

```bash
.venv/bin/python -m pip install -e '.[nomos]'
.venv/bin/python scripts/gateway.py --nomos /path/to/nomos
```

Leave that gateway running. In a second terminal, from this checkout:

```bash
.venv/bin/dispatchdesk run --goal "Read T100 and send a helpful reply about the damaged mug." --nomos-config .local/nomos/agent.json --session .local/send.json
```

The agent stops with exit code 3 and prints the exact pending request and approval
ID. Inspect the ticket, recipient in trusted storage, and pending arguments. In a
reviewer terminal, approve or deny using the separate reviewer identity:

```bash
.venv/bin/dispatchdesk review APPROVAL_ID --decision APPROVE --config .local/nomos/reviewer.json
.venv/bin/dispatchdesk run --goal "Read T100 and send a helpful reply about the damaged mug." --nomos-config .local/nomos/agent.json --session .local/send.json --resume
```

Resume uses the saved request and reauthorizes it. Resume itself never grants
approval. Rejections, expiration, changed arguments, and unavailable gateways
must leave business side effects untouched. `status` shows local row counts;
inspect `.local/support.db` for content. The `refund_order` tool records a local
refund only after review and cannot exceed the ticket's remaining paid amount.

## Test As A Customer

```bash
.venv/bin/python -m unittest discover -s tests -v
nomos test --suite policies/permissions.json --bundle policies/support.yaml
# macOS/Linux: enable real gateway integration tests
NOMOS_BINARY=/absolute/path/to/nomos .venv/bin/python -m unittest discover -s tests -v
```

PowerShell: set `$env:NOMOS_BINARY = 'C:\path\to\nomos.exe'` before running tests.
Without this variable, gateway tests explicitly skip. Core tests need no Nomos,
SDK, model, or network. They use a named planner test double, not a pretend LLM.
The real-model path uses Ollama and is validated separately from deterministic CI.

See [the known Windows HTTP rejection issue](VALIDATION.md#observed-nomos-compatibility-issue).
Set `STRICT_NOMOS_HTTP=1` to fail on the observed connection reset rather than
accepting it with a warning and verifying the action still cannot execute.

CI installs the released Nomos binary with pinned checksums and the SDK's pinned
Git dependency. To try a future Nomos build, change only `NOMOS_BINARY` locally.
To test a future SDK, install that version explicitly in this project's virtual
environment. Run the same customer tests before adopting a new baseline.

## Architecture And Limits

CLI exit codes: `0` finished, `2` error, `3` awaiting review, `4` step limit,
and `5` denied. A denial ends the run instead of asking the model to work around it.

- `store.py`: business validation and transactional SQLite side effects; no Nomos imports.
- `agent.py`: local model adapter, bounded agent loop, saved intent and conversation.
- `gates.py`: standalone read/draft rules or the optional Nomos public-SDK adapter.
- `policies/`: customer-owned policy and eight offline permission expectations.
- `tests/`: business invariants and black-box integration tests against a real gateway.

Ticket IDs, tool names, argument fields, and types are validated. Recipients and
tenant scope come from storage, not model-supplied routing. Operation IDs are
application-generated; side effects and receipts commit atomically. Retrying the
same operation after a crash cannot duplicate its SQLite mutation. This does not
provide exactly-once delivery to a future external provider, or deduplicate a new
agent run that independently requests the same business action.

This is **not a sandbox**. The host process is trusted and can access local files;
the model only receives the bounded tool interface. Reviewer credentials are not
agent tools, but local development runs share an OS account. Production would
need process/credential isolation, a real identity provider, external-provider
idempotency and reconciliation, and hardened transport. Endpoint URLs are local
HTTP only. Authorization does not decide whether an otherwise permitted message
is truthful or appropriate.

Keep `.local/` private: it holds synthetic conversations, sessions, databases, and
generated credentials. Do not add real customer data without an appropriate
security review. Only one process should write a session at a time. Use a new
`--session` for each new task; use `--resume` only for the same task and database.

## Contribute

See [CONTRIBUTING.md](CONTRIBUTING.md) for environment setup, validation commands,
and pull request expectations. Sanitized failing cases are welcome. Do not commit
databases, credentials, virtual environments, or private session files.

MIT licensed. See [LICENSE](LICENSE) and [VALIDATION.md](VALIDATION.md).
