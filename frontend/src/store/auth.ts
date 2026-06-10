/**
 * Auth store — current user + role. Deliberately NO token field.
 *
 * The browser session's credential is the httpOnly `nb_access`/`nb_refresh`
 * cookie pair (set by the API, unreadable to JS, sent via
 * `credentials:'include'`). Holding the access token in JS-reachable state
 * would hand a working 30-minute session to any XSS payload — the cookie
 * design exists precisely so that can't happen, so the login response's
 * `access_token` (still returned for non-browser API clients) is discarded.
 *
 * Persists the user identity to localStorage so reload doesn't bounce back to
 * /login; it's re-validated against /api/users/me on mount and the cookie is
 * the real credential. The role switcher in the user menu (mock/demo
 * affordance) also writes here, which the UI reads to decide whether to render
 * admin-only inline buttons.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { AuthSession, User, UserRole } from '@/models';

interface AuthState {
  user: User | null;
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
      isAuthenticated: false,
      setSession: (session) =>
        set({
          user: userFromSession(session),
          isAuthenticated: true,
        }),
      setUser: (user) => set({ user }),
      logout: () => set({ user: null, isAuthenticated: false }),
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
        isAuthenticated: s.isAuthenticated,
      }),
    },
  ),
);

/** Clear the session outside React (used on a 401 from the real client). */
export function clearAuthSession(): void {
  useAuthStore.getState().logout();
}
