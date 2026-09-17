/**
 * AuthContext — real backend authentication.
 *
 * Mechanism:
 *   - Login  → POST /api/v1/auth/login (form body: username + password)
 *              Backend sets HttpOnly cookie `session=<JWT>`.
 *   - Restore → GET /api/v1/auth/me on mount — detects existing cookie.
 *   - Logout  → POST /api/v1/auth/logout — clears cookie.
 *
 * The HttpOnly cookie is sent automatically by the browser on every request
 * (via `credentials: 'include'` in api.ts). No token is stored in JS memory.
 *
 * Public interface is intentionally unchanged so all existing components
 * (AuthScreen, Topbar, Sidebar, etc.) require zero modifications.
 */

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from 'react';
import type { UserProfile, Role } from '@/lib/types';
import { api, ApiError, type MeResponse } from '@/lib/api';

interface AuthContextValue {
  user: UserProfile | null;
  isAuthenticated: boolean;
  role: Role;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<void>;
  signInWithGoogle: () => void;
  signOut: () => void;
  switchRole: (role: Role) => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

/** Map the backend /me response to the frontend UserProfile shape. */
function toProfile(me: MeResponse, role: Role = 'patient'): UserProfile {
  return {
    id: String(me.id),
    email: me.email,
    // Derive a display name from the email (before the @)
    displayName: me.email.split('@')[0],
    role,
  };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [role, setRole] = useState<Role>('patient');
  /** True while the initial session-restore call is in flight */
  const [loading, setLoading] = useState(true);

  // ── Restore session on mount ──────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const me = await api.get<MeResponse>('/api/v1/auth/me');
        if (!cancelled) setUser(toProfile(me, role));
      } catch (err) {
        // 401 = no active session — normal on first visit
        if (!(err instanceof ApiError) || err.status !== 401) {
          console.warn('[AuthContext] Session restore failed:', err);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Sign in ───────────────────────────────────────────────────────────────
  const signIn = useCallback(async (email: string, password: string) => {
    // Backend expects OAuth2PasswordRequestForm — application/x-www-form-urlencoded
    await api.postForm('/api/v1/auth/login', {
      username: email,  // OAuth2 spec uses `username`, backend maps it to email
      password,
    });
    // Cookie is now set. Fetch the user profile.
    const me = await api.get<MeResponse>('/api/v1/auth/me');
    setUser(toProfile(me, role));
  }, [role]);

  // ── Sign up ───────────────────────────────────────────────────────────────
  const signUp = useCallback(async (email: string, password: string) => {
    const params = new URLSearchParams({ email, password });
    await api.postEmpty(`/api/v1/auth/register?${params.toString()}`);
  }, []);

  // ── Google sign-in ────────────────────────────────────────────────────────
  const signInWithGoogle = useCallback(() => {
    window.location.href = '/api/v1/auth/google';
  }, []);

  // ── Sign out ──────────────────────────────────────────────────────────────
  const signOut = useCallback(async () => {
    try {
      await api.postEmpty('/api/v1/auth/logout');
    } catch (err) {
      // Ignore — cookie may already be expired
      console.warn('[AuthContext] Logout error (non-fatal):', err);
    } finally {
      setUser(null);
    }
  }, []);

  // ── Role switcher (frontend-only; backend doesn't implement role switching) ─
  const switchRole = useCallback((r: Role) => setRole(r), []);

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        role,
        loading,
        signIn,
        signUp,
        signInWithGoogle,
        signOut,
        switchRole,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}

// Re-export for backward compat (AuthContext was previously exporting demoPatient)
export { };
