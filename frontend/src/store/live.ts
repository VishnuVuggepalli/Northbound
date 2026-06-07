/**
 * Live SSE connection status, surfaced in the TopBar so users can see that
 * live updates (device reachability, port changes) are actually flowing.
 *
 * Written by `useEventStream` from the EventSource lifecycle; read by the
 * `LiveIndicator`. Kept outside the React tree (zustand) so the single stream
 * owner and the indicator don't need to share a parent.
 */

import { create } from 'zustand';

/** `connecting` covers both the initial open and EventSource auto-reconnect. */
export type LiveStatus = 'connecting' | 'open' | 'closed';

interface LiveState {
  status: LiveStatus;
  setStatus: (status: LiveStatus) => void;
}

export const useLiveStore = create<LiveState>((set) => ({
  status: 'closed',
  setStatus: (status) => set({ status }),
}));
