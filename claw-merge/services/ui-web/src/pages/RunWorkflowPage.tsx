import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { submitWorkflow } from '../api/client'

export default function RunWorkflowPage() {
  const navigate = useNavigate()
  const [incidentId, setIncidentId] = useState('')
  const [deviceId, setDeviceId] = useState('')
  const [deviceTags, setDeviceTags] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setSubmitting(true)

    const inputs: Record<string, unknown> = {}
    if (incidentId) inputs.incidentId = incidentId
    if (deviceId) inputs.deviceId = deviceId
    if (deviceTags) inputs.device_tags = deviceTags.split(',').map(t => t.trim())
    inputs.actor_roles = ['security-lead']

    const idempotencyKey = `contain-${deviceId || incidentId}-${Date.now()}`

    try {
      const result = await submitWorkflow(
        'contain_device_from_incident',
        inputs,
        idempotencyKey,
      )
      navigate(`/workflows/${result.run_id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div>
      <div className="page-header">
        <h1>Run Workflow</h1>
        <p>Submit a security workflow for execution</p>
      </div>

      <div className="card" style={{ maxWidth: 600 }}>
        <div className="card-header">
          <h3>Contain Device from Incident</h3>
          <span className="badge badge-running">MVP Workflow</span>
        </div>
        <p style={{ color: 'var(--text-secondary)', fontSize: 14, marginBottom: 16 }}>
          Isolate a device and collect investigation package. Provide either an incident ID
          or a device ID. VIP-tagged devices require approval.
        </p>

        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Incident ID (optional if Device ID provided)</label>
            <input
              type="text"
              value={incidentId}
              onChange={e => setIncidentId(e.target.value)}
              placeholder="e.g. INC-2024-001"
            />
          </div>

          <div className="form-group">
            <label>Device ID (optional if Incident ID provided)</label>
            <input
              type="text"
              value={deviceId}
              onChange={e => setDeviceId(e.target.value)}
              placeholder="e.g. abc123-device-id"
            />
          </div>

          <div className="form-group">
            <label>Device Tags (comma-separated, add "VIP" to require approval)</label>
            <input
              type="text"
              value={deviceTags}
              onChange={e => setDeviceTags(e.target.value)}
              placeholder="e.g. VIP, Windows, HP"
            />
          </div>

          {error && (
            <div style={{ color: 'var(--accent-red)', marginBottom: 16, fontSize: 14 }}>
              {error}
            </div>
          )}

          <button
            type="submit"
            className="btn btn-primary"
            disabled={submitting || (!incidentId && !deviceId)}
          >
            {submitting ? 'Submitting...' : 'Submit Workflow'}
          </button>
        </form>
      </div>
    </div>
  )
}
