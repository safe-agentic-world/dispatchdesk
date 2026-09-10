"""Black-box customer tests: published CLI + public Python SDK only."""
import json
from contextlib import closing
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import warnings

from dispatchdesk.agent import run_agent
from dispatchdesk.gates import NomosGate
from dispatchdesk.store import Store
from test_core import Planner, call

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from gateway import configure


@unittest.skipUnless(os.environ.get("NOMOS_BINARY"), "Set NOMOS_BINARY to run real gateway integration tests")
class NomosTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cls.gateway_root = cls.root / "gateway"
        command = configure(cls.gateway_root, port, binary=os.environ["NOMOS_BINARY"], ttl=10)
        cls.log = (cls.root / "gateway.log").open("w")
        cls.addClassCleanup(cls.log.close)
        cls.process = subprocess.Popen(command, stdout=cls.log, stderr=cls.log)
        cls.addClassCleanup(cls.stop_gateway)
        for _ in range(100):
            if cls.process.poll() is not None:
                raise RuntimeError("Gateway exited before readiness")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=0.2):
                    break
            except (OSError, urllib.error.URLError):
                time.sleep(0.05)
        else:
            raise RuntimeError("Gateway readiness timeout")
        cls.config = json.loads((cls.gateway_root / "agent.json").read_text())
        cls.reviewer = NomosGate(json.loads((cls.gateway_root / "reviewer.json").read_text())).client

    @classmethod
    def stop_gateway(cls):
        if cls.process.poll() is None:
            cls.process.terminate()
            try:
                cls.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cls.process.kill()
                cls.process.wait(timeout=5)

    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(dir=self.root))
        self.store = Store(self.directory / "support.db")
        self.store.seed()
        self.gate = NomosGate(self.config)
        self.args = {"ticket_id": "T100", "body": "We can replace the damaged mug."}
        self.operation = self.directory.name

    def pending(self):
        result = self.gate.dispatch(self.store, "send_reply", self.args, self.operation)
        self.assertEqual(result["status"], "REQUIRE_APPROVAL")
        self.assertEqual(self.store.counts()["outbox"], 0)
        return result["pending"]

    def test_policy_suite(self):
        root = Path(__file__).resolve().parents[1]
        subprocess.run([os.environ["NOMOS_BINARY"], "test", "--suite", str(root / "policies/permissions.json"),
                        "--bundle", str(root / "policies/support.yaml")], check=True, capture_output=True)

    def test_real_draft_and_cross_tenant_denial(self):
        result = self.gate.dispatch(self.store, "draft_reply", self.args, self.operation)
        self.assertTrue(result["executed"])
        denied = self.gate.dispatch(self.store, "send_reply", {**self.args, "ticket_id": "T200"}, "other")
        self.assertEqual(denied["status"], "DENY")
        self.assertEqual(self.store.counts()["outbox"], 0)

    def test_approved_send_and_replay_have_one_side_effect(self):
        pending = self.pending()
        self.reviewer.decide_approval(pending["approval_id"], "APPROVE")
        for _ in range(2):
            result = self.gate.dispatch(self.store, "send_reply", self.args, self.operation, pending)
            self.assertTrue(result["executed"])
        self.assertEqual(self.store.counts()["outbox"], 1)
        with closing(sqlite3.connect(self.gateway_root / "audit.db")) as db:
            count = db.execute("SELECT COUNT(*) FROM audit_events WHERE event_type='action.external_reported' AND action_id=?",
                               (self.operation,)).fetchone()[0]
        self.assertGreaterEqual(count, 1)

    def test_rejection_and_agent_cannot_self_approve(self):
        pending = self.pending()
        try:
            self.gate.client.decide_approval(pending["approval_id"], "APPROVE")
        except urllib.error.HTTPError as error:
            self.assertEqual(error.code, 403)
            error.close()
        except ConnectionResetError:
            if os.name != "nt" or os.environ.get("STRICT_NOMOS_HTTP") == "1":
                raise
            warnings.warn("Nomos v0.13.3 Windows rejection reset the connection instead of returning HTTP 403; "
                          "set STRICT_NOMOS_HTTP=1 to fail on this known protocol issue", RuntimeWarning)
        else:
            self.fail("Agent identity was able to approve its own action")
        still_pending = self.gate.dispatch(self.store, "send_reply", self.args, self.operation, pending)
        self.assertFalse(still_pending["executed"], "Unauthorized approval attempt granted execution")
        self.assertEqual(self.store.counts()["outbox"], 0)
        self.reviewer.decide_approval(pending["approval_id"], "DENY")
        result = self.gate.dispatch(self.store, "send_reply", self.args, self.operation, pending)
        self.assertFalse(result["executed"])
        self.assertEqual(self.store.counts()["outbox"], 0)

    def test_approval_expiry_prevents_side_effect(self):
        pending = self.pending()
        self.reviewer.decide_approval(pending["approval_id"], "APPROVE")
        time.sleep(10.2)  # Public contract: wait for expiry, do not edit Nomos storage.
        result = self.gate.dispatch(self.store, "send_reply", self.args, self.operation, pending)
        self.assertFalse(result["executed"])
        self.assertEqual(self.store.counts()["outbox"], 0)

    def test_payload_changed_after_review_does_not_execute(self):
        pending = self.pending()
        self.reviewer.decide_approval(pending["approval_id"], "APPROVE")
        changed = {**self.args, "body": "This was not reviewed"}
        pending["request"]["params"]["body"] = changed["body"]
        result = self.gate.dispatch(self.store, "send_reply", changed, self.operation, pending)
        self.assertFalse(result["executed"])
        self.assertEqual(self.store.counts()["outbox"], 0)

    def test_recipient_changed_in_storage_invalidates_pending_send(self):
        pending = self.pending()
        self.reviewer.decide_approval(pending["approval_id"], "APPROVE")
        with self.store.connect() as db:
            db.execute("UPDATE tickets SET customer = ? WHERE id = ?", ("changed@example.test", "T100"))
        with self.assertRaises(ValueError):
            self.gate.dispatch(self.store, "send_reply", self.args, self.operation, pending)
        self.assertEqual(self.store.counts()["outbox"], 0)

    def test_agent_pause_restart_review_and_resume(self):
        path = self.directory / "session.json"
        state = run_agent(self.store, Planner(call("send_reply", **self.args)), self.gate, "Send reply", path)
        self.assertEqual(state["status"], "waiting_for_review")
        state = run_agent(self.store, Planner(), self.gate, "Send reply", path, resume=True)
        self.assertEqual(state["status"], "waiting_for_review")
        self.assertEqual(self.store.counts()["outbox"], 0)
        approval = state["pending"]["authorization"]["approval_id"]
        self.reviewer.decide_approval(approval, "APPROVE")
        state = run_agent(Store(self.store.path), Planner(call("finish")), NomosGate(self.config),
                          "Send reply", path, resume=True)
        self.assertEqual(state["status"], "finished")
        self.assertEqual(self.store.counts()["outbox"], 1)

    def test_gateway_unavailable_never_falls_back_to_allow(self):
        # Reserve a port without listening so no unrelated service can answer it.
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            gate = NomosGate({**self.config, "base_url": f"http://127.0.0.1:{sock.getsockname()[1]}", "timeout": 0.2})
            with self.assertRaises(urllib.error.URLError):
                gate.dispatch(self.store, "draft_reply", self.args, self.operation)
        self.assertEqual(self.store.counts()["drafts"], 0)

    def test_refund_review_and_business_limit(self):
        args = {"ticket_id": "T100", "amount_cents": 1000, "reason": "damaged mug"}
        result = self.gate.dispatch(self.store, "refund_order", args, self.operation)
        self.assertEqual(result["status"], "REQUIRE_APPROVAL")
        self.assertEqual(self.store.counts()["refunds"], 0)
        self.reviewer.decide_approval(result["pending"]["approval_id"], "APPROVE")
        result = self.gate.dispatch(self.store, "refund_order", args, self.operation, result["pending"])
        self.assertTrue(result["executed"])
        self.assertEqual(self.store.counts()["refunds"], 1)


if __name__ == "__main__":
    unittest.main()
