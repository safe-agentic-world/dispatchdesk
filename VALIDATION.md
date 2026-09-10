# Validation Record

## Baseline

- Host: Windows, Python 3.12.
- Nomos CLI: published v0.13.3, Windows amd64 archive verified against pinned SHA-256.
- SDK: installed from upstream Git commit `f5b35a69ab4364f5035de3dc7fe1a4db49555f1b`, not a sibling checkout.
- Local model: installed Ollama `codellama:7b`; no model download or paid inference.

## Deterministic Checks

`NOMOS_BINARY` enabled: **19 tests passed**, including ten real-gateway tests
and nine standalone tests. The integration suite also runs all eight policy
expectations using the released `nomos test` command. Workflow syntax passes
`actionlint`. Wheel and source distribution build successfully.

The test suite verifies reads/drafts, cross-tenant denial, review before writes,
reviewer identity separation, expiry, payload and recipient drift, restart/resume,
gateway unavailability, audit outcome existence, persistent idempotency, bounded
agent execution, argument validation, and refund budget limits.

## Live Model Checks

The local model read T100, consumed the tool result, created a draft, and finished.
With Nomos enabled, it read the ticket, drafted a reply, proposed a send, and paused
before any outbox mutation. Following a separate reviewer approval, a new agent
process resumed the saved request, reauthorized, queued exactly one local outbox
entry, and finished. These were genuine model proposals, not test-double responses.
Reviewer decisions during validation were supplied by the test operator through
the separate reviewer CLI; this is not evidence of an independent user.

An initial unconstrained request produced an unsupported refund/discount claim.
That pending message was rejected, and the outbox remained empty. This is an
important limitation: authorization cannot verify the truth of model-written text.
The successful send used reply text explicitly supplied in the goal. Use explicit
business policy and human review; do not interpret a green permission suite as a
model-quality or production-safety assessment.

## Observed Nomos Compatibility Issue

The v0.13.3 Windows gateway intermittently resets the connection on an agent's
unauthorized approval request rather than returning HTTP 403 (`WinError 10054`).
This happened in repeated local test runs. It did not authorize the pending action.

The default test accepts this Windows-only transport rejection **with a warning**,
then reauthorizes the pending action and asserts execution remains blocked and the
outbox empty. It subsequently verifies a valid reviewer can reject the approval.
It does not claim the HTTP contract passed. Set `STRICT_NOMOS_HTTP=1` to make a
connection reset fail the suite when diagnosing or testing an upstream fix.
Other HTTP statuses, successful self-approval, or resets on non-Windows hosts fail.

No Nomos source changes were made while building this customer application.

## Limits

- Hosted CI must independently verify the Linux/Windows and Python 3.10/3.12 matrix.
- No external email, payment provider, production account, or real customer data was used.
- Live-model output is nondeterministic; CI deliberately uses explicit planner doubles.
- Multiple concurrent writers to one session file are unsupported.
- The application is a controlled customer-style fixture, not an actual independent customer.
