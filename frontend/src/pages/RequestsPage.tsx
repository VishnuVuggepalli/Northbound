import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Inbox } from 'lucide-react';
import { RequestRow } from '@/components/requests/RequestRow';
import { useApplyRequest, useApproveRequest, useDevices, useAllPorts, useRejectRequest, useRequests } from '@/api/queries';
import { useAuthStore } from '@/store/auth';
import { useThemeStore } from '@/store/theme';
import { useUIStore } from '@/store/ui';
import { pushToast } from '@/store/toast';
import { cn } from '@/lib/cn';

type FilterKey = 'all' | 'pending' | 'approved' | 'applied' | 'rejected' | 'failed';
const FILTERS: FilterKey[] = ['all', 'pending', 'approved', 'applied', 'rejected', 'failed'];

export function RequestsPage() {
  const user = useAuthStore((s) => s.user)!;
  const theme = useThemeStore((s) => s.theme);
  const setEnv = useUIStore((s) => s.setEnv);
  const selectPort = useUIStore((s) => s.selectPort);
  const navigate = useNavigate();

  const { data: requests = [] } = useRequests();
  const { data: devices = [] } = useDevices();
  const { data: ports = {} } = useAllPorts();
  const approve = useApproveRequest();
  const apply = useApplyRequest();
  const reject = useRejectRequest();

  const [filter, setFilter] = useState<FilterKey>('all');
  const [expanded, setExpanded] = useState<string | null>(null);

  const scope: 'mine' | 'all' = user.role === 'admin' ? 'all' : 'mine';

  // The backend already scopes the list: non-admins get ONLY their own requests
  // (forced server-side by user id), admins get all. So we trust `requests`
  // as-is. We must NOT re-filter by `requested_by` here — that field is the
  // requester's user id (a UUID), while the frontend only knows `user.username`,
  // so a client-side `requested_by === username` compare matches nothing and
  // wrongly empties the page. (`scope` still drives the heading copy below.)
  const filtered = useMemo(() => {
    let list = requests;
    if (filter !== 'all') list = list.filter((r) => r.status === filter);
    return [...list].sort((a, b) => b.created_at - a.created_at);
  }, [requests, filter]);

  const counts = useMemo<Record<FilterKey, number>>(() => {
    const base = requests;
    return {
      all: base.length,
      pending: base.filter((r) => r.status === 'pending').length,
      approved: base.filter((r) => r.status === 'approved').length,
      applied: base.filter((r) => r.status === 'applied').length,
      rejected: base.filter((r) => r.status === 'rejected').length,
      failed: base.filter((r) => r.status === 'failed').length,
    };
  }, [requests]);

  return (
    <div className="mx-auto max-w-6xl px-6 py-6">
      <header className="mb-4">
        <div className="text-xs uppercase tracking-wider text-fg-subtle">
          {scope === 'mine' ? 'Filed by you' : 'Across all sites'}
        </div>
        <h1 className="text-2xl font-semibold text-fg">
          {scope === 'mine' ? 'My requests' : 'All requests'}
        </h1>
      </header>

      <div className="mb-4 flex flex-wrap gap-1.5">
        {FILTERS.map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => setFilter(k)}
            className={cn(
              'flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs',
              filter === k
                ? 'border-accent bg-accent-soft text-fg'
                : 'border-border text-fg-muted hover:bg-bg-elev-2 hover:text-fg',
            )}
          >
            <span className="capitalize">{k}</span>
            <span className="nb-mono text-[10px] text-fg-subtle">{counts[k]}</span>
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-md border border-dashed border-border py-16 text-fg-muted">
          <Inbox size={28} className="text-fg-subtle" />
          <div>No requests in this view.</div>
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map((req) => {
            const dev = devices.find((d) => d.id === req.device_id);
            const port = (ports[req.device_id] ?? []).find((p) => p.name === req.port_name);
            return (
              <RequestRow
                key={req.id}
                request={req}
                device={dev}
                port={port}
                theme={theme}
                user={user}
                mode="mine"
                expanded={expanded === req.id}
                onToggle={() => setExpanded(expanded === req.id ? null : req.id)}
                onApprove={(id) =>
                  approve.mutate(
                    { id, reviewer: user.username },
                    {
                      onSuccess: () =>
                        pushToast({ kind: 'info', title: 'Approved', message: `#${id}` }),
                    },
                  )
                }
                onApply={(id) =>
                  apply.mutate(
                    { id, reviewer: user.username },
                    {
                      onSuccess: () =>
                        pushToast({ kind: 'success', title: 'Applied', message: `#${id}` }),
                    },
                  )
                }
                onReject={(id, comment) =>
                  reject.mutate(
                    { id, reviewer: user.username, comment },
                    {
                      onSuccess: () =>
                        pushToast({ kind: 'info', title: 'Rejected', message: `#${id}` }),
                    },
                  )
                }
                onOpenPort={(deviceId, portName, env) => {
                  setEnv(env);
                  selectPort(portName);
                  navigate(`/env/${env}/devices/${deviceId}`);
                }}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
