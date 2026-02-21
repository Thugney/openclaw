import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { getWorkflow, WorkflowRun, getAuditByCorrelation, AuditEntry, submitWorkflow } from '../api/client'

export default function WorkflowDetailPage() {
  const { runId } = useParams<{ runId: string }>()
  const navigate = useNavigate()
  const [run, setRun] = useState<WorkflowRun | null>(null)
  const [audit, setAudit] = useState<AuditEntry[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!runId) return
    Promise.all([
      getWorkflow(runId),
    ])
      .then(([wf]) => {
        setRun(wf)
        return getAuditByCorrelation(wf.correlation_id)
      })
      .then(setAudit)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [runId])

  const handleUnisolate = async () => {
    if (!run) return
    const deviceId = run.outputs?.deviceId as string || run.inputs?.deviceId as string
    if (!deviceId) return

    try {
      const result = await submitWorkflow(
        'contain_device_from_incident',
        { deviceId, action: 'unisolate' },
        `unisolate-${deviceId}-${Date.now()}`,
      )
      navigate(`/workflows/${result.run_id}`)
    } catch (err) {
      console.error(err)
    }
  }

  if (loading) return <div className="empty-state">Loading...</div>
  if (!run) return <div className="empty-state">Workflow run not found</div>

  return (
    <div>
      <div className="page-header">
        <h1>Workflow: {run.workflow_name}</h1>
        <p>
          Run ID: <span className="mono">{run.run_id}</span> |{' '}
          Correlation: <span className="correlation-id">{run.correlation_id}</span>
        </p>
      </div>

      <div className="card">
        <div className="card-header">
          <h3>Status</h3>
          <span className={`badge badge-${run.status === 'completed' ? 'completed' : run.status === 'failed' ? 'failed' : 'running'}`}>
            {run.status}
          </span>
        </div>

        <table className="table">
          <tbody>
            <tr><td style={{ width: 180 }}><strong>Submitted By</strong></td><td>{run.submitted_by}</td></tr>
            <tr><td><strong>Submitted At</strong></td><td>{new Date(run.submitted_at).toLocaleString()}</td></tr>
            <tr><td><strong>Idempotency Key</strong></td><td className="mono">{run.idempotency_key}</td></tr>
            <tr><td><strong>Inputs</strong></td><td><pre className="mono">{JSON.stringify(run.inputs, null, 2)}</pre></td></tr>
            {run.outputs && Object.keys(run.outputs).length > 0 && (
              <tr><td><strong>Outputs</strong></td><td><pre className="mono">{JSON.stringify(run.outputs, null, 2)}</pre></td></tr>
            )}
            {run.error && (
              <tr><td><strong>Error</strong></td><td style={{ color: 'var(--accent-red)' }}>{run.error}</td></tr>
            )}
          </tbody>
        </table>

        {run.status === 'completed' && (run.outputs?.isolated as boolean) && (
          <div style={{ marginTop: 16 }}>
            <button className="btn btn-danger" onClick={handleUnisolate}>
              Unisolate Device
            </button>
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-header">
          <h3>Audit Trail</h3>
          <span className="badge badge-pending">{audit.length} entries</span>
        </div>

        {audit.length === 0 ? (
          <div className="empty-state">No audit entries for this correlation ID</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Action</th>
                <th>Actor</th>
                <th>Policy</th>
                <th>Hash</th>
              </tr>
            </thead>
            <tbody>
              {audit.map(entry => (
                <tr key={entry.id}>
                  <td>{new Date(entry.timestamp).toLocaleString()}</td>
                  <td>{entry.action}</td>
                  <td>{entry.actor}</td>
                  <td>
                    <span className={`badge ${entry.policy_decision === 'allowed' ? 'badge-completed' : entry.policy_decision === 'denied' ? 'badge-failed' : 'badge-awaiting'}`}>
                      {entry.policy_decision || 'n/a'}
                    </span>
                  </td>
                  <td><span className="correlation-id">{entry.entry_hash?.slice(0, 12)}...</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
