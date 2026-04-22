import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

export type Role = 'viewer' | 'operator' | 'admin';

export interface AuthUser {
  username: string;
  role: Role;
}

interface LoginResponse {
  token: string;
  username: string;
  role: Role;
  expires_at?: string;
}

interface AuthContextValue {
  user: AuthUser | null;
  token: string | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
  isAuthenticated: boolean;
}

const TOKEN_KEY = 'traffic_intel.token';
const AuthContext = createContext<AuthContextValue | null>(null);

// Module-scoped holder for the current token so the fetch interceptor can
// read it without re-wrapping on every render.
let activeToken: string | null =
  typeof window !== 'undefined' ? window.localStorage.getItem(TOKEN_KEY) : null;

// Install the fetch interceptor exactly once. Every same-origin /api/* call
// picks up the Authorization header automatically.
let interceptorInstalled = false;
function installFetchInterceptor() {
  if (interceptorInstalled || typeof window === 'undefined') return;
  interceptorInstalled = true;
  const original = window.fetch.bind(window);
  window.fetch = async (
    input: RequestInfo | URL,
    init?: RequestInit,
  ): Promise<Response> => {
    let url = '';
    if (typeof input === 'string') url = input;
    else if (input instanceof URL) url = input.toString();
    else url = input.url;

    const isApi = url.startsWith('/api/') || url.includes('/api/');
    if (isApi && activeToken) {
      const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
      if (!headers.has('Authorization')) {
        headers.set('Authorization', `Bearer ${activeToken}`);
      }
      return original(input, { ...(init ?? {}), headers });
    }
    return original(input, init);
  };
}

async function fetchMe(token: string): Promise<AuthUser> {
  const res = await fetch('/api/auth/me', {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error(`auth/me ${res.status}`);
  const j = (await res.json()) as AuthUser;
  return { username: j.username, role: j.role };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(activeToken);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState<boolean>(!!activeToken);
  const mounted = useRef(true);

  useEffect(() => {
    installFetchInterceptor();
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  // Rehydrate on mount if a token is already in localStorage.
  useEffect(() => {
    if (!token) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const u = await fetchMe(token);
        if (!cancelled) setUser(u);
      } catch {
        if (!cancelled) {
          activeToken = null;
          window.localStorage.removeItem(TOKEN_KEY);
          setToken(null);
          setUser(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      let detail = `login failed (${res.status})`;
      try {
        const j = await res.json();
        if (j?.detail) detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail);
      } catch {
        /* keep default detail */
      }
      throw new Error(detail);
    }
    const j = (await res.json()) as LoginResponse;
    activeToken = j.token;
    window.localStorage.setItem(TOKEN_KEY, j.token);
    setToken(j.token);
    setUser({ username: j.username, role: j.role });
  }, []);

  const logout = useCallback(() => {
    activeToken = null;
    window.localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setUser(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      token,
      loading,
      login,
      logout,
      isAuthenticated: !!user && !!token,
    }),
    [user, token, loading, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}

const ROLE_RANK: Record<Role, number> = { viewer: 1, operator: 2, admin: 3 };

export function roleAtLeast(role: Role | undefined, min: Role): boolean {
  if (!role) return false;
  return ROLE_RANK[role] >= ROLE_RANK[min];
}
