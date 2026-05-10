/**
 * Toast notifications.
 *
 * Lives outside of React tree so any code (mutations, hotkeys, plain util
 * functions) can call `pushToast(...)` without prop-drilling.
 */

import { create } from 'zustand';

export type ToastKind = 'info' | 'success' | 'warn' | 'error';

export interface Toast {
  id: string;
  title?: string;
  message?: string;
  kind: ToastKind;
}

interface ToastState {
  toasts: Toast[];
  push: (t: Omit<Toast, 'id'> & { duration?: number }) => string;
  dismiss: (id: string) => void;
}

export const useToastStore = create<ToastState>((set, get) => ({
  toasts: [],
  push: (t) => {
    const id = Math.random().toString(36).slice(2);
    const toast: Toast = { id, kind: t.kind, title: t.title, message: t.message };
    set({ toasts: [...get().toasts, toast] });
    const duration = t.duration ?? 3200;
    setTimeout(() => get().dismiss(id), duration);
    return id;
  },
  dismiss: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),
}));

export function pushToast(t: Parameters<ToastState['push']>[0]): string {
  return useToastStore.getState().push(t);
}
