"""MSClaw CLI.

Thin client that talks to the control-api for:
- Submitting workflows
- Checking status
- Reviewing approvals
- Querying audit trail

Designed for pipeline integration and operator use.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import HTTPError


DEFAULT_API = "http://localhost:8100"


def _request(method: str, url: str, body: dict | None = None) -> dict[str, Any]:
    """Make an HTTP request to the control API."""
    data = json.dumps(body).encode() if body else None
    req = Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")

    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        error_body = json.loads(e.read().decode()) if e.fp else {}
        print(f"Error {e.code}: {error_body.get('detail', e.reason)}", file=sys.stderr)
        sys.exit(1)


def cmd_workflow_submit(args: argparse.Namespace) -> None:
    """Submit a workflow."""
    inputs = json.loads(args.inputs) if args.inputs else {}
    body = {
        "workflow_id": args.workflow_id,
        "inputs": inputs,
        "operator_id": args.operator or "cli-operator",
    }
    if args.idempotency_key:
        body["idempotency_key"] = args.idempotency_key

    result = _request("POST", f"{args.api}/api/v1/workflows", body)
    print(json.dumps(result, indent=2))


def cmd_workflow_status(args: argparse.Namespace) -> None:
    """Get workflow run status."""
    result = _request("GET", f"{args.api}/api/v1/workflows/{args.run_id}")
    print(json.dumps(result, indent=2))


def cmd_workflow_list(args: argparse.Namespace) -> None:
    """List workflow runs."""
    url = f"{args.api}/api/v1/workflows?limit={args.limit}"
    if args.status:
        url += f"&status={args.status}"
    result = _request("GET", url)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"{'Run ID':<40} {'Workflow':<35} {'Status':<20} {'Created'}")
        print("-" * 120)
        for run in result:
            print(f"{run['run_id'][:36]:<40} {run['workflow_id']:<35} {run['status']:<20} {run['created_at']}")


def cmd_approval_list(args: argparse.Namespace) -> None:
    """List pending approvals."""
    result = _request("GET", f"{args.api}/api/v1/approvals?status={args.status}")
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if not result:
            print(f"No {args.status} approvals")
            return
        print(f"{'Approval ID':<40} {'Action':<40} {'Reason':<40} {'Requested'}")
        print("-" * 140)
        for a in result:
            print(f"{a['approval_id'][:36]:<40} {a['plugin']}.{a['action']:<38} {a['reason'][:38]:<40} {a['requested_at']}")


def cmd_approval_decide(args: argparse.Namespace) -> None:
    """Approve or deny a request."""
    body = {
        "decision": args.decision,
        "decided_by": args.operator or "cli-operator",
    }
    if args.note:
        body["note"] = args.note

    result = _request("POST", f"{args.api}/api/v1/approvals/{args.approval_id}/decide", body)
    print(json.dumps(result, indent=2))


def cmd_audit_list(args: argparse.Namespace) -> None:
    """Query audit trail."""
    url = f"{args.api}/api/v1/audit?limit={args.limit}"
    if args.correlation_id:
        url += f"&correlation_id={args.correlation_id}"
    if args.workflow_run_id:
        url += f"&workflow_run_id={args.workflow_run_id}"

    result = _request("GET", url)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for entry in result:
            target = entry.get("target") or "-"
            plugin = f"{entry.get('plugin', '-')}.{entry.get('tool_action', '-')}"
            print(
                f"[{entry['correlation_id'][:8]}] "
                f"{entry['timestamp']} "
                f"{entry['action']:<30} "
                f"by {entry['actor']:<20} "
                f"{plugin:<30} "
                f"target={target}"
            )


def cmd_audit_chain(args: argparse.Namespace) -> None:
    """Get audit chain for a correlation ID."""
    result = _request("GET", f"{args.api}/api/v1/audit/chain/{args.correlation_id}")
    print(json.dumps(result, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="msclaw",
        description="MSClaw CLI - Microsoft Security Operations Agent Runtime",
    )
    parser.add_argument("--api", default=DEFAULT_API, help="Control API base URL")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--operator", help="Operator identity")

    subparsers = parser.add_subparsers(dest="command")

    # workflow submit
    ws = subparsers.add_parser("workflow-submit", help="Submit a workflow")
    ws.add_argument("workflow_id", help="Workflow ID")
    ws.add_argument("--inputs", help="JSON string of workflow inputs")
    ws.add_argument("--idempotency-key", help="Idempotency key")
    ws.set_defaults(func=cmd_workflow_submit)

    # workflow status
    wst = subparsers.add_parser("workflow-status", help="Get workflow run status")
    wst.add_argument("run_id", help="Workflow run ID")
    wst.set_defaults(func=cmd_workflow_status)

    # workflow list
    wl = subparsers.add_parser("workflow-list", help="List workflow runs")
    wl.add_argument("--limit", type=int, default=20)
    wl.add_argument("--status", help="Filter by status")
    wl.set_defaults(func=cmd_workflow_list)

    # approval list
    al = subparsers.add_parser("approval-list", help="List approvals")
    al.add_argument("--status", default="pending")
    al.set_defaults(func=cmd_approval_list)

    # approval decide
    ad = subparsers.add_parser("approval-decide", help="Approve or deny")
    ad.add_argument("approval_id", help="Approval ID")
    ad.add_argument("decision", choices=["approved", "denied"])
    ad.add_argument("--note", help="Decision note")
    ad.set_defaults(func=cmd_approval_decide)

    # audit list
    aul = subparsers.add_parser("audit-list", help="Query audit trail")
    aul.add_argument("--correlation-id", help="Filter by correlation ID")
    aul.add_argument("--workflow-run-id", help="Filter by workflow run ID")
    aul.add_argument("--limit", type=int, default=50)
    aul.set_defaults(func=cmd_audit_list)

    # audit chain
    auc = subparsers.add_parser("audit-chain", help="Get full audit chain")
    auc.add_argument("correlation_id", help="Correlation ID")
    auc.set_defaults(func=cmd_audit_chain)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()
