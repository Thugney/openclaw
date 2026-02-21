import React, { useState, useEffect } from "react";
import { approvalApi, type ApprovalItem } from "../api/client";

export function ApprovalsPage() {
  const [approvals, setApprovals] = useState<ApprovalItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState<"pending" | "approved" | "denied">("pending");
  const [decidingId, setDecidingId] = useState<string | null>(null);
  const [decisionNote, setDecisionNote] = useState("");

  const loadApprovals = async () => {
    setLoading(true);
    try {
      const data = await approvalApi.list(filter);
      setApprovals(data);
    } catch {
      // Error handling
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadApprovals();
  }, [filter]);

  const handleDecision = async (approvalId: string, decision: "approved" | "denied") => {
    try {
      await approvalApi.decide(approvalId, decision, "operator@contoso.com", decisionNote || undefined);
      setDecidingId(null);
      setDecisionNote("");
      loadApprovals();
    } catch {
      // Error handling
    }
  };

  return (
    <div>
      <h2 style={{ margin: "0 0 24px", fontSize: 24, fontWeight: 600 }}>Approval Queue</h2>

      {/* Filter tabs */}
      <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
        {(["pending", "approved", "denied"] as const).map((status) => (
          <button
            key={status}
            onClick={() => setFilter(status)}
            style={{
              padding: "8px 16px",
              border: filter === status ? "2px solid #1a73e8" : "1px solid #ddd",
              borderRadius: 4,
              backgroundColor: filter === status ? "#e3f2fd" : "#fff",
              color: filter === status ? "#1a73e8" : "#666",
              cursor: "pointer",
              fontSize: 13,
              fontWeight: filter === status ? 600 : 400,
            }}
          >
            {status.charAt(0).toUpperCase() + status.slice(1)}
          </button>
        ))}
        <button
          onClick={loadApprovals}
          disabled={loading}
          style={{
            marginLeft: "auto",
            padding: "8px 12px",
            border: "1px solid #ddd",
            borderRadius: 4,
            backgroundColor: "#fff",
            cursor: "pointer",
            fontSize: 13,
          }}
        >
          {loading ? "..." : "Refresh"}
        </button>
      </div>

      {/* Approval cards */}
      {approvals.length === 0 ? (
        <div style={{
          backgroundColor: "#fff",
          borderRadius: 8,
          padding: 40,
          textAlign: "center",
          color: "#999",
          boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
        }}>
          No {filter} approvals
        </div>
      ) : (
        approvals.map((approval) => (
          <div
            key={approval.approval_id}
            style={{
              backgroundColor: "#fff",
              borderRadius: 8,
              padding: 20,
              marginBottom: 16,
              boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
              borderLeft: `4px solid ${approval.status === "pending" ? "#ff5722" : approval.status === "approved" ? "#4caf50" : "#f44336"}`,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
              <div>
                <span style={{ fontWeight: 600, fontSize: 15 }}>
                  {approval.plugin}.{approval.action}
                </span>
                <span style={{ color: "#999", fontSize: 12, marginLeft: 12 }}>
                  ID: {approval.approval_id.slice(0, 8)}
                </span>
              </div>
              <span style={{ fontSize: 12, color: "#888" }}>
                {new Date(approval.requested_at).toLocaleString()}
              </span>
            </div>

            <p style={{ margin: "0 0 12px", color: "#333", fontSize: 14 }}>{approval.reason}</p>

            <div style={{ fontSize: 12, color: "#666", marginBottom: 12 }}>
              <strong>Parameters:</strong>{" "}
              <code style={{ backgroundColor: "#f5f5f5", padding: "2px 6px", borderRadius: 3 }}>
                {JSON.stringify(approval.parameters)}
              </code>
            </div>

            <div style={{ fontSize: 12, color: "#666", marginBottom: 12 }}>
              <strong>Workflow Run:</strong> <code>{approval.workflow_run_id.slice(0, 8)}...</code>
              {" | "}
              <strong>Step:</strong> {approval.step_index}
            </div>

            {approval.status === "pending" && (
              <div>
                {decidingId === approval.approval_id ? (
                  <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
                    <input
                      type="text"
                      placeholder="Decision note (optional)"
                      value={decisionNote}
                      onChange={(e) => setDecisionNote(e.target.value)}
                      style={{
                        padding: "6px 10px",
                        border: "1px solid #ddd",
                        borderRadius: 4,
                        fontSize: 13,
                        width: 250,
                      }}
                    />
                    <button
                      onClick={() => handleDecision(approval.approval_id, "approved")}
                      style={{
                        padding: "6px 16px",
                        backgroundColor: "#4caf50",
                        color: "#fff",
                        border: "none",
                        borderRadius: 4,
                        cursor: "pointer",
                        fontSize: 13,
                        fontWeight: 500,
                      }}
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => handleDecision(approval.approval_id, "denied")}
                      style={{
                        padding: "6px 16px",
                        backgroundColor: "#f44336",
                        color: "#fff",
                        border: "none",
                        borderRadius: 4,
                        cursor: "pointer",
                        fontSize: 13,
                        fontWeight: 500,
                      }}
                    >
                      Deny
                    </button>
                    <button
                      onClick={() => { setDecidingId(null); setDecisionNote(""); }}
                      style={{
                        padding: "6px 12px",
                        border: "1px solid #ddd",
                        borderRadius: 4,
                        backgroundColor: "#fff",
                        cursor: "pointer",
                        fontSize: 13,
                      }}
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setDecidingId(approval.approval_id)}
                    style={{
                      padding: "6px 16px",
                      backgroundColor: "#ff5722",
                      color: "#fff",
                      border: "none",
                      borderRadius: 4,
                      cursor: "pointer",
                      fontSize: 13,
                      fontWeight: 500,
                    }}
                  >
                    Review & Decide
                  </button>
                )}
              </div>
            )}

            {approval.decided_by && (
              <div style={{ fontSize: 12, color: "#888", marginTop: 8 }}>
                Decided by {approval.decided_by} at {approval.decided_at}
                {approval.decision_note && ` - "${approval.decision_note}"`}
              </div>
            )}
          </div>
        ))
      )}
    </div>
  );
}
