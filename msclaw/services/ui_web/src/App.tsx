import React from "react";
import { Link, Outlet, useLocation } from "react-router-dom";

export function App() {
  const location = useLocation();

  const navItems = [
    { path: "/workflows", label: "Workflows", icon: ">" },
    { path: "/approvals", label: "Approvals", icon: "!" },
    { path: "/audit", label: "Audit Trail", icon: "#" },
  ];

  return (
    <div style={{ display: "flex", minHeight: "100vh", fontFamily: "system-ui, -apple-system, sans-serif" }}>
      {/* Sidebar */}
      <nav style={{
        width: 240,
        backgroundColor: "#1a1a2e",
        color: "#e0e0e0",
        padding: "20px 0",
        display: "flex",
        flexDirection: "column",
      }}>
        <div style={{ padding: "0 20px", marginBottom: 32 }}>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: "#4fc3f7", margin: 0 }}>MSClaw</h1>
          <p style={{ fontSize: 12, color: "#888", margin: "4px 0 0" }}>Security Operations</p>
        </div>

        {navItems.map((item) => {
          const isActive = location.pathname.startsWith(item.path) ||
            (item.path === "/workflows" && location.pathname === "/");
          return (
            <Link
              key={item.path}
              to={item.path}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 12,
                padding: "12px 20px",
                color: isActive ? "#4fc3f7" : "#aaa",
                textDecoration: "none",
                backgroundColor: isActive ? "rgba(79, 195, 247, 0.1)" : "transparent",
                borderLeft: isActive ? "3px solid #4fc3f7" : "3px solid transparent",
                fontSize: 14,
                fontWeight: isActive ? 600 : 400,
              }}
            >
              <span style={{ fontFamily: "monospace", fontSize: 16 }}>{item.icon}</span>
              {item.label}
            </Link>
          );
        })}

        <div style={{ marginTop: "auto", padding: "20px", fontSize: 11, color: "#555" }}>
          MSClaw v0.1.0 (dev)
        </div>
      </nav>

      {/* Main content */}
      <main style={{ flex: 1, backgroundColor: "#f5f5f5", padding: 24 }}>
        <Outlet />
      </main>
    </div>
  );
}
