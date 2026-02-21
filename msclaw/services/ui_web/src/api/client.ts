/**
 * MSClaw API client for the React UI.
 */

const API_BASE = import.meta.env.VITE_API_URL || "http://localhost:8100";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `API error: ${response.status}`);
  }

  return response.json();
}

// Workflow API
export interface WorkflowSubmitRequest {
  workflow_id: string;
  inputs: Record<string, unknown>;
  idempotency_key?: string;
  operator_id?: string;
}

export interface WorkflowSubmitResponse {
  run_id: string;
  correlation_id: string;
  status: string;
  message: string;
}

export interface WorkflowRun {
  run_id: string;
  workflow_id: string;
  status: string;
  steps_completed: number[];
  step_results: Record<string, unknown>;
  artifacts: string[];
  created_at: string;
  updated_at: string;
  error: string | null;
}

export interface WorkflowListItem {
  run_id: string;
  workflow_id: string;
  status: string;
  created_at: string;
  operator_id: string;
}

export const workflowApi = {
  submit: (data: WorkflowSubmitRequest) =>
    request<WorkflowSubmitResponse>("/api/v1/workflows", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  getStatus: (runId: string) =>
    request<WorkflowRun>(`/api/v1/workflows/${runId}`),

  list: (limit = 50, status?: string) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (status) params.set("status", status);
    return request<WorkflowListItem[]>(`/api/v1/workflows?${params}`);
  },

  cancel: (runId: string) =>
    request<{ status: string }>(`/api/v1/workflows/${runId}/cancel`, { method: "POST" }),
};

// Approval API
export interface ApprovalItem {
  approval_id: string;
  workflow_run_id: string;
  step_index: number;
  plugin: string;
  action: string;
  reason: string;
  parameters: Record<string, unknown>;
  status: string;
  requested_at: string;
  decided_at: string | null;
  decided_by: string | null;
  decision_note: string | null;
}

export const approvalApi = {
  list: (status = "pending") =>
    request<ApprovalItem[]>(`/api/v1/approvals?status=${status}`),

  decide: (approvalId: string, decision: "approved" | "denied", decidedBy: string, note?: string) =>
    request<ApprovalItem>(`/api/v1/approvals/${approvalId}/decide`, {
      method: "POST",
      body: JSON.stringify({ decision, decided_by: decidedBy, note }),
    }),
};

// Audit API
export interface AuditEntry {
  entry_id: string;
  correlation_id: string;
  workflow_run_id: string | null;
  action: string;
  actor: string;
  target: string | null;
  plugin: string | null;
  tool_action: string | null;
  inputs: Record<string, unknown> | null;
  outputs: Record<string, unknown> | null;
  policy_decision: string | null;
  model_used: string | null;
  approval_chain: string[] | null;
  error: string | null;
  timestamp: string;
  entry_hash: string | null;
}

export const auditApi = {
  list: (correlationId?: string, workflowRunId?: string, limit = 100) => {
    const params = new URLSearchParams({ limit: String(limit) });
    if (correlationId) params.set("correlation_id", correlationId);
    if (workflowRunId) params.set("workflow_run_id", workflowRunId);
    return request<AuditEntry[]>(`/api/v1/audit?${params}`);
  },

  getChain: (correlationId: string) =>
    request<AuditEntry[]>(`/api/v1/audit/chain/${correlationId}`),
};
