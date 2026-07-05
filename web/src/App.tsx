import { useEffect } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { ProjectProvider } from "./project/ProjectContext";
import Layout from "./components/Layout";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import QueuesPage from "./pages/QueuesPage";
import JobsPage from "./pages/JobsPage";
import WorkersPage from "./pages/WorkersPage";
import DlqPage from "./pages/DlqPage";
import MetricsPage from "./pages/MetricsPage";

function Protected({ children }: { children: JSX.Element }) {
  const { token, loadMe } = useAuth();
  useEffect(() => {
    if (token) void loadMe();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  if (!token) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route
        path="/"
        element={
          <Protected>
            <ProjectProvider>
              <Layout />
            </ProjectProvider>
          </Protected>
        }
      >
        <Route index element={<Navigate to="/queues" replace />} />
        <Route path="queues" element={<QueuesPage />} />
        <Route path="jobs" element={<JobsPage />} />
        <Route path="workers" element={<WorkersPage />} />
        <Route path="dlq" element={<DlqPage />} />
        <Route path="metrics" element={<MetricsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
