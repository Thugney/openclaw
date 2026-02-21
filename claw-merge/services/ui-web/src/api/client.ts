/**
 * API client for MSClaw control-api and audit-service.
 */

const API_BASE = '/api/v1';
const AUDIT_BASE = '/api/v1/audit';

// Default actor for dev mode
const DEV_ACTOR = 'admin@contoso.com';
const DEV_ROLES = 'security-lead';

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Actor': DEV_ACTOR,
    'X-Roles': DEV_ROLES,
    ...(init?.headers as Record<string, string> ?? {}),
  };

  const resp = await fetch(url, { ...init, headers });
  if (!resp.ok) {
    const body = await resp.text();
    throw new Error(`HTTP ${resp.status}: ${body}`);
  }
  return resp.json();
}

// -- Workflows --

export interface WorkflowRun {
  run_id: string;
  correlation_id: string;
  workflow_name: string;
  status: string;
  idempotency_key: string;
  submitted_by: string;
  submitted_at: string;
  started_at: string | null;
  completed_at: string | null;
  inputs: Record<string, unknown>;
  steps: unknown[];
  outputs: Record<string, unknown>;
  error: string | null;
  tags: Record<string, string>;
}

export interface WorkflowSubmitResponse {
  run_id: string;
  correlation_id: string;
  status: string;
  message: string;
}

export async function submitWorkflow(
  workflowName: string,
  inputs: Record<string, unknown>,
  idempotencyKey: string,
  tags: Record<string, string> = {},
): Promise<WorkflowSubmitResponse> {
  return fetchJSON(`${API_BASE}/workflows`, {
    method: 'POST',
    body: JSON.stringify({
      workflow_name: workflowName,
      inputs,
      idempotency_key: idempotencyKey,
      tags,
    }),
  });
}

export async function getWorkflow(runId: string): Promise<WorkflowRun> {
  return fetchJSON(`${API_BASE}/workflows/${runId}`);
}

export async function listWorkflows(
  offset = 0, limit = 50, status?: string
): Promise<WorkflowRun[]> {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  if (status) params.set('status', status);
  return fetchJSON(`${API_BASE}/workflows?${params}`);
}

// -- Approvals --

export interface ApprovalRequest {
  approval_id: string;
  correlation_id: string;
  workflow_run_id: string | null;
  step_id: string | null;
  intent_id: string;
  plugin: string;
  action: string;
  inputs: Record<string, unknown>;
  requested_by: string;
  requested_at: string;
  status: string;
  required_approvers: string[];
  policy_reason: string;
  decided_by: string | null;
  decided_at: string | null;
  decision_reason: string | null;
}

export async function listPendingApprovals(
  offset = 0, limit = 50
): Promise<ApprovalRequest[]> {
  return fetchJSON(`${API_BASE}/approvals?offset=${offset}&limit=${limit}`);
}

export async function decideApproval(
  approvalId: string,
  action: 'approve' | 'reject',
  reason = '',
): Promise<{ approval_id: string; status: string }> {
  return fetchJSON(`${API_BASE}/approvals/${approvalId}/decide`, {
    method: 'POST',
    body: JSON.stringify({ action, reason }),
  });
}

// -- Audit --

export interface AuditEntry {
  id: string;
  correlation_id: string;
  timestamp: string;
  actor: string;
  actor_type: string;
  action: string;
  service: string;
  inputs: Record<string, unknown>;
  outputs: Record<string, unknown>;
  model_id: string | null;
  tool_name: string | null;
  idempotency_key: string | null;
  policy_decision: string | null;
  policy_rule: string | null;
  policy_reason: string | null;
  previous_hash: string | null;
  entry_hash: string | null;
  error: string | null;
}

export async function listAuditEntries(
  offset = 0, limit = 50, action?: string
): Promise<AuditEntry[]> {
  const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
  if (action) params.set('action', action);
  return fetchJSON(`${AUDIT_BASE}/entries?${params}`);
}

export async function getAuditByCorrelation(correlationId: string): Promise<AuditEntry[]> {
  return fetchJSON(`${AUDIT_BASE}/correlation/${correlationId}`);
}

// -- Tools --

export interface ToolInfo {
  plugin: string;
  action: string;
  description: string;
  required_permissions: string[];
  idempotency_strategy: string;
  rollback_action: string | null;
  requires_approval: boolean;
}

export async function listTools(): Promise<{ tools: ToolInfo[] }> {
  return fetchJSON('/api/v1/tools');
}
