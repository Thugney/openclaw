import React, { useState, useEffect } from "react";
import { useParams, Link } from "react-router-dom";
import { workflowApi, auditApi, type WorkflowRun, type AuditEntry } from "../api/client";

const STATUS_COLORS: Record<string, string> = {
  pending: "#ff9800",
  running: "#2196f3",
  awaiting_approval: "#ff5722",
  completed: "#4caf50",
  failed: "#f44336",
  cancelled: "#9e9e9e",
};

export function WorkflowRunPage() {
  const { runId } = useParams<{ runId: string }>();
  const [run, setRun] = useState<WorkflowRun | null>(null);
  const [auditEntries, setAuditEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadData = async () => {
    if (!runId) return;
    setLoading(true);
    try {
      const [runData, audit] = await Promise.all([
        workflowApi.getStatus(runId),
        auditApi.list(undefined, runId),
      ]);
      setRun(runData);
      setAuditEntries(audit);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [runId]);

  if (loading) return <div style={{ padding: 40, textAlign: "center", color: "#999" }}>Loading...</div>;
  if (error) return <div style={{ padding: 40, color: "#f44336" }}>Error: {error}</div>;
  if (!run) return <div style={{ padding: 40, color: "#999" }}>Run not found</div>;

  return (
    <div>
      <Link to="/workflows" style={{ fontSize: 13, color: "#1a73e8", textDecoration: "none", marginBottom: 16, display: "block" }}>
        &larr; Back to workflows
      </Link>

      <h2 style={{ margin: "0 0 8px", fontSize: 24, fontWeight: 600 }}>Workflow Run</h2>
      <p style={{ margin: "0 0 24px", fontSize: 13, color: "#888" }}>
        {run.workflow_id} | <code>{run.run_id}</code>
      </p>

      {/* Status card */}
      <div style={{
        backgroundColor: "#fff",
        borderRadius: 8,
        padding: 24,
        marginBottom: 24,
        boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
        gap: 20,
      }}>
        <div>
          <div style={{ fontSize: 12, color: "#888", marginBottom: 4 }}>Status</div>
          <span style={{
            display: "inline-block",
            padding: "4px 12px",
            borderRadius: 12,
            fontSize: 13,
            fontWeight: 600,
            color: "#fff",
            backgroundColor: STATUS_COLORS[run.status] || "#999",
          }}>
            {run.status}
          </span>
        </div>
        <div>
          <div style={{ fontSize: 12, color: "#888", marginBottom: 4 }}>Steps Completed</div>
          <div style={{ fontSize: 18, fontWeight: 600 }}>{run.steps_completed.length}</div>
        </div>
        <div>
          <div style={{ fontSize: 12, color: "#888", marginBottom: 4 }}>Artifacts</div>
          <div style={{ fontSize: 18, fontWeight: 600 }}>{run.artifacts.length}</div>
        </div>
        <div>
          <div style={{ fontSize: 12, color: "#888", marginBottom: 4 }}>Created</div>
          <div style={{ fontSize: 13 }}>{new Date(run.created_at).toLocaleString()}</div>
        </div>
      </div>

      {/* Error */}
      {run.error && (
        <div style={{
          backgroundColor: "#fde8e8",
          borderRadius: 8,
          padding: 16,
          marginBottom: 24,
          color: "#c62828",
          fontSize: 14,
        }}>
          <strong>Error:</strong> {run.error}
        </div>
      )}

      {/* Actions */}
      {run.status === "completed" && (
        <div style={{
          backgroundColor: "#fff",
          borderRadius: 8,
          padding: 20,
          marginBottom: 24,
          boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
        }}>
          <h3 style={{ margin: "0 0 12px", fontSize: 15, fontWeight: 600 }}>Actions</h3>
          <button
            style={{
              padding: "8px 16px",
              backgroundColor: "#ff9800",
              color: "#fff",
              border: "none",
              borderRadius: 4,
              cursor: "pointer",
              fontSize: 13,
              fontWeight: 500,
            }}
          >
            Unisolate Device (policy-gated)
          </button>
        </div>
      )}

      {/* Step results */}
      {Object.keys(run.step_results).length > 0 && (
        <div style={{
          backgroundColor: "#fff",
          borderRadius: 8,
          padding: 20,
          marginBottom: 24,
          boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
        }}>
          <h3 style={{ margin: "0 0 12px", fontSize: 15, fontWeight: 600 }}>Step Results</h3>
          <pre style={{
            backgroundColor: "#f5f5f5",
            padding: 12,
            borderRadius: 4,
            fontSize: 12,
            overflow: "auto",
          }}>
            {JSON.stringify(run.step_results, null, 2)}
          </pre>
        </div>
      )}

      {/* Audit trail */}
      <div style={{
        backgroundColor: "#fff",
        borderRadius: 8,
        padding: 20,
        boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
      }}>
        <h3 style={{ margin: "0 0 16px", fontSize: 15, fontWeight: 600 }}>
          Audit Trail ({auditEntries.length} entries)
        </h3>
        {auditEntries.length === 0 ? (
          <p style={{ color: "#999", fontSize: 13 }}>No audit entries yet</p>
        ) : (
          auditEntries.map((entry, i) => (
            <div
              key={entry.entry_id}
              style={{
                display: "flex",
                gap: 12,
                padding: "8px 0",
                borderBottom: i < auditEntries.length - 1 ? "1px solid #f0f0f0" : "none",
                fontSize: 12,
              }}
            >
              <span style={{ color: "#aaa", width: 70, flexShrink: 0 }}>
                {new Date(entry.timestamp).toLocaleTimeString()}
              </span>
              <span style={{ fontWeight: 500, width: 180 }}>{entry.action}</span>
              <span style={{ color: "#666", width: 100 }}>{entry.actor}</span>
              <span style={{ color: "#888", flex: 1 }}>
                {entry.plugin && `${entry.plugin}.${entry.tool_action}`}
                {entry.policy_decision && ` [${entry.policy_decision}]`}
                {entry.error && ` ERROR: ${entry.error}`}
              </span>
              <code style={{ color: "#aaa", fontSize: 10 }}>{entry.entry_hash?.slice(0, 8)}</code>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
