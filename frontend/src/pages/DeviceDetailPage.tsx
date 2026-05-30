import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ChevronRight, FileText } from 'lucide-react';
import { Switch3D } from '@/components/three/Switch3D';
import { PortStrip } from '@/components/PortStrip';
import { PortPanel } from '@/components/PortPanel';
import { DeviceConfigView } from '@/components/DeviceConfigView';
import { VendorActions } from '@/components/VendorActions';
import { PlatformIcon } from '@/components/ui/PlatformIcon';
import { StatusDot } from '@/components/ui/StatusDot';
import { Badge } from '@/components/ui/Badge';
import { findPlatformForDevice, isWriteLocked } from '@/lib/devicePolicy';
import { PLATFORM_REGISTRY } from '@/mocks/registry';
import { useAuthStore } from '@/store/auth';
import { useThemeStore } from '@/store/theme';
import { useUIStore } from '@/store/ui';
import {
  useAudit,
  useDevice,
  usePorts,
  useRequests,
} from '@/api/queries';
import { pushToast } from '@/store/toast';
import { cn } from '@/lib/cn';
import type { Environment } from '@/types';

type Tab = 'ports' | 'config';

export function DeviceDetailPage() {
  const { env, deviceId } = useParams<{ env: Environment; deviceId: string }>();
  const navigate = useNavigate();
  const theme = useThemeStore((s) => s.theme);
  const user = useAuthStore((s) => s.user);
  const selectedPort = useUIStore((s) => s.selectedPortName);
  const selectPort = useUIStore((s) => s.selectPort);
  const selectDevice = useUIStore((s) => s.selectDevice);
  const openRequest = useUIStore((s) => s.openRequest);

  const [tab, setTab] = useState<Tab>('ports');

  const { data: device } = useDevice(deviceId);
  const { data: portSnapshot, refetch, dataUpdatedAt } = usePorts(deviceId);
  const ports = portSnapshot?.ports ?? [];
  const { data: requests = [] } = useRequests();
  const { data: audit = [] } = useAudit();

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
    return (
      <div className="flex h-full items-center justify-center text-fg-muted">
        Loading device…
      </div>
    );
  }

  const selectedPortObj = selectedPort ? ports.find((p) => p.name === selectedPort) : null;
  const platform = findPlatformForDevice(device, PLATFORM_REGISTRY);
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
            <div className="flex items-center gap-1.5 text-xs">
              <button
                type="button"
                onClick={() => navigate(`/env/${env}`)}
                className="text-fg-muted hover:text-fg"
              >
                {env?.toUpperCase()}
              </button>
              <ChevronRight size={11} className="text-fg-subtle" />
              <span className="nb-mono text-fg">{device.name}</span>
            </div>
            <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-fg-muted">
              <span className="nb-mono uppercase">{device.platform}</span>
              <span>·</span>
              <span>{device.model}</span>
              <span>·</span>
              <span className="nb-mono">{device.mgmt_ip}</span>
              <span>·</span>
              <span className="flex items-center gap-1">
                <StatusDot state={device.reachable ? 'up' : 'down'} size={6} />
                {device.reachable ? 'reachable' : 'unreachable'}
              </span>
              {readOnly && <Badge variant="warn">Read-only</Badge>}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
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
          </nav>
        </div>
      </header>

      {tab === 'ports' ? (
        <div className="grid h-[calc(100%-3.5rem)] grid-rows-[1.6fr_1fr]">
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
      ) : (
        <DeviceConfigView device={device} ports={ports} user={user!} />
      )}

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
    </div>
  );
}
