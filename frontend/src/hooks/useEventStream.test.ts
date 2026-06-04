import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createElement, type ReactNode } from 'react';
import { useEventStream } from './useEventStream';
import { queryKeys } from '@/api/queries';
import { useLiveStore } from '@/store/live';
import { useToastStore } from '@/store/toast';
import type { Device } from '@/types';

/** Minimal EventSource stand-in: records listeners, lets a test dispatch events. */
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  withCredentials: boolean;
  closed = false;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
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

function device(over: Partial<Device>): Device {
  return { id: 'd1', name: 'spine-1', reachable: true, ...over } as unknown as Device;
}

describe('useEventStream', () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal('EventSource', FakeEventSource as unknown as typeof EventSource);
    useLiveStore.setState({ status: 'closed' });
    useToastStore.setState({ toasts: [] });
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

  it('tracks connection status: connecting → open', () => {
    const qc = new QueryClient();
    renderHook(() => useEventStream(true), { wrapper: wrapper(qc) });
    expect(useLiveStore.getState().status).toBe('connecting');
    FakeEventSource.instances[0].onopen?.();
    expect(useLiveStore.getState().status).toBe('open');
    FakeEventSource.instances[0].onerror?.();
    expect(useLiveStore.getState().status).toBe('connecting');
  });

  it('invalidates device queries on a reachability event', () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, 'invalidateQueries');
    renderHook(() => useEventStream(true), { wrapper: wrapper(qc) });
    FakeEventSource.instances[0].emit('device.reachability', { device_id: 'd1', reachable: false });
    expect(spy).toHaveBeenCalledWith({ queryKey: ['devices'] });
  });

  it('toasts when a cached device flips reachability', () => {
    const qc = new QueryClient();
    qc.setQueryData(queryKeys.devices(), [device({ id: 'd1', name: 'spine-1', reachable: true })]);
    renderHook(() => useEventStream(true), { wrapper: wrapper(qc) });
    FakeEventSource.instances[0].emit('device.reachability', { device_id: 'd1', reachable: false });
    const toasts = useToastStore.getState().toasts;
    expect(toasts).toHaveLength(1);
    expect(toasts[0].kind).toBe('warn');
    expect(toasts[0].title).toContain('spine-1');
  });

  it('stays silent when reachability matches the cached value (no connect-time storm)', () => {
    const qc = new QueryClient();
    qc.setQueryData(queryKeys.devices(), [device({ id: 'd1', reachable: true })]);
    renderHook(() => useEventStream(true), { wrapper: wrapper(qc) });
    FakeEventSource.instances[0].emit('device.reachability', { device_id: 'd1', reachable: true });
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  it('invalidates the device ports query on a ports event', () => {
    const qc = new QueryClient();
    const spy = vi.spyOn(qc, 'invalidateQueries');
    renderHook(() => useEventStream(true), { wrapper: wrapper(qc) });
    FakeEventSource.instances[0].emit('device.ports', { device_id: 'd9' });
    expect(spy).toHaveBeenCalledWith({ queryKey: queryKeys.ports('d9') });
    expect(spy).toHaveBeenCalledWith({ queryKey: queryKeys.allPorts() });
  });

  it('closes the stream and marks status closed on unmount', () => {
    const qc = new QueryClient();
    const { unmount } = renderHook(() => useEventStream(true), { wrapper: wrapper(qc) });
    const source = FakeEventSource.instances[0];
    unmount();
    expect(source.closed).toBe(true);
    expect(useLiveStore.getState().status).toBe('closed');
  });
});
