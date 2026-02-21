"""MSClaw CLI entrypoint."""

from __future__ import annotations

import json
import time
from typing import Optional

import httpx
import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(name="msclaw", help="MSClaw Security Operations CLI")
console = Console()

DEFAULT_API = "http://localhost:8000"


def _api_url() -> str:
    import os
    return os.getenv("MSCLAW_API_URL", DEFAULT_API)


def _headers(actor: str = "cli-user@contoso.com", roles: str = "security-lead") -> dict:
    return {
        "Content-Type": "application/json",
        "X-Actor": actor,
        "X-Roles": roles,
    }


# -- Workflows --

@app.command()
def run(
    workflow: str = typer.Argument(..., help="Workflow name"),
    device_id: Optional[str] = typer.Option(None, "--device-id", "-d"),
    incident_id: Optional[str] = typer.Option(None, "--incident-id", "-i"),
    device_tags: Optional[str] = typer.Option(None, "--tags", help="Comma-separated tags"),
    actor: str = typer.Option("cli-user@contoso.com", "--actor"),
    wait: bool = typer.Option(False, "--wait", "-w", help="Wait for completion"),
):
    """Submit a workflow for execution."""
    inputs: dict = {}
    if device_id:
        inputs["deviceId"] = device_id
    if incident_id:
        inputs["incidentId"] = incident_id
    if device_tags:
        inputs["device_tags"] = [t.strip() for t in device_tags.split(",")]
    inputs["actor_roles"] = ["security-lead"]

    idempotency_key = f"cli-{workflow}-{device_id or incident_id}-{int(time.time())}"

    with httpx.Client(base_url=_api_url(), timeout=30.0) as client:
        resp = client.post(
            "/api/v1/workflows",
            headers=_headers(actor),
            json={
                "workflow_name": workflow,
                "inputs": inputs,
                "idempotency_key": idempotency_key,
            },
        )
        resp.raise_for_status()
        result = resp.json()

    console.print(f"[bold green]Workflow submitted[/bold green]")
    console.print(f"  Run ID:         {result['run_id']}")
    console.print(f"  Correlation ID: {result['correlation_id']}")
    console.print(f"  Status:         {result['status']}")

    if wait and result["status"] not in ("completed", "failed", "idempotent_skip"):
        console.print("\nWaiting for completion...")
        _wait_for_completion(result["run_id"])


@app.command()
def status(run_id: str = typer.Argument(..., help="Workflow run ID")):
    """Check workflow run status."""
    with httpx.Client(base_url=_api_url(), timeout=10.0) as client:
        resp = client.get(f"/api/v1/workflows/{run_id}", headers=_headers())
        resp.raise_for_status()
        run = resp.json()

    console.print(f"[bold]Workflow: {run['workflow_name']}[/bold]")
    console.print(f"  Status:     {run['status']}")
    console.print(f"  Submitted:  {run['submitted_at']}")
    console.print(f"  Correlation: {run['correlation_id']}")
    if run.get("outputs"):
        console.print(f"  Outputs:    {json.dumps(run['outputs'], indent=2)}")
    if run.get("error"):
        console.print(f"  [red]Error: {run['error']}[/red]")


@app.command()
def workflows(
    limit: int = typer.Option(20, "--limit", "-n"),
    status_filter: Optional[str] = typer.Option(None, "--status"),
):
    """List workflow runs."""
    params: dict = {"limit": limit}
    if status_filter:
        params["status"] = status_filter

    with httpx.Client(base_url=_api_url(), timeout=10.0) as client:
        resp = client.get("/api/v1/workflows", headers=_headers(), params=params)
        resp.raise_for_status()
        runs = resp.json()

    table = Table(title="Workflow Runs")
    table.add_column("Run ID", style="cyan")
    table.add_column("Workflow")
    table.add_column("Status")
    table.add_column("Submitted By")
    table.add_column("Correlation ID", style="dim")

    for run in runs:
        table.add_row(
            run["run_id"][:16],
            run["workflow_name"],
            run["status"],
            run["submitted_by"],
            run["correlation_id"][:16],
        )

    console.print(table)


# -- Approvals --

