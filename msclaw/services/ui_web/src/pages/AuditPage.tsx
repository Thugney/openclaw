import React, { useState, useEffect } from "react";
import { auditApi, type AuditEntry } from "../api/client";

const ACTION_COLORS: Record<string, string> = {
  "workflow.submitted": "#2196f3",
  "workflow.started": "#03a9f4",
  "workflow.completed": "#4caf50",
  "workflow.failed": "#f44336",
  "tool.intent_created": "#9c27b0",
  "tool.policy_checked": "#ff9800",
  "tool.policy_denied": "#f44336",
  "tool.approval_requested": "#ff5722",
  "tool.approved": "#4caf50",
  "tool.denied": "#f44336",
  "tool.executed": "#4caf50",
  "tool.failed": "#f44336",
  "model.invoked": "#607d8b",
};

export function AuditPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [correlationFilter, setCorrelationFilter] = useState("");
  const [workflowFilter, setWorkflowFilter] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const loadEntries = async () => {
    setLoading(true);
    try {
      const data = await auditApi.list(
        correlationFilter || undefined,
        workflowFilter || undefined,
      );
      setEntries(data);
    } catch {
      // Error handling
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadEntries();
  }, []);

  return (
    <div>
      <h2 style={{ margin: "0 0 24px", fontSize: 24, fontWeight: 600 }}>Audit Trail</h2>

      {/* Filters */}
      <div style={{
        backgroundColor: "#fff",
        borderRadius: 8,
        padding: 16,
        marginBottom: 20,
        boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
        display: "flex",
        gap: 16,
        alignItems: "flex-end",
        flexWrap: "wrap",
      }}>
        <div>
          <label style={{ display: "block", fontSize: 12, marginBottom: 4, color: "#666" }}>
            Correlation ID
          </label>
          <input
            type="text"
            value={correlationFilter}
            onChange={(e) => setCorrelationFilter(e.target.value)}
            placeholder="corr-abc123"
            style={{ padding: "6px 10px", border: "1px solid #ddd", borderRadius: 4, fontSize: 13, width: 240 }}
          />
        </div>
        <div>
          <label style={{ display: "block", fontSize: 12, marginBottom: 4, color: "#666" }}>
            Workflow Run ID
          </label>
          <input
            type="text"
            value={workflowFilter}
            onChange={(e) => setWorkflowFilter(e.target.value)}
            placeholder="run-xyz789"
            style={{ padding: "6px 10px", border: "1px solid #ddd", borderRadius: 4, fontSize: 13, width: 240 }}
          />
        </div>
        <button
          onClick={loadEntries}
          disabled={loading}
          style={{
            padding: "6px 16px",
            backgroundColor: "#1a73e8",
            color: "#fff",
            border: "none",
            borderRadius: 4,
            cursor: "pointer",
            fontSize: 13,
          }}
        >
          {loading ? "Loading..." : "Search"}
        </button>
      </div>

      {/* Entries */}
      <div style={{
        backgroundColor: "#fff",
        borderRadius: 8,
        boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
        overflow: "hidden",
      }}>
        {entries.length === 0 ? (
          <div style={{ padding: 40, textAlign: "center", color: "#999", fontSize: 14 }}>
            No audit entries found
          </div>
        ) : (
          entries.map((entry) => (
            <div
              key={entry.entry_id}
              style={{ borderBottom: "1px solid #f0f0f0" }}
            >
              <div
                onClick={() => setExpandedId(expandedId === entry.entry_id ? null : entry.entry_id)}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 12,
                  padding: "12px 16px",
                  cursor: "pointer",
                  fontSize: 13,
                }}
              >
                <span style={{
                  display: "inline-block",
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  backgroundColor: ACTION_COLORS[entry.action] || "#999",
                  flexShrink: 0,
                }} />
                <span style={{ fontFamily: "monospace", fontSize: 11, color: "#888", width: 70, flexShrink: 0 }}>
                  {entry.correlation_id.slice(0, 8)}
                </span>
                <span style={{ fontWeight: 500, width: 200, flexShrink: 0 }}>{entry.action}</span>
                <span style={{ color: "#666", width: 120, flexShrink: 0 }}>{entry.actor}</span>
                <span style={{ color: "#666", flex: 1 }}>
                  {entry.plugin && `${entry.plugin}.${entry.tool_action || ""}`}
                  {entry.target && ` → ${entry.target}`}
                </span>
                <span style={{ color: "#aaa", fontSize: 11, flexShrink: 0 }}>
                  {new Date(entry.timestamp).toLocaleTimeString()}
                </span>
              </div>

              {expandedId === entry.entry_id && (
                <div style={{ padding: "0 16px 16px 36px", fontSize: 12 }}>
                  <div style={{
                    backgroundColor: "#f8f9fa",
                    borderRadius: 4,
                    padding: 12,
                    fontFamily: "monospace",
                    whiteSpace: "pre-wrap",
                    lineHeight: 1.6,
                  }}>
                    {`Entry ID:       ${entry.entry_id}
Correlation ID: ${entry.correlation_id}
Workflow Run:   ${entry.workflow_run_id || "-"}
Action:         ${entry.action}
Actor:          ${entry.actor}
Target:         ${entry.target || "-"}
Plugin:         ${entry.plugin || "-"}
Tool Action:    ${entry.tool_action || "-"}
Policy:         ${entry.policy_decision || "-"}
Model:          ${entry.model_used || "-"}
Hash:           ${entry.entry_hash || "-"}
Timestamp:      ${entry.timestamp}

Inputs:  ${entry.inputs ? JSON.stringify(entry.inputs, null, 2) : "-"}
Outputs: ${entry.outputs ? JSON.stringify(entry.outputs, null, 2) : "-"}
${entry.error ? `Error:   ${entry.error}` : ""}
${entry.approval_chain ? `Approval Chain: ${entry.approval_chain.join(" → ")}` : ""}`}
                  </div>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
