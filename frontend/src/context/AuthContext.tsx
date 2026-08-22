import { createContext, useContext, useState, type ReactNode } from 'react';
import type { UserProfile, Role } from '@/lib/types';
import { demoUser, demoPatient } from '@/lib/demo-data';

interface AuthContextValue {
  user: UserProfile | null;
  isAuthenticated: boolean;
  role: Role;
  signIn: (email: string, _password: string) => void;
  signInWithGoogle: () => void;
  signOut: () => void;
  switchRole: (role: Role) => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [role, setRole] = useState<Role>('patient');

  const signIn = (email: string, _password: string) => {
    setUser({ ...demoUser, email: email || demoUser.email });
  };

  const signInWithGoogle = () => {
    setUser({ ...demoUser, email: 'google-user@holomed.ai' });
  };

  const signOut = () => {
    setUser(null);
  };

  const switchRole = (r: Role) => setRole(r);

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        role,
        signIn,
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

export { demoPatient };
