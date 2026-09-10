# Contributing To DispatchDesk

Keep DispatchDesk useful as a standalone support application and as a consumer
of Nomos's public APIs. Do not import Nomos internals or depend on a sibling
checkout. Changes should have a small, reproducible example and regression test.

## Development Setup

Use Python 3.10+ and Git. From this repository:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m build
.venv/bin/python -m pip check
```

Windows: create the environment with `py -3 -m venv .venv`, then replace
`.venv/bin/python` with `.venv\Scripts\python.exe`. Activation is not required.
The default suite skips gateway tests if `NOMOS_BINARY` is unset; model access
is not required for deterministic tests.

## Integration Validation

Install the optional SDK with `python -m pip install -e '.[dev,nomos]'` using
your virtual environment's Python. Point `NOMOS_BINARY` at the release or
candidate build, then rerun the full suite:

```bash
NOMOS_BINARY=/absolute/path/to/nomos .venv/bin/python -m unittest discover -s tests -v
```

In PowerShell set `$env:NOMOS_BINARY = 'C:\path\to\nomos.exe'` first. Set
`STRICT_NOMOS_HTTP=1` when testing the known Windows HTTP rejection issue;
see [VALIDATION.md](VALIDATION.md). For live-model checks follow the
[README](README.md); report the model and exact goal separately from CI results.

## Code And Pull Requests

- Use four-space Python indentation, descriptive names, and small modules.
- Keep core runtime dependencies empty; add optional integrations as extras.
- Keep policy decisions separate from business validation and side effects.
- Test denied actions by checking that business state did not change.
- Preserve approval binding, explicit review, and transactional idempotency.
- Use focused commit subjects such as `fix: reject changed review payloads`,
  `docs: clarify setup`, or `chore: update development tooling`.
- Explain the change, tests run, compatibility impact, and any new dependencies.
  Update documentation when commands or behavior change.

Do not publish databases, credentials, transcripts, or customer data. For a
potential vulnerability, request a private reporting channel in a minimal issue
without disclosing exploit details or sensitive payloads. Share a sanitized
reproducer only after a private channel has been agreed.
