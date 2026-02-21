import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listWorkflows, WorkflowRun } from '../api/client'

function statusBadge(status: string) {
  const map: Record<string, string> = {
    pending: 'badge-pending',
    running: 'badge-running',
    completed: 'badge-completed',
    failed: 'badge-failed',
    awaiting_approval: 'badge-awaiting',
    cancelled: 'badge-failed',
  }
  return <span className={`badge ${map[status] || 'badge-pending'}`}>{status}</span>
}

export default function WorkflowsPage() {
  const [runs, setRuns] = useState<WorkflowRun[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    listWorkflows()
      .then(setRuns)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  return (
    <div>
      <div className="page-header">
        <h1>Workflow Runs</h1>
        <p>All submitted workflow executions</p>
      </div>

      {loading ? (
        <div className="empty-state">Loading...</div>
      ) : runs.length === 0 ? (
        <div className="empty-state">
          <p>No workflow runs yet.</p>
          <Link to="/" className="btn btn-primary" style={{ marginTop: 16, display: 'inline-block' }}>
            Run a Workflow
          </Link>
        </div>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Run ID</th>
              <th>Workflow</th>
              <th>Status</th>
              <th>Submitted By</th>
              <th>Submitted At</th>
              <th>Correlation ID</th>
            </tr>
          </thead>
          <tbody>
            {runs.map(run => (
              <tr key={run.run_id}>
                <td>
                  <Link to={`/workflows/${run.run_id}`} style={{ color: 'var(--accent-blue)' }}>
                    {run.run_id.slice(0, 12)}...
                  </Link>
                </td>
                <td>{run.workflow_name}</td>
                <td>{statusBadge(run.status)}</td>
                <td>{run.submitted_by}</td>
                <td>{new Date(run.submitted_at).toLocaleString()}</td>
                <td><span className="correlation-id">{run.correlation_id}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
