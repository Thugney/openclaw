import { Routes, Route, NavLink } from 'react-router-dom'
import WorkflowsPage from './pages/WorkflowsPage'
import ApprovalsPage from './pages/ApprovalsPage'
import AuditPage from './pages/AuditPage'
import RunWorkflowPage from './pages/RunWorkflowPage'
import WorkflowDetailPage from './pages/WorkflowDetailPage'
import ToolsPage from './pages/ToolsPage'

export default function App() {
  return (
    <div className="app-layout">
      <nav className="sidebar">
        <div className="sidebar-logo">MSClaw</div>
        <div className="sidebar-nav">
          <NavLink to="/" end>Run Workflow</NavLink>
          <NavLink to="/workflows">Workflows</NavLink>
          <NavLink to="/approvals">Approvals</NavLink>
          <NavLink to="/audit">Audit Trail</NavLink>
          <NavLink to="/tools">Tools</NavLink>
        </div>
      </nav>
      <main className="main-content">
        <Routes>
          <Route path="/" element={<RunWorkflowPage />} />
          <Route path="/workflows" element={<WorkflowsPage />} />
          <Route path="/workflows/:runId" element={<WorkflowDetailPage />} />
          <Route path="/approvals" element={<ApprovalsPage />} />
          <Route path="/audit" element={<AuditPage />} />
          <Route path="/tools" element={<ToolsPage />} />
        </Routes>
      </main>
    </div>
  )
}
