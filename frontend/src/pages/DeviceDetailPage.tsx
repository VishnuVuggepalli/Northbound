import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { AlertTriangle, Cpu, FileText, Power, RefreshCw, Trash2 } from 'lucide-react';
import { Switch3D } from '@/components/three/Switch3D';
import { PortStrip } from '@/components/PortStrip';
import { PortPanel } from '@/components/PortPanel';
import { DeviceConfigView } from '@/components/DeviceConfigView';
import { DeviceSystemView } from '@/components/DeviceSystemView';
import { VendorActions } from '@/components/VendorActions';
import { PlatformIcon } from '@/shared/PlatformIcon';
import { StatusDot } from '@/shared/StatusDot';
import { Badge } from '@/shared/Badge';
import { Button } from '@/shared/Button';
import { Modal } from '@/modals/Modal';
import { findPlatformForDevice, isWriteLocked } from '@/lib/devicePolicy';
import { isApiError } from '@/api';
import { useAuthStore } from '@/store/auth';
import { useThemeStore } from '@/store/theme';
import { useUIStore } from '@/store/ui';
import {
  useAudit,
  useDeleteDevice,
  useDevice,
  usePorts,
  usePlatforms,
  useRediscoverDevice,
  useRequests,
  useSetDeviceWrites,
} from '@/api/queries';
import { pushToast } from '@/store/toast';
import { cn } from '@/lib/cn';

type Tab = 'ports' | 'config' | 'system';

