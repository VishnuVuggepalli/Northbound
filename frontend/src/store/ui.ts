/**
 * UI store — selection, sidebar, modals, transient state.
 *
 * Auth, theme, and server cache live elsewhere (see `auth.ts`, `theme.ts`,
 * `@tanstack/react-query`). Putting everything in one store leads to
 * fat blast radii on re-renders — split intentionally.
 */

import { create } from 'zustand';
import type { Environment, Port } from '@/models';

interface UIState {
  env: Environment;
  selectedDeviceId: string | null;
  selectedPortName: string | null;
  sidebarWidth: number;
  helpOpen: boolean;
  requestModal: { open: boolean; port: Port | null };

  setEnv: (env: Environment) => void;
  selectDevice: (id: string | null) => void;
  selectPort: (name: string | null) => void;
  setSidebarWidth: (w: number) => void;
  openHelp: () => void;
  closeHelp: () => void;
  openRequest: (port: Port) => void;
  closeRequest: () => void;
  closeOverlays: () => void;
}

export const useUIStore = create<UIState>((set) => ({
  env: 'lab',
  selectedDeviceId: null,
  selectedPortName: null,
  sidebarWidth: 280,
  helpOpen: false,
  requestModal: { open: false, port: null },

  // Setting env never clears selectedDeviceId/Port: the URL is the source of
  // truth for device selection. Effects fire child-before-parent, so a
  // deep-link like /env/lab/devices/<id> would otherwise have its
  // DeviceDetailPage `selectDevice(...)` clobbered by the parent
  // EnvironmentPage's `setEnv(...)`. The DeviceDetailPage clears the port
  // selection when its deviceId changes, so cross-device transitions remain
  // clean.
  setEnv: (env) => set({ env }),
  selectDevice: (id) => set({ selectedDeviceId: id, selectedPortName: null }),
  selectPort: (name) => set({ selectedPortName: name }),
  setSidebarWidth: (w) => set({ sidebarWidth: Math.max(220, Math.min(420, w)) }),
  openHelp: () => set({ helpOpen: true }),
  closeHelp: () => set({ helpOpen: false }),
  openRequest: (port) => set({ requestModal: { open: true, port } }),
  closeRequest: () => set({ requestModal: { open: false, port: null } }),
  closeOverlays: () =>
    set({
      helpOpen: false,
      requestModal: { open: false, port: null },
      selectedPortName: null,
    }),
}));
