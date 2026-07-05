import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { useProject } from "../project/ProjectContext";

const NAV = [
  { to: "/queues", label: "Queues" },
  { to: "/jobs", label: "Jobs" },
  { to: "/workers", label: "Workers" },
  { to: "/dlq", label: "Dead Letter" },
  { to: "/metrics", label: "Metrics" },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const { projects, selectedId, setSelectedId } = useProject();

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-56 flex-col border-r border-edge bg-panel">
        <div className="px-4 py-4">
          <div className="text-sm font-semibold text-slate-100">Job Scheduler</div>
          <div className="text-xs text-muted">Postgres-backed queue</div>
        </div>
        <nav className="flex-1 space-y-1 px-2">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `block rounded-md px-3 py-2 text-sm ${
                  isActive
                    ? "bg-edge text-white"
                    : "text-slate-300 hover:bg-edge/60"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-edge p-3 text-xs text-muted">
          <div className="truncate">{user?.email ?? "…"}</div>
          <button className="btn-ghost mt-2 w-full" onClick={logout}>
            Sign out
          </button>
        </div>
      </aside>

      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-edge bg-panel/60 px-6 py-3">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted">Project</span>
            <select
              className="input w-56 py-1"
              value={selectedId ?? ""}
              onChange={(e) => setSelectedId(Number(e.target.value))}
            >
              {projects.length === 0 && <option value="">No projects</option>}
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
        </header>
        <main className="flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
