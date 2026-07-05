import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Page, Project } from "../api/types";

interface ProjectState {
  projects: Project[];
  selected: Project | null;
  selectedId: number | null;
  setSelectedId: (id: number) => void;
  isLoading: boolean;
}

const ProjectContext = createContext<ProjectState | null>(null);

export function ProjectProvider({ children }: { children: ReactNode }) {
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.get<Page<Project>>("/api/v1/projects?limit=200"),
  });

  const projects = data?.items ?? [];

  useEffect(() => {
    if (selectedId === null && projects.length > 0) {
      setSelectedId(projects[0].id);
    }
  }, [projects, selectedId]);

  const selected = projects.find((p) => p.id === selectedId) ?? null;

  return (
    <ProjectContext.Provider
      value={{ projects, selected, selectedId, setSelectedId, isLoading }}
    >
      {children}
    </ProjectContext.Provider>
  );
}

export function useProject(): ProjectState {
  const ctx = useContext(ProjectContext);
  if (!ctx) throw new Error("useProject must be used within ProjectProvider");
  return ctx;
}
