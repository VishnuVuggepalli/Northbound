import { useEffect } from 'react';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/api/queries';
import { useLiveStore } from '@/store/live';
import { pushToast } from '@/store/toast';
import type { Device } from '@/models';

const API_BASE = import.meta.env.VITE_API_BASE ?? '';

/**
 * Subscribe to the backend live-state SSE stream (`GET /api/events/stream`) and
 * reflect it in the UI (F157), without polling:
 *
 * - `device.reachability` → refetch device list + detail, and toast when a
 *   device flips reachable↔unreachable *relative to what the user currently
 *   sees* (comparing against cache avoids a toast storm on connect, when the
 *   backend replays first-observation events that already match the cache).
 * - `device.ports`        → refetch that device's ports (a write just changed them).
 *
 * Connection status is published to `useLiveStore` so the TopBar can show a
 * live indicator. The browser `EventSource` authenticates via the same-origin
 * httpOnly session cookie (it cannot set an Authorization header) and reconnects
 * automatically on a dropped connection. Opened only while `enabled`.
 */
export function useEventStream(enabled: boolean): void {
  const qc = useQueryClient();
  const setStatus = useLiveStore((s) => s.setStatus);

  useEffect(() => {
    // jsdom / older runtimes have no EventSource — no-op rather than throw.
    if (!enabled || typeof EventSource === 'undefined') return;

    setStatus('connecting');
    const source = new EventSource(`${API_BASE}/api/events/stream`, { withCredentials: true });

    source.onopen = () => setStatus('open');
    // EventSource auto-reconnects after an error; reflect it as "connecting".
    source.onerror = () => setStatus('connecting');

    const onReachability = (event: MessageEvent): void => {
      const data = parseEvent<{ device_id?: string; reachable?: boolean }>(event);
      if (data?.device_id !== undefined && data.reachable !== undefined) {
        maybeToastReachability(qc, data.device_id, data.reachable);
      }
      // Prefix key matches the device list (['devices', env]) and detail
      // (['devices', id]); reachability lives on both.
      void qc.invalidateQueries({ queryKey: ['devices'] });
    };

    const onPorts = (event: MessageEvent): void => {
      const deviceId = parseEvent<{ device_id?: string }>(event)?.device_id;
      if (deviceId) void qc.invalidateQueries({ queryKey: queryKeys.ports(deviceId) });
      void qc.invalidateQueries({ queryKey: queryKeys.allPorts() });
    };

    // `request.timeline` → a comment (or transition) landed on a request: refresh
    // that request's open thread + the requests list. Powers the live comment thread.
    const onRequestTimeline = (event: MessageEvent): void => {
      const id = parseEvent<{ request_id?: string }>(event)?.request_id;
      if (id) void qc.invalidateQueries({ queryKey: ['requests', id, 'timeline'] });
      void qc.invalidateQueries({ queryKey: ['requests'] });
    };

    source.addEventListener('device.reachability', onReachability);
    source.addEventListener('device.ports', onPorts);
    source.addEventListener('request.timeline', onRequestTimeline);

    return () => {
      source.removeEventListener('device.reachability', onReachability);
      source.removeEventListener('device.ports', onPorts);
      source.removeEventListener('request.timeline', onRequestTimeline);
      source.close();
      setStatus('closed');
    };
  }, [enabled, qc, setStatus]);
}

function parseEvent<T>(event: MessageEvent): T | undefined {
  try {
    return JSON.parse(event.data) as T;
  } catch {
    return undefined;
  }
}

/** Find a device by id across all cached `['devices', …]` queries (list + detail). */
function findCachedDevice(qc: QueryClient, deviceId: string): Device | undefined {
  for (const [, data] of qc.getQueriesData<Device[] | Device>({ queryKey: ['devices'] })) {
    if (Array.isArray(data)) {
      const hit = data.find((d) => d.id === deviceId);
      if (hit) return hit;
    } else if (data && data.id === deviceId) {
      return data;
    }
  }
  return undefined;
}

/** Toast only when the new reachability differs from what the user currently sees. */
function maybeToastReachability(qc: QueryClient, deviceId: string, reachable: boolean): void {
  const device = findCachedDevice(qc, deviceId);
  // No cached view, or no real change from it → stay silent (avoids connect-time storm).
  if (!device || device.reachable === reachable) return;
  pushToast(
    reachable
      ? { kind: 'success', title: `${device.name} is reachable` }
      : { kind: 'warn', title: `${device.name} is unreachable` },
  );
}