export function DeviceDetailPage() {
  const { deviceId } = useParams<{ deviceId: string }>();
  const navigate = useNavigate();
  const theme = useThemeStore((s) => s.theme);
  const user = useAuthStore((s) => s.user);
  const selectedPort = useUIStore((s) => s.selectedPortName);
  const selectPort = useUIStore((s) => s.selectPort);
  const selectDevice = useUIStore((s) => s.selectDevice);
  const openRequest = useUIStore((s) => s.openRequest);

  const [tab, setTab] = useState<Tab>('ports');

  const { data: device, isError: deviceError, error: deviceErr } = useDevice(deviceId);
  const { data: portSnapshot, refetch, dataUpdatedAt } = usePorts(deviceId);
  const ports = portSnapshot?.ports ?? [];
  const { data: requests = [] } = useRequests();
  const { data: audit = [] } = useAudit();
  // Must be called unconditionally (before any early return) so the hook order
  // is stable across renders — otherwise React crashes the page to blank once
  // `device` loads and an extra hook appears. (react-hooks/rules-of-hooks)
  const { data: platforms } = usePlatforms();
  const isAdmin = user?.role === 'admin';
  const setWrites = useSetDeviceWrites(deviceId ?? '');
  const rediscover = useRediscoverDevice(deviceId ?? '');
  const remove = useDeleteDevice(deviceId ?? '');
  const [confirmRemove, setConfirmRemove] = useState(false);

  // Sync the route's device id into the UI store so global hotkeys (j/k/r)
  // know which device's ports to navigate. Reaching this page via URL (no
  // sidebar click) used to leave selectedDeviceId=null and silently break
  // keyboard navigation.
  useEffect(() => {
    if (deviceId) selectDevice(deviceId);
  }, [deviceId, selectDevice]);

  // Reset selected port when device changes
  useEffect(() => {
    selectPort(null);
  }, [deviceId, selectPort]);

  if (!device) {
    // Distinguish a real fetch failure (404 / backend down) from loading —
    // otherwise an error sits on "Loading device…" forever with no recourse.
    if (deviceError) {
      return (
        <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
          <AlertTriangle className="text-danger" size={24} aria-hidden />
          <div className="text-sm text-fg">
            Couldn&apos;t load this device.
            <span className="mt-1 block text-fg-muted">
              {deviceErr instanceof Error
                ? deviceErr.message
                : 'It may not exist, or the backend is unreachable.'}
            </span>
          </div>
          <Button kind="outline" onClick={() => navigate(-1)}>
            Go back
          </Button>
        </div>
      );
    }
    return (
      <div className="flex h-full items-center justify-center text-fg-muted">Loading device…</div>
    );
  }

  const selectedPortObj = selectedPort ? ports.find((p) => p.name === selectedPort) : null;
  const platform = findPlatformForDevice(device, platforms ?? []);
  const readOnly = isWriteLocked(device, platform);

  return (
    <div className="flex h-full flex-col">
      <header
        className="nb-reveal flex items-center justify-between gap-4 border-b border-border bg-bg-elev-1/40 px-5 py-3"
        style={{ '--nb-reveal-i': 0 } as React.CSSProperties}
      >
        <div className="flex items-center gap-3">
          <PlatformIcon platform={device.platform} role={device.role} size={16} />
          <div>
            {/* Breadcrumb trail (Home › Lab › device) is now the global
                <Breadcrumbs/> in the shell; here we keep the device name as the
                page heading. */}
            <h1 className="nb-mono text-sm text-fg">{device.name}</h1>
            <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-fg-muted">
              <span className="nb-mono uppercase">{device.platform}</span>
              <span>·</span>
              <span>{device.model}</span>
              <span>·</span>
              <span className="nb-mono">{device.mgmt_ip}</span>
              <span>·</span>
              <span className="flex items-center gap-1">
                <StatusDot
                  state={
                    device.reachable == null ? 'pending' : device.reachable ? 'up' : 'down'
                  }
                  size={6}
                />
                {device.reachable == null
                  ? 'checking…'
                  : device.reachable
                    ? 'reachable'
                    : 'unreachable'}
              </span>
              {readOnly && <Badge variant="warn">Read-only</Badge>}
              {!readOnly && device.writes_enabled === false && (
                <Badge variant="warn">Writes disabled</Badge>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {isAdmin && (
            <button
              type="button"
              disabled={rediscover.isPending}
              onClick={() =>
                rediscover.mutate(undefined, {
                  onSuccess: (r) =>
                    pushToast({
                      kind: 'success',
                      message: `Re-discovered ${device.name}: ${r.ports_total} ports${
                        r.ports_added ? ` (${r.ports_added} new)` : ''
                      }.`,
                    }),
                  onError: (e: unknown) =>
                    pushToast({
                      kind: 'error',
                      message: e instanceof Error ? e.message : 'Re-discovery failed.',
                    }),
                })
              }
              title="Re-probe the device and refresh its stored ports + config baseline"
              className="flex h-9 items-center gap-1.5 rounded-md border border-border px-2.5 text-xs font-medium text-fg-muted transition hover:bg-bg-elev-2 hover:text-fg disabled:opacity-50"
            >
              <RefreshCw size={13} className={rediscover.isPending ? 'animate-spin' : ''} />
              Re-discover
            </button>
          )}
          {isAdmin && !readOnly && (
            <button
              type="button"
              disabled={setWrites.isPending}
              onClick={() => setWrites.mutate(device.writes_enabled === false)}
              title="Enable or disable config writes for this device"
              className={cn(
                'flex h-9 items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium transition',
                device.writes_enabled === false
                  ? 'border-danger/40 bg-danger/10 text-danger hover:bg-danger/20'
                  : 'border-success/40 bg-success/10 text-success hover:bg-success/20',
              )}
            >
              <Power size={13} />
              {device.writes_enabled === false ? 'Writes off' : 'Writes on'}
            </button>
          )}
          {isAdmin && (
            <button
              type="button"
              onClick={() => setConfirmRemove(true)}
              title="Remove (offboard) this device"
              className="flex h-9 items-center gap-1.5 rounded-md border border-danger/40 px-2.5 text-xs font-medium text-danger transition hover:bg-danger/10"
            >
              <Trash2 size={13} />
              Remove
            </button>
          )}
          <VendorActions device={device} platform={platform} />
          <nav className="flex items-center gap-0.5 rounded-md border border-border bg-bg-elev-1 p-0.5 text-xs">
          <button
            type="button"
            onClick={() => setTab('ports')}
            className={cn(
              'rounded-[4px] px-3 py-1.5 font-medium',
              tab === 'ports' ? 'bg-bg-elev-2 text-fg' : 'text-fg-muted hover:text-fg',
            )}
          >
            Ports
          </button>
          <button
            type="button"
            onClick={() => setTab('config')}
            className={cn(
              'flex items-center gap-1 rounded-[4px] px-3 py-1.5 font-medium',
              tab === 'config' ? 'bg-bg-elev-2 text-fg' : 'text-fg-muted hover:text-fg',
            )}
          >
            <FileText size={11} />
            Config
          </button>
          <button
            type="button"
            onClick={() => setTab('system')}
            className={cn(
              'flex items-center gap-1 rounded-[4px] px-3 py-1.5 font-medium',
              tab === 'system' ? 'bg-bg-elev-2 text-fg' : 'text-fg-muted hover:text-fg',
            )}
          >
            <Cpu size={11} />
            System
          </button>
          </nav>
        </div>
      </header>

      <div className="min-h-0 flex-1">
        {tab === 'ports' &&
          (ports.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-sm">
              <AlertTriangle
                className={device.reachable === false ? 'text-warn' : 'text-fg-subtle'}
                size={24}
                aria-hidden
              />
              {device.reachable === false ? (
                <>
                  <span className="text-fg">
                    This device is unreachable — its ports can&apos;t be read right now.
                  </span>
                  <span className="text-fg-muted">Check connectivity, then Re-discover.</span>
                </>
              ) : (
                <>
                  <span className="text-fg">No ports to show yet.</span>
                  <span className="text-fg-muted">
                    Use Re-discover to fetch the live port list.
                  </span>
                </>
              )}
            </div>
          ) : (
            <div className="grid h-full grid-rows-[1.6fr_1fr]">
            <div
              className="nb-reveal overflow-hidden p-4"
              style={{ '--nb-reveal-i': 1 } as React.CSSProperties}
            >
              <Switch3D
                device={device}
                ports={ports}
                theme={theme}
                selectedPort={selectedPort}
                onPick={(p) => selectPort(p.name)}
              />
            </div>
            <div className="overflow-hidden border-t border-border bg-bg-elev-1/40">
              <PortStrip
                device={device}
                ports={ports}
                requests={requests}
                selected={selectedPort}
                theme={theme}
                onSelect={(name) => selectPort(name)}
              />
            </div>
          </div>
          ))}
        {tab === 'config' && <DeviceConfigView device={device} ports={ports} user={user!} />}
        {tab === 'system' && <DeviceSystemView device={device} />}
      </div>

      {selectedPortObj && (
        <PortPanel
          device={device}
          port={selectedPortObj}
          requests={requests}
          audit={audit}
          theme={theme}
          user={user!}
          fetchedAt={dataUpdatedAt || undefined}
          onClose={() => selectPort(null)}
          onOpenRequest={() => openRequest(selectedPortObj)}
          onRefetch={() => {
            void refetch();
            pushToast({
              kind: 'info',
              title: 'Refetching live state',
              message: '~600ms typical',
            });
          }}
        />
      )}

      <Modal
        open={confirmRemove}
        onClose={() => {
          if (!remove.isPending) setConfirmRemove(false);
        }}
        title="Remove device?"
        subtitle={device.name}
        footer={
          <>
            <Button kind="ghost" onClick={() => setConfirmRemove(false)} disabled={remove.isPending}>
              Cancel
            </Button>
            <Button
              kind="danger"
              disabled={remove.isPending}
              onClick={() =>
                remove.mutate(undefined, {
                  onSuccess: () => {
                    setConfirmRemove(false);
                    pushToast({ kind: 'success', message: `Removed ${device.name}.` });
                    navigate(`/env/${device.env}`);
                  },
                  onError: (e: unknown) => {
                    const msg =
                      isApiError(e) && e.status === 409
                        ? 'This device has change-request history and can’t be hard-deleted — the change trail must be retained.'
                        : e instanceof Error
                          ? e.message
                          : 'Remove failed.';
                    pushToast({ kind: 'error', message: msg });
                  },
                })
              }
            >
              {remove.isPending ? 'Removing…' : 'Remove device'}
            </Button>
          </>
        }
      >
        <p className="text-sm text-fg-muted">
          This offboards <span className="text-fg">{device.name}</span> ({device.mgmt_ip}) and
          deletes its stored port metadata and config backups. The audit trail is retained. This
          can&apos;t be undone.
        </p>
      </Modal>
    </div>
  );
}
