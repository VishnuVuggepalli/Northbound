import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { QueryClient } from '@tanstack/react-query';
import { createElement, type ReactNode } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { useEventStream } from './useEventStream';
import { queryKeys } from '@/api/queries';

/** Minimal EventSource stand-in: records listeners, lets a test dispatch events. */
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  withCredentials: boolean;
  closed = false;
  private listeners = new Map<string, Set<(e: MessageEvent) => void>>();

  constructor(url: string, init?: { withCredentials?: boolean }) {
    this.url = url;
    this.withCredentials = init?.withCredentials ?? false;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, fn: (e: MessageEvent) => void): void {
    (this.listeners.get(type) ?? this.listeners.set(type, new Set()).get(type)!).add(fn);
  }

  removeEventListener(type: string, fn: (e: MessageEvent) => void): void {
    this.listeners.get(type)?.delete(fn);
  }

  close(): void {
    this.closed = true;
  }

  emit(type: string, data: unknown): void {
    const payload = { data: JSON.stringify(data) } as MessageEvent;
    this.listeners.get(type)?.forEach((fn) => fn(payload));
  }
}

function wrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client }, children);
}

describe('useEventStream', () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal('EventSource', FakeEventSource as unknown as typeof EventSource);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('does not open a stream when not authenticated', () => {
    const qc = new QueryClient();
    renderHook(() => useEventStream(false), { wrapper: wrapper(qc) });
    expect(FakeEventSource.instances).toHaveLength(0);
  });

  it('opens a credentialed stream to /api/events/stream when authenticated', () => {
    const qc = new QueryClient();
    renderHook(() => useEventStream(true), { wrapper: wrapper(qc) });
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].url).toContain('/api/events/stream');
    expect(FakeEventSource.instances[0].withCredentials).toBe(true);
  });

  it('invalidates device queries on a reachability event', () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, 'invalidateQueries');
    renderHook(() => useEventStream(true), { wrapper: wrapper(qc) });
    FakeEventSource.instances[0].emit('device.reachability', {
      device_id: 'd1',
      reachable: false,
    });
    expect(spy).toHaveBeenCalledWith({ queryKey: ['devices'] });
  });

  it('invalidates the device ports query on a ports event', () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, 'invalidateQueries');
    renderHook(() => useEventStream(true), { wrapper: wrapper(qc) });
    FakeEventSource.instances[0].emit('device.ports', { device_id: 'd9' });
    expect(spy).toHaveBeenCalledWith({ queryKey: queryKeys.ports('d9') });
    expect(spy).toHaveBeenCalledWith({ queryKey: queryKeys.allPorts() });
  });

  it('closes the stream on unmount', () => {
    const qc = new QueryClient();
    const { unmount } = renderHook(() => useEventStream(true), { wrapper: wrapper(qc) });
    const source = FakeEventSource.instances[0];
    unmount();
    expect(source.closed).toBe(true);
  });
});
