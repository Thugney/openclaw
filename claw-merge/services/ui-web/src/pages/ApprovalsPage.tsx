import { useEffect, useState } from 'react'
import { listPendingApprovals, decideApproval, ApprovalRequest } from '../api/client'

export default function ApprovalsPage() {
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([])
  const [loading, setLoading] = useState(true)

  const refresh = () => {
    setLoading(true)
    listPendingApprovals()
      .then(setApprovals)
      .catch(console.error)
      .finally(() => setLoading(false))
  }

  useEffect(() => { refresh() }, [])

  const handleDecision = async (approvalId: string, action: 'approve' | 'reject') => {
    const reason = action === 'reject'
      ? prompt('Rejection reason:') || ''
      : ''
    try {
      await decideApproval(approvalId, action, reason)
      refresh()
    } catch (err) {
      console.error(err)
    }
  }

  return (
    <div>
      <div className="page-header">
        <h1>Approvals Queue</h1>
        <p>Pending approval requests for policy-gated actions</p>
      </div>

      <div style={{ marginBottom: 16 }}>
        <button className="btn" onClick={refresh}>Refresh</button>
      </div>

      {loading ? (
        <div className="empty-state">Loading...</div>
      ) : approvals.length === 0 ? (
        <div className="empty-state">No pending approvals</div>
      ) : (
        approvals.map(a => (
          <div key={a.approval_id} className="card">
            <div className="card-header">
              <div>
                <strong>{a.plugin}.{a.action}</strong>
                <span className="correlation-id" style={{ marginLeft: 12 }}>{a.correlation_id}</span>
              </div>
              <span className="badge badge-awaiting">{a.status}</span>
            </div>

            <table className="table" style={{ marginBottom: 12 }}>
              <tbody>
                <tr><td style={{ width: 160 }}><strong>Requested By</strong></td><td>{a.requested_by}</td></tr>
                <tr><td><strong>Requested At</strong></td><td>{new Date(a.requested_at).toLocaleString()}</td></tr>
                <tr><td><strong>Policy Reason</strong></td><td>{a.policy_reason}</td></tr>
                <tr><td><strong>Required Approvers</strong></td><td>{a.required_approvers.join(', ')}</td></tr>
                <tr><td><strong>Inputs</strong></td><td><pre className="mono">{JSON.stringify(a.inputs, null, 2)}</pre></td></tr>
              </tbody>
            </table>

            <div className="actions-row">
              <button className="btn btn-success btn-sm" onClick={() => handleDecision(a.approval_id, 'approve')}>
                Approve
              </button>
              <button className="btn btn-danger btn-sm" onClick={() => handleDecision(a.approval_id, 'reject')}>
                Reject
              </button>
            </div>
          </div>
        ))
      )}
    </div>
  )
}
