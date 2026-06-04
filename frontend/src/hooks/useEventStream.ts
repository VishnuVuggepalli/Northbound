import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { queryKeys } from '@/api/queries';

const API_BASE = import.meta.env.VITE_API_BASE ?? '';

/**
 * Subscribe to the backend live-state SSE stream (`GET /api/events/stream`) and
 * invalidate the matching TanStack Query caches as events arrive, so the UI
 * updates without polling (F157).
 *
 * - `device.reachability` → refetch device list + detail (the reachability badge).
 * - `device.ports`        → refetch that device's ports (a write just changed them).
 *
 * The browser `EventSource` authenticates via the same-origin httpOnly session
 * cookie (it cannot set an Authorization header) and reconnects automatically on
 * a dropped connection, so there is no manual retry logic here. The stream is
 * opened only while `enabled` (i.e. authenticated) and closed on unmount.
 */
export function useEventStream(enabled: boolean): void {
  const qc = useQueryClient();
  useEffect(() => {
    // jsdom / older runtimes have no EventSource — no-op rather than throw.
    if (!enabled || typeof EventSource === 'undefined') return;

    const source = new EventSource(`${API_BASE}/api/events/stream`, { withCredentials: true });

    const onReachability = (): void => {
      // Prefix key matches the device list (['devices', env]) and detail
      // (['devices', id]); reachability lives on both.
      void qc.invalidateQueries({ queryKey: ['devices'] });
    };

    const onPorts = (event: MessageEvent): void => {
      let deviceId: string | undefined;
      try {
        deviceId = (JSON.parse(event.data) as { device_id?: string }).device_id;
      } catch {
        // Malformed payload — fall through to the broad invalidation below.
      }
      if (deviceId) void qc.invalidateQueries({ queryKey: queryKeys.ports(deviceId) });
      void qc.invalidateQueries({ queryKey: queryKeys.allPorts() });
    };

    source.addEventListener('device.reachability', onReachability);
    source.addEventListener('device.ports', onPorts);

    return () => {
      source.removeEventListener('device.reachability', onReachability);
      source.removeEventListener('device.ports', onPorts);
      source.close();
    };
  }, [enabled, qc]);
}
