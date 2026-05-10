/**
 * Auth store — current user + role.
 *
 * Persists to localStorage so reload doesn't bounce back to /login. The role
 * switcher in the user menu also writes here, which the UI reads to decide
 * whether to render admin-only inline buttons.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { User, UserRole } from '@/types';
import { USERS } from '@/mocks/fixtures';

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  login: (username: string) => void;
  logout: () => void;
  switchRole: (role: UserRole) => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      isAuthenticated: false,
      login: (username) => {
        const user = USERS.find((u) => u.username === username) ?? USERS[0]!;
        set({ user, isAuthenticated: true });
      },
      logout: () => set({ user: null, isAuthenticated: false }),
      switchRole: (role) => {
        // Demo affordance: pick the first user with that role.
        const target = USERS.find((u) => u.role === role);
        if (!target) return;
        const current = get().user;
        if (!current || current.role !== role) {
          set({ user: target, isAuthenticated: true });
        }
      },
    }),
    {
      name: 'nb-auth',
      partialize: (s) => ({ user: s.user, isAuthenticated: s.isAuthenticated }),
    },
  ),
);
