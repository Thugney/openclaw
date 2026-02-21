import { useEffect, useState } from 'react'
import { listAuditEntries, AuditEntry } from '../api/client'

export default function AuditPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    listAuditEntries()
      .then(setEntries)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  return (
    <div>
      <div className="page-header">
        <h1>Audit Trail</h1>
        <p>Complete audit ledger with tamper-evident hash chain</p>
      </div>

      {loading ? (
        <div className="empty-state">Loading...</div>
      ) : entries.length === 0 ? (
        <div className="empty-state">No audit entries yet</div>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Timestamp</th>
              <th>Action</th>
              <th>Actor</th>
              <th>Service</th>
              <th>Policy</th>
              <th>Correlation ID</th>
              <th>Hash</th>
            </tr>
          </thead>
          <tbody>
            {entries.map(entry => (
              <tr key={entry.id}>
                <td>{new Date(entry.timestamp).toLocaleString()}</td>
                <td>{entry.action}</td>
                <td>{entry.actor}</td>
                <td>{entry.service}</td>
                <td>
                  {entry.policy_decision ? (
                    <span className={`badge ${
                      entry.policy_decision === 'allowed' ? 'badge-completed' :
                      entry.policy_decision === 'denied' ? 'badge-failed' :
                      'badge-awaiting'
                    }`}>
                      {entry.policy_decision}
                    </span>
                  ) : '-'}
                </td>
                <td><span className="correlation-id">{entry.correlation_id}</span></td>
                <td><span className="correlation-id">{entry.entry_hash?.slice(0, 12)}...</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