@app.command()
def approvals():
    """List pending approvals."""
    with httpx.Client(base_url=_api_url(), timeout=10.0) as client:
        resp = client.get("/api/v1/approvals", headers=_headers())
        resp.raise_for_status()
        items = resp.json()

    if not items:
        console.print("[dim]No pending approvals[/dim]")
        return

    table = Table(title="Pending Approvals")
    table.add_column("Approval ID", style="cyan")
    table.add_column("Action")
    table.add_column("Requested By")
    table.add_column("Policy Reason")

    for a in items:
        table.add_row(
            a["approval_id"][:16],
            f"{a['plugin']}.{a['action']}",
            a["requested_by"],
            a["policy_reason"],
        )

    console.print(table)


@app.command()
def approve(
    approval_id: str = typer.Argument(..., help="Approval request ID"),
    reason: str = typer.Option("", "--reason", "-r"),
):
    """Approve a pending request."""
    with httpx.Client(base_url=_api_url(), timeout=10.0) as client:
        resp = client.post(
            f"/api/v1/approvals/{approval_id}/decide",
            headers=_headers(),
            json={"action": "approve", "reason": reason},
        )
        resp.raise_for_status()
    console.print(f"[green]Approved: {approval_id}[/green]")


@app.command()
def reject(
    approval_id: str = typer.Argument(..., help="Approval request ID"),
    reason: str = typer.Option("", "--reason", "-r"),
):
    """Reject a pending request."""
    with httpx.Client(base_url=_api_url(), timeout=10.0) as client:
        resp = client.post(
            f"/api/v1/approvals/{approval_id}/decide",
            headers=_headers(),
            json={"action": "reject", "reason": reason},
        )
        resp.raise_for_status()
    console.print(f"[red]Rejected: {approval_id}[/red]")


# -- Audit --

@app.command()
def audit(
    correlation_id: Optional[str] = typer.Option(None, "--correlation", "-c"),
    limit: int = typer.Option(20, "--limit", "-n"),
):
    """View audit trail."""
    with httpx.Client(base_url=_api_url(), timeout=10.0) as client:
        if correlation_id:
            resp = client.get(f"/api/v1/audit/correlation/{correlation_id}")
        else:
            resp = client.get(f"/api/v1/audit/entries?limit={limit}")
        resp.raise_for_status()
        entries = resp.json()

    table = Table(title="Audit Trail")
    table.add_column("Time")
    table.add_column("Action")
    table.add_column("Actor")
    table.add_column("Policy")
    table.add_column("Correlation", style="dim")

    for e in entries:
        table.add_row(
            e["timestamp"][:19],
            e["action"],
            e["actor"],
            e.get("policy_decision", "-"),
            e["correlation_id"][:16],
        )

    console.print(table)


# -- Tools --

@app.command()
def tools():
    """List registered tools."""
    with httpx.Client(base_url=_api_url().replace(":8000", ":8003"), timeout=10.0) as client:
        resp = client.get("/api/v1/tools")
        resp.raise_for_status()
        data = resp.json()

    table = Table(title="Registered Tools")
    table.add_column("Plugin")
    table.add_column("Action")
    table.add_column("Permissions")
    table.add_column("Approval")

    for t in data["tools"]:
        table.add_row(
            t["plugin"],
            t["action"],
            ", ".join(t["required_permissions"]),
            "Yes" if t["requires_approval"] else "-",
        )

    console.print(table)


def _wait_for_completion(run_id: str, timeout: int = 120, interval: int = 3) -> None:
    elapsed = 0
    with httpx.Client(base_url=_api_url(), timeout=10.0) as client:
        while elapsed < timeout:
            resp = client.get(f"/api/v1/workflows/{run_id}", headers=_headers())
            resp.raise_for_status()
            run = resp.json()
            s = run["status"]
            console.print(f"  [{elapsed}s] Status: {s}")
            if s in ("completed", "failed", "cancelled"):
                if s == "completed":
                    console.print("[bold green]Workflow completed successfully[/bold green]")
                else:
                    console.print(f"[bold red]Workflow {s}: {run.get('error', '')}[/bold red]")
                return
            if s == "awaiting_approval":
                console.print("[yellow]Workflow awaiting approval – check 'msclaw approvals'[/yellow]")
                return
            time.sleep(interval)
            elapsed += interval
    console.print("[yellow]Timed out waiting for completion[/yellow]")


if __name__ == "__main__":
    app()
