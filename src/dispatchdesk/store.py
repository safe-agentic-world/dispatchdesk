"""Durable local support operations. No email provider or payment network."""
import hashlib
from contextlib import contextmanager
import json
import sqlite3
from pathlib import Path


TOOL_FIELDS = {
    "read_ticket": {"ticket_id"},
    "draft_reply": {"ticket_id", "body"},
    "send_reply": {"ticket_id", "body"},
    "refund_order": {"ticket_id", "amount_cents", "reason"},
}


def validate(tool, arguments):
    if tool not in TOOL_FIELDS:
        raise ValueError("Unknown tool")
    if not isinstance(arguments, dict) or set(arguments) != TOOL_FIELDS[tool]:
        raise ValueError("Missing or unknown tool arguments")
    if arguments.get("ticket_id") not in {"T100", "T200"}:
        raise ValueError("Unknown ticket ID")
    for field in ("body", "reason"):
        if field in arguments and (not isinstance(arguments[field], str)
                                   or not arguments[field].strip()
                                   or len(arguments[field]) > 4000):
            raise ValueError(f"Invalid {field}")
    if "amount_cents" in arguments:
        amount = arguments["amount_cents"]
        if type(amount) is not int or not 1 <= amount <= 100000:
            raise ValueError("amount_cents must be a positive integer <= 100000")


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tickets (
                    id TEXT PRIMARY KEY, customer TEXT NOT NULL, tenant TEXT NOT NULL,
                    subject TEXT NOT NULL, body TEXT NOT NULL, paid_cents INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS operations (
                    id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, result TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS drafts (
                    operation_id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS outbox (
                    operation_id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL,
                    recipient TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS refunds (
                    operation_id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL,
                    amount_cents INTEGER NOT NULL, reason TEXT NOT NULL);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def seed(self):
        with self.connect() as db:
            db.executemany("INSERT OR IGNORE INTO tickets VALUES (?, ?, ?, ?, ?, ?)", [
                ("T100", "alex@example.test", "acme", "Damaged mug",
                 "My mug arrived cracked. Please explain my options and arrange a replacement or refund.", 2500),
                ("T200", "sam@example.test", "other", "Missing order",
                 "My order has not arrived. Can you check it?", 4000),
            ])

    def ticket(self, ticket_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            raise ValueError("Ticket not found")
        return dict(row)

    def resource(self, ticket_id):
        # Resource scope and recipient come from trusted storage, never the model.
        ticket = self.ticket(ticket_id)
        return f"support://{ticket['tenant']}/tickets/{ticket['id']}"

    def execute(self, tool, arguments, operation_id, *, expected_recipient=None):
        validate(tool, arguments)
        if tool == "read_ticket":
            return self.ticket(arguments["ticket_id"])
        fingerprint = hashlib.sha256(json.dumps(
            [tool, arguments], sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()).hexdigest()
        with self.connect() as db:
            # Serialize idempotency lookup + side effect + receipt in one transaction.
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT * FROM operations WHERE id = ?", (operation_id,)).fetchone()
            if previous:
                if previous["fingerprint"] != fingerprint:
                    raise ValueError("Operation ID reused with changed arguments")
                return json.loads(previous["result"])
            ticket = db.execute("SELECT * FROM tickets WHERE id = ?", (arguments["ticket_id"],)).fetchone()
            if ticket is None:
                raise ValueError("Ticket not found")
            if tool == "send_reply" and expected_recipient is not None and ticket["customer"] != expected_recipient:
                raise ValueError("Recipient changed after authorization")
            if tool == "draft_reply":
                db.execute("INSERT INTO drafts VALUES (?, ?, ?)",
                           (operation_id, ticket["id"], arguments["body"]))
                result = {"status": "drafted", "operation_id": operation_id}
            elif tool == "send_reply":
                db.execute("INSERT INTO outbox VALUES (?, ?, ?, ?)",
                           (operation_id, ticket["id"], ticket["customer"], arguments["body"]))
                result = {"status": "queued_locally", "recipient": ticket["customer"], "operation_id": operation_id}
            else:
                refunded = db.execute("SELECT COALESCE(SUM(amount_cents), 0) FROM refunds WHERE ticket_id = ?",
                                      (ticket["id"],)).fetchone()[0]
                if refunded + arguments["amount_cents"] > ticket["paid_cents"]:
                    raise ValueError("Refund exceeds remaining paid amount")
                db.execute("INSERT INTO refunds VALUES (?, ?, ?, ?)",
                           (operation_id, ticket["id"], arguments["amount_cents"], arguments["reason"]))
                result = {"status": "recorded_locally", "amount_cents": arguments["amount_cents"],
                          "operation_id": operation_id}
            db.execute("INSERT INTO operations VALUES (?, ?, ?)",
                       (operation_id, fingerprint, json.dumps(result)))
            return result

    def counts(self):
        with self.connect() as db:
            return {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in ("tickets", "drafts", "outbox", "refunds")}
