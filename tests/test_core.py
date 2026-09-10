import json
from pathlib import Path
import tempfile
import unittest

from dispatchdesk.agent import run_agent, strict_json
from dispatchdesk.gates import LocalGate, local_url
from dispatchdesk.store import Store, validate


class Planner:
    """Deterministic test double; never represented as a real model."""
    def __init__(self, *calls):
        self.calls = iter(calls)

    def next(self, messages):
        return next(self.calls)


def call(tool, **arguments):
    return {"tool": tool, "arguments": arguments}


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / "support.db")
        self.store.seed()

    def test_standalone_agent_observes_and_drafts(self):
        planner = Planner(call("read_ticket", ticket_id="T100"),
                          call("draft_reply", ticket_id="T100", body="Sorry about the damaged mug."), call("finish"))
        state = run_agent(self.store, planner, LocalGate(), "Draft a reply", self.root / "session.json")
        self.assertEqual(state["status"], "finished")
        self.assertEqual(self.store.counts(), {"tickets": 2, "drafts": 1, "outbox": 0, "refunds": 0})
        self.assertIn("Damaged mug", state["messages"][3]["content"])

    def test_standalone_refuses_writes_and_cross_tenant_access(self):
        gate = LocalGate()
        for tool, args in (("send_reply", {"ticket_id": "T100", "body": "Hi"}),
                           ("refund_order", {"ticket_id": "T100", "amount_cents": 100, "reason": "damage"}),
                           ("read_ticket", {"ticket_id": "T200"})):
            self.assertEqual(gate.dispatch(self.store, tool, args, "op")["status"], "DENY")
        self.assertEqual(self.store.counts()["outbox"], 0)
        self.assertEqual(self.store.counts()["refunds"], 0)

    def test_idempotency_survives_restart_and_rejects_payload_drift(self):
        args = {"ticket_id": "T100", "body": "Hello"}
        first = self.store.execute("send_reply", args, "op1")
        restarted = Store(self.store.path)
        self.assertEqual(first, restarted.execute("send_reply", args, "op1"))
        self.assertEqual(restarted.counts()["outbox"], 1)
        with self.assertRaises(ValueError):
            restarted.execute("send_reply", {**args, "body": "Changed"}, "op1")
        self.assertEqual(restarted.counts()["outbox"], 1)

    def test_refunds_cannot_exceed_original_payment(self):
        self.store.execute("refund_order", {"ticket_id": "T100", "amount_cents": 2000, "reason": "damage"}, "r1")
        with self.assertRaises(ValueError):
            self.store.execute("refund_order", {"ticket_id": "T100", "amount_cents": 600, "reason": "damage"}, "r2")
        self.assertEqual(self.store.counts()["refunds"], 1)

    def test_arguments_fail_closed(self):
        bad = [("shell", {}), ("send_reply", {"ticket_id": "T100"}),
               ("send_reply", {"ticket_id": "T100", "body": "x", "recipient": "attacker@example.test"}),
               ("refund_order", {"ticket_id": "T100", "amount_cents": True, "reason": "x"})]
        for tool, args in bad:
            with self.subTest(tool=tool, args=args), self.assertRaises(ValueError):
                validate(tool, args)

    def test_loop_is_bounded(self):
        planner = Planner(*(call("read_ticket", ticket_id="T100") for _ in range(3)))
        state = run_agent(self.store, planner, LocalGate(), "Read", self.root / "session.json", max_steps=2)
        self.assertEqual(state["status"], "step_limit")
        self.assertEqual(state["steps"], 2)

    def test_uncertain_failure_preserves_operation_for_resume(self):
        class FailAfterWrite(LocalGate):
            fail = True
            def dispatch(self, store, tool, args, operation_id, pending=None):
                result = super().dispatch(store, tool, args, operation_id, pending)
                if self.fail:
                    raise OSError("Simulated failure after commit")
                return result
        path = self.root / "session.json"
        proposal = call("draft_reply", ticket_id="T100", body="Hello")
        gate = FailAfterWrite()
        with self.assertRaises(OSError):
            run_agent(self.store, Planner(proposal), gate, "Draft", path)
        gate.fail = False
        state = run_agent(self.store, Planner(call("finish")), gate, "Draft", path, resume=True)
        self.assertEqual(state["status"], "finished")
        self.assertEqual(self.store.counts()["drafts"], 1)

    def test_resume_rejects_different_database_or_goal(self):
        path = self.root / "session.json"
        run_agent(self.store, Planner(call("finish")), LocalGate(), "Draft", path)
        with self.assertRaises(ValueError):
            run_agent(Store(self.root / "other.db"), Planner(), LocalGate(), "Draft", path, resume=True)
        with self.assertRaises(ValueError):
            run_agent(self.store, Planner(), LocalGate(), "Send", path, resume=True)

    def test_json_and_endpoint_validation(self):
        for text in ('{"a":1,"a":2}', '{"a":NaN}'):
            with self.assertRaises(ValueError):
                strict_json(text)
        for url in ("https://example.com", "http://127.0.0.1@evil.test", "http://localhost/redirect"):
            with self.assertRaises(ValueError):
                local_url(url)


if __name__ == "__main__":
    unittest.main()
