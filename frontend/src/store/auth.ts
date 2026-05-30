/**
 * Auth store — current user + role + bearer token.
 *
 * Persists to localStorage so reload doesn't bounce back to /login. The token
 * is the credential the real API client attaches as `Authorization: Bearer`.
 * The mock client mints a fake token; either way the store shape is identical
 * so nothing downstream branches on which client is active.
 *
 * The role switcher in the user menu (mock/demo affordance) also writes here,
 * which the UI reads to decide whether to render admin-only inline buttons.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { AuthSession, User, UserRole } from '@/types';

interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  /** Persist a fresh session after a successful login / `me` refresh. */
  setSession: (session: AuthSession) => void;
  /** Replace the user object (e.g. after `GET /api/users/me` enriches it). */
  setUser: (user: User) => void;
  logout: () => void;
  /** Demo affordance: flip the role of the current (mock) session in place. */
  switchRole: (role: UserRole) => void;
}

function userFromSession(session: AuthSession): User {
  return { username: session.username, role: session.role, name: session.username };
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      token: null,
      isAuthenticated: false,
      setSession: (session) =>
        set({
          user: userFromSession(session),
          token: session.access_token,
          isAuthenticated: true,
        }),
      setUser: (user) => set({ user }),
      logout: () => set({ user: null, token: null, isAuthenticated: false }),
      switchRole: (role) => {
        const current = get().user;
        if (!current || current.role === role) return;
        set({ user: { ...current, role } });
      },
    }),
    {
      name: 'nb-auth',
      partialize: (s) => ({
        user: s.user,
        token: s.token,
        isAuthenticated: s.isAuthenticated,
      }),
    },
  ),
);

/** Read the bearer token outside React (used by the real API client). */
export function getAuthToken(): string | null {
  return useAuthStore.getState().token;
}

/** Clear the session outside React (used on a 401 from the real client). */
export function clearAuthSession(): void {
  useAuthStore.getState().logout();
}
