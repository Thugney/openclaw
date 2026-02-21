import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { workflowApi, type WorkflowListItem, type WorkflowSubmitResponse } from "../api/client";

const STATUS_COLORS: Record<string, string> = {
  pending: "#ff9800",
  running: "#2196f3",
  awaiting_approval: "#ff5722",
  completed: "#4caf50",
  failed: "#f44336",
  cancelled: "#9e9e9e",
};

export function WorkflowsPage() {
  const navigate = useNavigate();
  const [workflows, setWorkflows] = useState<WorkflowListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitResult, setSubmitResult] = useState<WorkflowSubmitResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Form state for "Contain device" workflow
  const [incidentId, setIncidentId] = useState("");
  const [deviceId, setDeviceId] = useState("");

  const loadWorkflows = async () => {
    setLoading(true);
    try {
      const data = await workflowApi.list();
      setWorkflows(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load workflows");
    } finally {
      setLoading(false);
    }
  };

  const submitContainDevice = async () => {
    setError(null);
    setSubmitResult(null);
    try {
      const inputs: Record<string, string> = {};
      if (incidentId) inputs.incidentId = incidentId;
      if (deviceId) inputs.deviceId = deviceId;

      if (!incidentId && !deviceId) {
        setError("Provide either an Incident ID or a Device ID");
        return;
      }

      const result = await workflowApi.submit({
        workflow_id: "contain-device-from-incident",
        inputs,
        operator_id: "operator@contoso.com",
      });
      setSubmitResult(result);
      loadWorkflows();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit workflow");
    }
  };

  React.useEffect(() => {
    loadWorkflows();
  }, []);

  return (
    <div>
      <h2 style={{ margin: "0 0 24px", fontSize: 24, fontWeight: 600 }}>Workflows</h2>

      {/* Submit workflow form */}
      <div style={{
        backgroundColor: "#fff",
        borderRadius: 8,
        padding: 24,
        marginBottom: 24,
        boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
      }}>
        <h3 style={{ margin: "0 0 16px", fontSize: 16, fontWeight: 600 }}>
          Run Workflow: Contain Device from Incident
        </h3>
        <div style={{ display: "flex", gap: 16, alignItems: "flex-end", flexWrap: "wrap" }}>
          <div>
            <label style={{ display: "block", fontSize: 13, marginBottom: 4, color: "#666" }}>
              Incident ID
            </label>
            <input
              type="text"
              value={incidentId}
              onChange={(e) => setIncidentId(e.target.value)}
              placeholder="INC-42"
              style={{
                padding: "8px 12px",
                border: "1px solid #ddd",
                borderRadius: 4,
                fontSize: 14,
                width: 200,
              }}
            />
          </div>
          <div style={{ color: "#999", fontSize: 13, paddingBottom: 8 }}>or</div>
          <div>
            <label style={{ display: "block", fontSize: 13, marginBottom: 4, color: "#666" }}>
              Device ID
            </label>
            <input
              type="text"
              value={deviceId}
              onChange={(e) => setDeviceId(e.target.value)}
              placeholder="device-001"
              style={{
                padding: "8px 12px",
                border: "1px solid #ddd",
                borderRadius: 4,
                fontSize: 14,
                width: 200,
              }}
            />
          </div>
          <button
            onClick={submitContainDevice}
            style={{
              padding: "8px 20px",
              backgroundColor: "#1a73e8",
              color: "#fff",
              border: "none",
              borderRadius: 4,
              fontSize: 14,
              fontWeight: 500,
              cursor: "pointer",
            }}
          >
            Submit Workflow
          </button>
        </div>

        {error && (
          <div style={{ marginTop: 12, color: "#f44336", fontSize: 13 }}>{error}</div>
        )}
        {submitResult && (
          <div style={{ marginTop: 12, padding: 12, backgroundColor: "#e8f5e9", borderRadius: 4, fontSize: 13 }}>
            Workflow submitted. Run ID:{" "}
            <code
              style={{ cursor: "pointer", textDecoration: "underline" }}
              onClick={() => navigate(`/workflows/${submitResult.run_id}`)}
            >
              {submitResult.run_id}
            </code>{" "}
            | Correlation: <code>{submitResult.correlation_id}</code>
          </div>
        )}
      </div>

      {/* Workflow list */}
      <div style={{
        backgroundColor: "#fff",
        borderRadius: 8,
        padding: 24,
        boxShadow: "0 1px 3px rgba(0,0,0,0.1)",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>Recent Runs</h3>
          <button
            onClick={loadWorkflows}
            disabled={loading}
            style={{
              padding: "6px 12px",
              border: "1px solid #ddd",
              borderRadius: 4,
              backgroundColor: "#fff",
              cursor: "pointer",
              fontSize: 13,
            }}
          >
            {loading ? "Loading..." : "Refresh"}
          </button>
        </div>

        {workflows.length === 0 ? (
          <p style={{ color: "#999", fontSize: 14 }}>No workflow runs yet. Submit one above.</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ borderBottom: "2px solid #eee" }}>
                <th style={{ textAlign: "left", padding: "8px 12px", color: "#666" }}>Run ID</th>
                <th style={{ textAlign: "left", padding: "8px 12px", color: "#666" }}>Workflow</th>
                <th style={{ textAlign: "left", padding: "8px 12px", color: "#666" }}>Status</th>
                <th style={{ textAlign: "left", padding: "8px 12px", color: "#666" }}>Operator</th>
                <th style={{ textAlign: "left", padding: "8px 12px", color: "#666" }}>Created</th>
              </tr>
            </thead>
            <tbody>
              {workflows.map((wf) => (
                <tr
                  key={wf.run_id}
                  style={{ borderBottom: "1px solid #f0f0f0", cursor: "pointer" }}
                  onClick={() => navigate(`/workflows/${wf.run_id}`)}
                >
                  <td style={{ padding: "10px 12px" }}>
                    <code style={{ fontSize: 12 }}>{wf.run_id.slice(0, 8)}...</code>
                  </td>
                  <td style={{ padding: "10px 12px" }}>{wf.workflow_id}</td>
                  <td style={{ padding: "10px 12px" }}>
                    <span style={{
                      display: "inline-block",
                      padding: "2px 8px",
                      borderRadius: 12,
                      fontSize: 11,
                      fontWeight: 600,
                      color: "#fff",
                      backgroundColor: STATUS_COLORS[wf.status] || "#999",
                    }}>
                      {wf.status}
                    </span>
                  </td>
                  <td style={{ padding: "10px 12px" }}>{wf.operator_id}</td>
                  <td style={{ padding: "10px 12px", color: "#888" }}>
                    {new Date(wf.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
