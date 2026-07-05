import {
  createContext,
  useContext,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, getToken, setToken } from "../api/client";
import type { User } from "../api/types";

interface AuthState {
  token: string | null;
  user: User | null;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string) => Promise<void>;
  logout: () => void;
  loadMe: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

interface TokenResponse {
  access_token: string;
}
interface RegisterResponse {
  user: User;
  access_token: string;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [token, setTok] = useState<string | null>(getToken());
  const [user, setUser] = useState<User | null>(null);

  async function login(email: string, password: string) {
    const res = await api.post<TokenResponse>("/api/v1/auth/login", {
      email,
      password,
    });
    setToken(res.access_token);
    setTok(res.access_token);
    await loadMe();
  }

  async function register(email: string, password: string) {
    const res = await api.post<RegisterResponse>("/api/v1/auth/register", {
      email,
      password,
    });
    setToken(res.access_token);
    setTok(res.access_token);
    setUser(res.user);
  }

  function logout() {
    setToken(null);
    setTok(null);
    setUser(null);
    queryClient.clear(); // drop cached data so nothing leaks across accounts
  }

  async function loadMe() {
    try {
      const me = await api.get<User>("/api/v1/auth/me");
      setUser(me);
    } catch {
      logout();
    }
  }

  return (
    <AuthContext.Provider
      value={{ token, user, login, register, logout, loadMe }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
