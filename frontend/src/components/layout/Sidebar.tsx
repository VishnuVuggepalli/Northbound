import { useEffect, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Plus } from 'lucide-react';
import { useDevices, useRequests, useSites } from '@/api/queries';
import { useUIStore } from '@/store/ui';
import { PlatformIcon } from '@/components/ui/PlatformIcon';
import { StatusDot } from '@/components/ui/StatusDot';
import { Badge } from '@/components/ui/Badge';
import { SkeletonList } from '@/components/ui/Skeleton';
import { cn } from '@/lib/cn';
import { plural } from '@/lib/format';
import type { Device, DeviceRole, Environment } from '@/types';

const ROLE_ORDER: DeviceRole[] = ['spine', 'leaf', 'router', 'vpn'];
const ROLE_LABELS: Record<DeviceRole, string> = {
  spine: 'Spines',
  leaf: 'Leaves',
  router: 'Routers',
  vpn: 'VPN',
};

interface SidebarProps {
  env: Environment;
}

export function Sidebar({ env }: SidebarProps) {
  const navigate = useNavigate();
  const params = useParams();
  const { data: devices = [], isLoading: devicesLoading } = useDevices(env);
  const { data: requests = [] } = useRequests();
  const { data: sites = [] } = useSites();
  const siteName = sites.find((s) => s.slug === env)?.name ?? env;
  const width = useUIStore((s) => s.sidebarWidth);
  const setSidebarWidth = useUIStore((s) => s.setSidebarWidth);
  const selectDevice = useUIStore((s) => s.selectDevice);

  const dragRef = useRef<{ active: boolean; startX: number; startW: number }>({
    active: false,
    startX: 0,
    startW: 0,
  });

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragRef.current.active) return;
      setSidebarWidth(dragRef.current.startW + (e.clientX - dragRef.current.startX));
    };
    const onUp = () => {
      dragRef.current.active = false;
      document.body.classList.remove('cursor-col-resize');
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [setSidebarWidth]);

  const grouped: Record<DeviceRole, Device[]> = {
    spine: [],
    leaf: [],
    router: [],
    vpn: [],
  };
  for (const d of devices) grouped[d.role].push(d);

  return (
    <aside
      style={{ width }}
      className="relative shrink-0 border-r border-border bg-bg-elev-1/60"
    >
      <div className="flex h-full flex-col overflow-y-auto nb-scroll">
        <div className="border-b border-border px-4 py-3">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-xs uppercase tracking-wider text-fg-subtle">{siteName}</div>
              <div className="text-sm font-semibold text-fg">{plural(devices.length, 'device')}</div>
            </div>
            <button
              type="button"
              onClick={() => navigate('/onboard')}
              title="Add device"
              className="rounded-md p-1.5 text-fg-muted hover:bg-bg-elev-2 hover:text-fg"
            >
              <Plus size={14} />
            </button>
          </div>
        </div>

        {devicesLoading && devices.length === 0 && (
          <div className="p-3">
            <SkeletonList rows={4} rowClassName="h-7" />
          </div>
        )}
        {!devicesLoading && devices.length === 0 && (
          <div className="px-4 py-6 text-center text-xs text-fg-muted">
            No devices in {siteName} yet.{' '}
            <button
              type="button"
              onClick={() => navigate('/onboard')}
              className="text-accent hover:underline"
            >
              Onboard one
            </button>
          </div>
        )}

        {ROLE_ORDER.map((role) => {
          const list = grouped[role];
          if (!list.length) return null;
          return (
            <div key={role} className="border-b border-border px-2 py-2">
              <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-fg-subtle">
                {ROLE_LABELS[role]}
              </div>
              <ul className="space-y-0.5">
                {list.map((d) => {
                  const pendingCount = requests.filter(
                    (r) => r.device_id === d.id && r.status === 'pending',
                  ).length;
                  const isSelected = params.deviceId === d.id;
                  return (
                    <li key={d.id}>
                      <button
                        type="button"
                        onClick={() => {
                          selectDevice(d.id);
                          navigate(`/env/${env}/devices/${d.id}`);
                        }}
                        className={cn(
                          'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-sm text-fg-muted transition-colors',
                          isSelected
                            ? 'bg-accent-soft text-fg shadow-[0_0_0_1px_var(--nb-accent-soft)_inset]'
                            : 'hover:bg-bg-elev-2 hover:text-fg',
                        )}
                      >
                        <PlatformIcon platform={d.platform} role={d.role} />
                        <span className="nb-mono flex-1 truncate text-left">{d.name}</span>
                        <span className="flex items-center gap-1.5">
                          {pendingCount > 0 && (
                            <Badge variant="warn" title={`${pendingCount} pending`}>
                              {pendingCount}
                            </Badge>
                          )}
                          <StatusDot
                            state={d.reachable == null ? 'pending' : d.reachable ? 'up' : 'down'}
                            label={
                              d.reachable == null
                                ? 'Reachability unknown'
                                : d.reachable
                                  ? 'Reachable'
                                  : 'Unreachable'
                            }
                          />
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </div>

      {/*
        WCAG 2.5.7 (Dragging movements): the resize handle must have a
        non-drag alternative. We expose a focusable separator with an
        aria-valuenow so AT users see the current width, and bind ←/→ keys to
        nudge it in 16px steps. PageUp/PageDown step by 64px, Home/End jump
        to min/max.
      */}
      <div
        role="separator"
        aria-orientation="vertical"
        aria-valuemin={220}
        aria-valuemax={420}
        aria-valuenow={width}
        aria-label="Resize sidebar"
        tabIndex={0}
        onMouseDown={(e) => {
          dragRef.current = { active: true, startX: e.clientX, startW: width };
          document.body.classList.add('cursor-col-resize');
        }}
        onKeyDown={(e) => {
          let next = width;
          if (e.key === 'ArrowLeft') next = width - 16;
          else if (e.key === 'ArrowRight') next = width + 16;
          else if (e.key === 'PageUp') next = width - 64;
          else if (e.key === 'PageDown') next = width + 64;
          else if (e.key === 'Home') next = 220;
          else if (e.key === 'End') next = 420;
          else return;
          e.preventDefault();
          setSidebarWidth(next);
        }}
        className="absolute -right-1 top-0 h-full w-2 cursor-col-resize focus-visible:outline-none focus-visible:bg-accent/40"
      />
    </aside>
  );
}
