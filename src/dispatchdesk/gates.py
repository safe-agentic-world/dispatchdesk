"""Optional policy adapter. Business tools import neither Nomos nor an LLM SDK."""
import json
from urllib.parse import urlsplit

from .store import validate


def local_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"}):
        raise ValueError("Only a loopback HTTP endpoint is supported")
    return url.rstrip("/")


class LocalGate:
    """Standalone mode allows drafts/reads only. Writes never silently bypass review."""
    def dispatch(self, store, tool, arguments, operation_id, pending=None):
        validate(tool, arguments)
        resource = store.resource(arguments["ticket_id"])
        if not resource.startswith("support://acme/") or tool not in {"read_ticket", "draft_reply"}:
            return {"status": "DENY", "reason": "Standalone mode permits acme reads and drafts only"}
        return {"status": "ALLOW", "value": store.execute(tool, arguments, operation_id)}


class NomosGate:
    def __init__(self, config):
        from nomos_sdk import NomosClient
        config = dict(config)
        config["base_url"] = local_url(config["base_url"])
        self.client = NomosClient(**config)

    def dispatch(self, store, tool, arguments, operation_id, pending=None):
        from nomos_sdk import ActionRequest, CustomTool
        validate(tool, arguments)
        custom = CustomTool(
            client=self.client, action_type="support." + tool,
            resource=lambda params: store.resource(params["ticket_id"]),
            execute=lambda params: store.execute(tool, {k: v for k, v in params.items()
                                                        if k not in {"operation_id", "recipient"}},
                                                params["operation_id"], expected_recipient=params.get("recipient")),
        )
        params = {**arguments, "operation_id": operation_id}
        if tool == "send_reply":
            params["recipient"] = store.ticket(arguments["ticket_id"])["customer"]
        request = custom.prepare(params, action_id=operation_id, trace_id=operation_id)
        approval_id = None
        if pending:
            request = ActionRequest(**pending["request"])
            if request.params != params:
                raise ValueError("Pending arguments changed")
            approval_id = pending["approval_id"]
        result = custom.run(request, approval_id=approval_id)
        output = {"status": result.decision_response["decision"], "executed": result.executed}
        if result.executed:
            output["value"] = result.value
        elif output["status"] == "REQUIRE_APPROVAL":
            output["pending"] = {"request": request.as_dict(),
                                 "approval_id": result.decision_response["approval_id"]}
        return output


def load_gate(config_path):
    if config_path is None:
        return LocalGate()
    with open(config_path, encoding="utf-8") as handle:
        return NomosGate(json.load(handle))
