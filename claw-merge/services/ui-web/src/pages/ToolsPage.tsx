import { useEffect, useState } from 'react'
import { listTools, ToolInfo } from '../api/client'

export default function ToolsPage() {
  const [tools, setTools] = useState<ToolInfo[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    listTools()
      .then(data => setTools(data.tools))
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  return (
    <div>
      <div className="page-header">
        <h1>Registered Tools</h1>
        <p>All allowlisted plugin actions available for execution</p>
      </div>

      {loading ? (
        <div className="empty-state">Loading...</div>
      ) : (
        <table className="table">
          <thead>
            <tr>
              <th>Plugin</th>
              <th>Action</th>
              <th>Description</th>
              <th>Permissions</th>
              <th>Idempotency</th>
              <th>Approval</th>
              <th>Rollback</th>
            </tr>
          </thead>
          <tbody>
            {tools.map(tool => (
              <tr key={`${tool.plugin}.${tool.action}`}>
                <td><span className="badge badge-running">{tool.plugin}</span></td>
                <td>{tool.action}</td>
                <td style={{ fontSize: 13, color: 'var(--text-secondary)' }}>{tool.description}</td>
                <td className="mono" style={{ fontSize: 11 }}>
                  {tool.required_permissions.join(', ')}
                </td>
                <td>{tool.idempotency_strategy}</td>
                <td>{tool.requires_approval ? <span className="badge badge-awaiting">required</span> : '-'}</td>
                <td>{tool.rollback_action || '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
