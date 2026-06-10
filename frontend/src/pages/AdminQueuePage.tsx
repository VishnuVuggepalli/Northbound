import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Inbox } from 'lucide-react';
import { RequestRow } from '@/components/requests/RequestRow';
import {
  useApplyRequest,
  useApproveRequest,
  useDevices,
  useAllPorts,
  useRejectRequest,
  useRequests,
  useSites,
} from '@/api/queries';
import { isApiError } from '@/api';
import { useAuthStore } from '@/store/auth';
import { useThemeStore } from '@/store/theme';
import { useUIStore } from '@/store/ui';
import { pushToast } from '@/store/toast';
import { cn } from '@/lib/cn';

type SortKey = 'age' | 'env' | 'requester';

/** Readable message for a failed apply. A 409 STATE_DRIFT / ALREADY_CLAIMED detail
 *  is a JSON object the transport can't flatten, so ApiError.message degrades to
 *  the bare status text ("Conflict") — phrase those; pass real details through. */
function applyErrorMessage(e: unknown): string {
  if (isApiError(e) && e.status === 409 && /^(conflict|http 409)$/i.test(e.message)) {
    return 'Device state drifted or another admin already applied it. Refetch and retry.';
  }
  return e instanceof Error ? e.message : 'Apply failed.';
}

export function AdminQueuePage() {
  const user = useAuthStore((s) => s.user);
  const theme = useThemeStore((s) => s.theme);
  const setEnv = useUIStore((s) => s.setEnv);
  const selectPort = useUIStore((s) => s.selectPort);
  const navigate = useNavigate();

  const { data: requests = [] } = useRequests();
  const { data: devices = [] } = useDevices();
  const { data: ports = {} } = useAllPorts();
  const { data: sites = [] } = useSites();
  const approve = useApproveRequest();
  const apply = useApplyRequest();
  const reject = useRejectRequest();

  const [envFilter, setEnvFilter] = useState<string>('all');
  const [sort, setSort] = useState<SortKey>('age');
  const [expanded, setExpanded] = useState<string | null>(null);

  const list = useMemo(() => {
    let l = requests.filter((r) => r.status === 'pending' || r.status === 'approved');
    if (envFilter !== 'all') {
      l = l.filter((r) => devices.find((d) => d.id === r.device_id)?.env === envFilter);
    }
    if (sort === 'age') l = [...l].sort((a, b) => a.created_at - b.created_at);
    if (sort === 'env') {
      l = [...l].sort((a, b) => {
        const ea = devices.find((d) => d.id === a.device_id)?.env ?? '';
        const eb = devices.find((d) => d.id === b.device_id)?.env ?? '';
        return ea.localeCompare(eb);
      });
    }
    if (sort === 'requester') l = [...l].sort((a, b) => a.requested_by.localeCompare(b.requested_by));
    return l;
  }, [requests, envFilter, sort, devices]);

  const counts = useMemo(
    () => ({
      pending: requests.filter((r) => r.status === 'pending').length,
      approved: requests.filter((r) => r.status === 'approved').length,
    }),
    [requests],
  );

  if (user?.role !== 'admin') {
    return (
      <div className="flex h-full items-center justify-center text-fg-muted">
        Admin only.
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-6">
      <header className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-wider text-fg-subtle">
            {counts.pending} pending · {counts.approved} approved waiting to apply
          </div>
          <h1 className="text-2xl font-semibold text-fg">Request queue</h1>
        </div>
        <div className="flex items-center gap-2">
          <SegmentedFilter
            value={envFilter}
            options={[
              { value: 'all', label: 'All' },
              ...sites.map((s) => ({ value: s.slug, label: s.name })),
            ]}
            onChange={(v) => setEnvFilter(v)}
          />
          <SegmentedFilter
            value={sort}
            options={[
              { value: 'age', label: 'Oldest' },
              { value: 'env', label: 'Env' },
              { value: 'requester', label: 'Requester' },
            ]}
            onChange={(v) => setSort(v)}
          />
        </div>
      </header>

      {list.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-md border border-dashed border-border py-16 text-fg-muted">
          <Inbox size={28} className="text-fg-subtle" />
          <div>Inbox zero. Nice.</div>
        </div>
      ) : (
        <div className="space-y-2">
          {list.map((req) => {
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
                mode="queue"
                expanded={expanded === req.id}
                onToggle={() => setExpanded(expanded === req.id ? null : req.id)}
                onApprove={(id) =>
                  approve.mutate(
                    { id, reviewer: user.username },
                    {
                      onSuccess: () =>
                        pushToast({ kind: 'info', title: 'Approved', message: `#${id}` }),
                      onError: (e: unknown) =>
                        pushToast({
                          kind: 'error',
                          title: 'Approve failed',
                          message: e instanceof Error ? e.message : 'Approve failed.',
                        }),
                    },
                  )
                }
                onApply={(id) =>
                  apply.mutate(
                    { id, reviewer: user.username },
                    {
                      onSuccess: () =>
                        pushToast({ kind: 'success', title: 'Applied', message: `#${id}` }),
                      onError: (e: unknown) =>
                        pushToast({
                          kind: 'error',
                          title: 'Apply failed',
                          message: applyErrorMessage(e),
                        }),
                    },
                  )
                }
                onReject={(id, comment) =>
                  reject.mutate(
                    { id, reviewer: user.username, comment },
                    {
                      onSuccess: () =>
                        pushToast({ kind: 'info', title: 'Rejected', message: `#${id}` }),
                      onError: (e: unknown) =>
                        pushToast({
                          kind: 'error',
                          title: 'Reject failed',
                          message: e instanceof Error ? e.message : 'Reject failed.',
                        }),
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

interface SegmentedFilterProps<T extends string> {
  value: T;
  options: Array<{ value: T; label: string }>;
  onChange: (v: T) => void;
}

function SegmentedFilter<T extends string>({ value, options, onChange }: SegmentedFilterProps<T>) {
  return (
    <div className="flex items-center rounded-md border border-border bg-bg-elev-1 p-0.5 text-xs">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={cn(
            'rounded-[4px] px-2.5 py-1 text-fg-muted',
            value === o.value && 'bg-bg-elev-2 text-fg',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
