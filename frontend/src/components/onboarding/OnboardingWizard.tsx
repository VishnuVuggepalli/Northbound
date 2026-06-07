import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  Loader2,
  ShieldAlert,
} from 'lucide-react';
import { Button } from '@/shared/Button';
import { Input, Textarea } from '@/shared/Input';
import { Badge } from '@/shared/Badge';
import { PlatformIcon } from '@/shared/PlatformIcon';
import { cn } from '@/lib/cn';
import {
  usePlatforms,
  useTestConnection,
  useDiscoverDevice,
  useConfirmOnboard,
  useSites,
  useCreateSite,
} from '@/api/queries';
import { useAuthStore } from '@/store/auth';
import { pushToast } from '@/store/toast';
import { isApiError } from '@/api';
import type {
  AuthMethod,
  DeviceRole,
  Environment,
  OnboardingDraft,
  PlatformId,
  PlatformRegistryEntry,
} from '@/models';

type StepId = 1 | 2 | 3 | 4 | 5 | 6 | 7;

const STEPS: Array<{ id: StepId; title: string; subtitle: string }> = [
  { id: 1, title: 'Platform', subtitle: 'Pick the driver from the registry.' },
  { id: 2, title: 'Identity', subtitle: 'Name, environment, role.' },
  { id: 3, title: 'Connection', subtitle: 'Management IP and port.' },
  { id: 4, title: 'Credentials', subtitle: 'How we authenticate.' },
  { id: 5, title: 'Test', subtitle: 'Live probe — reachable, auth ok.' },
  { id: 6, title: 'Discover', subtitle: 'Pull port list and a config snippet.' },
  { id: 7, title: 'Confirm', subtitle: 'Atomic save: device + ports + baseline backup.' },
];

const initialDraft: OnboardingDraft = {
  platform_id: null,
  platform: null,
  name: '',
  env: 'lab',
  role: 'leaf',
  mgmt_ip: '',
  port: 443,
  prefer_native_api: true,
  auth_method: 'password',
  username: '',
  password: '',
  ssh_key: '',
  api_token: '',
  snmp_community: 'public',
};

const AUTH_LABELS: Record<AuthMethod, string> = {
  password: 'Password',
  ssh_key: 'SSH key',
  api_token: 'API token',
  snmp_v2c_community: 'SNMP v2c',
  snmp_v3: 'SNMP v3',
};

export function OnboardingWizard() {
  const navigate = useNavigate();
  const [step, setStep] = useState<StepId>(1);
  const [draft, setDraft] = useState<OnboardingDraft>(initialDraft);
  const { data: platforms = [] } = usePlatforms();
  const test = useTestConnection();
  const discover = useDiscoverDevice();
  const confirm = useConfirmOnboard();

  const selectedPlatform =
    draft.platform_id ? platforms.find((p) => p.platform_id === draft.platform_id) : undefined;

  const update = (patch: Partial<OnboardingDraft>) => setDraft((d) => ({ ...d, ...patch }));

  const canProceed = (): boolean => {
    switch (step) {
      case 1:
        return !!draft.platform_id;
      case 2:
        return !!draft.name && !!draft.env && !!draft.role;
      case 3:
        return /^\d{1,3}(\.\d{1,3}){3}$/.test(draft.mgmt_ip) && draft.port > 0;
      case 4: {
        // Username is only required when the auth method actually uses one.
        // SNMP v2c uses a community string, no username.
        const usesUsername =
          draft.auth_method === 'password' ||
          draft.auth_method === 'ssh_key' ||
          draft.auth_method === 'snmp_v3';
        if (usesUsername && !draft.username) return false;
        if (draft.auth_method === 'password') return !!draft.password;
        if (draft.auth_method === 'ssh_key') return !!draft.ssh_key;
        if (draft.auth_method === 'api_token') return !!draft.api_token;
        if (draft.auth_method === 'snmp_v2c_community') return !!draft.snmp_community;
        if (draft.auth_method === 'snmp_v3') return !!draft.password;
        return false;
      }
      case 5:
        return test.isSuccess;
      case 6:
        return discover.isSuccess;
      default:
        return true;
    }
  };

  const handleNext = async () => {
    if (step === 5 && !test.data) {
      const result = await test.mutateAsync(draft);
      if (!result.ok) {
        pushToast({ kind: 'error', title: 'Connection failed', message: result.message });
        return;
      }
    }
    if (step === 6 && !discover.data) {
      await discover.mutateAsync(draft);
    }
    setStep((s) => (s >= 7 ? 7 : ((s + 1) as StepId)));
  };

  const handleConfirm = async () => {
    try {
      const result = await confirm.mutateAsync(draft);
      pushToast({
        kind: 'success',
        title: 'Device onboarded',
        message: `${result.device.name} · ${result.ports_seeded} ports seeded`,
      });
      navigate(`/env/${result.device.env}/devices/${result.device.id}`);
    } catch (e) {
      pushToast({
        kind: 'error',
        title: 'Onboarding failed',
        message: e instanceof Error ? e.message : 'Unknown error',
      });
    }
  };

  return (
    <div className="mx-auto flex h-full max-w-3xl flex-col gap-6 px-6 py-8">
      <header>
        <div className="text-xs uppercase tracking-wider text-fg-subtle">Onboarding</div>
        <h1 className="text-2xl font-semibold tracking-tight text-fg">Add a device</h1>
        <p className="mt-1 text-sm text-fg-muted">
          Stateless probes (steps 1–6) followed by an atomic save in step 7. If anything fails
          mid-way we leave no trace.
        </p>
      </header>

      <Stepper steps={STEPS} current={step} />

      <div className="nb-card flex-1 p-6">
        {step === 1 && (
          <Step1Platform
            platforms={platforms}
            selected={draft.platform_id}
            onPick={(p) =>
              update({
                platform_id: p.platform_id,
                platform: p.platform,
                port: p.defaultPort,
                // Reset auth_method to a value valid for the new platform so the
                // segmented control doesn't render an option the driver rejects.
                auth_method: (p.capabilities.auth_methods[0] ?? 'password') as AuthMethod,
              })
            }
          />
        )}
        {step === 2 && <Step2Identity draft={draft} update={update} />}
        {step === 3 && <Step3Connection draft={draft} update={update} />}
        {step === 4 && (
          <Step4Credentials draft={draft} update={update} platform={selectedPlatform} />
        )}
        {step === 5 && (
          <Step5Test
            run={() => test.mutateAsync(draft)}
            data={test.data}
            isPending={test.isPending}
            isError={test.isError}
          />
        )}
        {step === 6 && (
          <Step6Discover
            run={() => discover.mutateAsync(draft)}
            data={discover.data}
            isPending={discover.isPending}
          />
        )}
        {step === 7 && (
          <Step7Confirm draft={draft} platform={selectedPlatform} discoverData={discover.data} />
        )}
      </div>

      <footer className="flex items-center justify-between gap-2">
        <Button
          kind="ghost"
          leftIcon={<ArrowLeft size={14} />}
          onClick={() =>
            step === 1 ? navigate(-1) : setStep((s) => (s <= 1 ? 1 : ((s - 1) as StepId)))
          }
        >
          {step === 1 ? 'Cancel' : 'Back'}
        </Button>
        {step < 7 ? (
          <Button
            kind="primary"
            rightIcon={<ArrowRight size={14} />}
            onClick={handleNext}
            disabled={!canProceed() || test.isPending || discover.isPending}
          >
            Continue
          </Button>
        ) : (
          <Button
            kind="success"
            leftIcon={<Check size={14} />}
            onClick={handleConfirm}
            disabled={confirm.isPending}
          >
            {confirm.isPending ? 'Saving…' : 'Confirm and save'}
          </Button>
        )}
      </footer>
    </div>
  );
}

/* -------------------------------------------------------------------------
 * Stepper
 * ------------------------------------------------------------------------- */

interface StepperProps {
  steps: typeof STEPS;
  current: StepId;
}

function Stepper({ steps, current }: StepperProps) {
  return (
    <ol className="grid grid-cols-7 gap-2">
      {steps.map((s) => {
        const done = current > s.id;
        const active = current === s.id;
        return (
          <li
            key={s.id}
            className={cn(
              'rounded-md border px-2.5 py-2 text-[11px]',
              active && 'border-accent bg-accent-soft',
              done && 'border-success/40 bg-success/10 text-success',
              !active && !done && 'border-border bg-bg-elev-1 text-fg-muted',
            )}
          >
            <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider">
              <span>{s.id}</span>
              {done && <Check size={10} />}
            </div>
            <div className="mt-0.5 truncate text-fg">{s.title}</div>
          </li>
        );
      })}
    </ol>
  );
}

/* -------------------------------------------------------------------------
 * Steps
 * ------------------------------------------------------------------------- */

interface Step1Props {
  platforms: readonly PlatformRegistryEntry[];
  selected: PlatformId | null;
  onPick: (p: PlatformRegistryEntry) => void;
}

function Step1Platform({ platforms, selected, onPick }: Step1Props) {
  return (
    <div className="space-y-3">
      <p className="text-sm text-fg-muted">
        Drivers are plugins; devices are runtime data. Pick a driver — capabilities below dictate
        what writes the wizard later allows.
      </p>
      <div className="grid grid-cols-2 gap-3">
        {platforms.map((p) => (
          <button
            key={p.platform_id}
            type="button"
            onClick={() => onPick(p)}
            className={cn(
              'flex items-start gap-3 rounded-lg border p-4 text-left transition-colors',
              selected === p.platform_id
                ? 'border-accent bg-accent-soft'
                : 'border-border bg-bg-elev-1 hover:border-border-strong',
            )}
          >
            <PlatformIcon platform={p.platform} role="leaf" />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <div className="font-semibold text-fg">{p.display_name}</div>
                {!p.capabilities.writable && (
                  <Badge variant="warn" title="Read-only forever">
                    <ShieldAlert size={10} className="mr-1" />
                    R/O
                  </Badge>
                )}
                {p.capabilities.supports_commit_confirm && (
                  <Badge variant="success">commit-confirm</Badge>
                )}
              </div>
              <p className="mt-1 text-xs text-fg-muted">{p.description}</p>
              <div className="mt-2 text-[10px] uppercase tracking-wider text-fg-subtle">
                Auth: {p.capabilities.auth_methods.map((m) => AUTH_LABELS[m]).join(' · ')}
              </div>
              {p.notes && (
                <p className="mt-1 text-[11px] italic text-fg-muted">{p.notes}</p>
              )}
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

interface UpdateFn {
  (patch: Partial<OnboardingDraft>): void;
}

function Step2Identity({ draft, update }: { draft: OnboardingDraft; update: UpdateFn }) {
  const { data: sites = [] } = useSites();
  const isAdmin = useAuthStore((s) => s.user?.role) === 'admin';
  const createSite = useCreateSite();
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState('');

  // Derive a URL-safe slug from the display name (e.g. "Edge DR" -> "edge-dr").
  const slugify = (s: string) =>
    s
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '');

  const handleCreateSite = async () => {
    const name = newName.trim();
    const slug = slugify(name);
    if (!slug) {
      pushToast({ kind: 'error', message: 'Enter a site name first.' });
      return;
    }
    try {
      const site = await createSite.mutateAsync({ slug, name });
      update({ env: site.slug });
      setNewName('');
      setAdding(false);
      pushToast({ kind: 'success', message: `Site "${site.name}" created.` });
    } catch (err: unknown) {
      pushToast({
        kind: 'error',
        message: isApiError(err) ? err.message : 'Could not create site.',
      });
    }
  };

  return (
    <div className="space-y-4">
      <Field label="Device name">
        <Input
          value={draft.name}
          onChange={(e) => update({ name: e.target.value })}
          placeholder="lab-leaf-4"
        />
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Site">
          <div className="space-y-2">
            <Segmented<Environment>
              value={draft.env}
              options={sites.map((s) => ({ value: s.slug, label: s.name }))}
              onChange={(v) => update({ env: v })}
            />
            {isAdmin && !adding && (
              <button
                type="button"
                onClick={() => setAdding(true)}
                className="text-xs text-accent hover:underline"
              >
                + New site
              </button>
            )}
            {isAdmin && adding && (
              <div className="flex items-center gap-2">
                <Input
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="Site name (e.g. Edge DR)"
                  aria-label="New site name"
                />
                <Button
                  type="button"
                  size="sm"
                  onClick={() => void handleCreateSite()}
                  disabled={createSite.isPending}
                >
                  Add
                </Button>
                <button
                  type="button"
                  onClick={() => {
                    setAdding(false);
                    setNewName('');
                  }}
                  className="text-xs text-fg-subtle hover:text-fg"
                >
                  Cancel
                </button>
              </div>
            )}
          </div>
        </Field>
        <Field label="Role">
          <Segmented<DeviceRole>
            value={draft.role}
            options={[
              { value: 'leaf', label: 'Leaf' },
              { value: 'spine', label: 'Spine' },
              { value: 'router', label: 'Router' },
              { value: 'vpn', label: 'VPN' },
            ]}
            onChange={(v) => update({ role: v })}
          />
        </Field>
      </div>
      {(draft.role === 'router' || draft.role === 'vpn') && (
        <div className="rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-xs text-warn">
          <strong>Read-only forever.</strong> Routers and VPN devices are write-locked at four
          layers (driver, API, DB, UI). No admin override.
        </div>
      )}
    </div>
  );
}

function Step3Connection({ draft, update }: { draft: OnboardingDraft; update: UpdateFn }) {
  const ipDirty = draft.mgmt_ip.length > 0;
  const ipValid = /^\d{1,3}(\.\d{1,3}){3}$/.test(draft.mgmt_ip);
  const portValid = draft.port > 0 && draft.port < 65536;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-[1fr_120px] gap-3">
        <Field label="Management IP">
          <Input
            value={draft.mgmt_ip}
            onChange={(e) => update({ mgmt_ip: e.target.value })}
            placeholder="10.10.0.14"
            className="nb-mono"
            aria-invalid={ipDirty && !ipValid}
            aria-describedby={ipDirty && !ipValid ? 'onboard-ip-error' : undefined}
            autoComplete="off"
            inputMode="decimal"
          />
          {ipDirty && !ipValid && (
            <span id="onboard-ip-error" role="alert" className="mt-1 block text-xs text-danger">
              Use dotted-quad format (e.g. 10.10.0.14).
            </span>
          )}
        </Field>
        <Field label="Port">
          <Input
            type="number"
            min={1}
            max={65535}
            value={draft.port}
            onChange={(e) => update({ port: parseInt(e.target.value) || 0 })}
            className="nb-mono"
            aria-invalid={!portValid}
          />
        </Field>
      </div>
      <label className="flex cursor-pointer items-center gap-2 rounded-md border border-border bg-bg-elev-1 p-3 text-sm">
        <input
          type="checkbox"
          checked={draft.prefer_native_api}
          onChange={(e) => update({ prefer_native_api: e.target.checked })}
          className="h-4 w-4 accent-[oklch(0.70_0.13_220)]"
        />
        <span className="flex-1">
          <span className="font-medium text-fg">Prefer native API</span>
          <span className="ml-2 text-xs text-fg-muted">
            REST / eAPI / NETCONF when available, SSH fallback otherwise.
          </span>
        </span>
      </label>
    </div>
  );
}

interface Step4Props {
  draft: OnboardingDraft;
  update: UpdateFn;
  platform?: PlatformRegistryEntry;
}

function Step4Credentials({ draft, update, platform }: Step4Props) {
  const allowed: AuthMethod[] = platform?.capabilities.auth_methods ?? ['password'];
  // SNMP v2c uses a community string instead of a username/password. We hide
  // the username field for it so the form mirrors how SwOS actually authenticates.
  const showUsername =
    draft.auth_method === 'password' ||
    draft.auth_method === 'ssh_key' ||
    draft.auth_method === 'snmp_v3';
  return (
    <div className="space-y-4">
      {allowed.length > 1 && (
        <Field label="Auth method">
          <Segmented<AuthMethod>
            value={draft.auth_method}
            options={allowed.map((m) => ({ value: m, label: AUTH_LABELS[m] }))}
            onChange={(v) => update({ auth_method: v })}
          />
        </Field>
      )}
      {allowed.length === 1 && (
        <div className="rounded-md border border-border bg-bg-elev-1 px-3 py-2 text-xs text-fg-muted">
          This driver only supports <strong className="text-fg">{AUTH_LABELS[allowed[0]!]}</strong>.
        </div>
      )}
      {showUsername && (
        <Field label="Username">
          <Input
            value={draft.username}
            onChange={(e) => update({ username: e.target.value })}
            placeholder="admin"
            className="nb-mono"
            data-testid="onboard-username"
          />
        </Field>
      )}
      {draft.auth_method === 'password' && (
        <Field label="Password">
          <Input
            type="password"
            value={draft.password}
            onChange={(e) => update({ password: e.target.value })}
            data-testid="onboard-password"
          />
        </Field>
      )}
      {draft.auth_method === 'ssh_key' && (
        <Field label="SSH private key">
          <Textarea
            rows={5}
            value={draft.ssh_key}
            onChange={(e) => update({ ssh_key: e.target.value })}
            placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
            className="nb-mono text-[11px]"
            data-testid="onboard-ssh-key"
          />
        </Field>
      )}
      {draft.auth_method === 'api_token' && (
        <Field label="API token">
          <Input
            type="password"
            value={draft.api_token}
            onChange={(e) => update({ api_token: e.target.value })}
            className="nb-mono"
            data-testid="onboard-api-token"
          />
        </Field>
      )}
      {draft.auth_method === 'snmp_v2c_community' && (
        <Field label="SNMP community">
          <Input
            type="password"
            value={draft.snmp_community}
            onChange={(e) => update({ snmp_community: e.target.value })}
            placeholder="public"
            className="nb-mono"
            data-testid="onboard-snmp-community"
            aria-describedby="snmp-help"
          />
          <span id="snmp-help" className="mt-1 block text-[11px] text-fg-muted">
            Treated as a secret — masked here and never logged.
          </span>
        </Field>
      )}
      {draft.auth_method === 'snmp_v3' && (
        <Field label="SNMP v3 auth passphrase">
          <Input
            type="password"
            value={draft.password}
            onChange={(e) => update({ password: e.target.value })}
            className="nb-mono"
            data-testid="onboard-snmp-v3-pass"
          />
        </Field>
      )}
      <div className="rounded-md border border-border bg-bg-elev-1 px-3 py-2 text-xs text-fg-muted">
        Stored encrypted via the CredVault interface (Fernet for v1, KMS-swappable). Never
        appears in logs or audit JSON.
      </div>
    </div>
  );
}

interface Step5Props {
  run: () => Promise<unknown>;
  data: { ok: boolean; latency_ms: number; message: string } | undefined;
  isPending: boolean;
  isError: boolean;
}

function Step5Test({ run, data, isPending, isError }: Step5Props) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-fg-muted">
        We probe the device once — TCP reach, then auth. No data is stored yet.
      </p>
      <div className="flex items-center gap-3 rounded-md border border-border bg-bg-elev-1 p-4">
        {isPending ? (
          <Loader2 className="animate-spin text-accent" size={20} />
        ) : data?.ok ? (
          <CheckCircle2 className="text-success" size={22} />
        ) : isError ? (
          <ShieldAlert className="text-danger" size={22} />
        ) : (
          <span className="h-5 w-5 rounded-full border border-border" />
        )}
        <div className="flex-1 text-sm">
          {isPending && 'Probing…'}
          {data?.ok && (
            <>
              <span className="font-medium text-fg">Connection OK</span>{' '}
              <span className="text-fg-muted">· {data.message} · {data.latency_ms} ms</span>
            </>
          )}
          {!isPending && !data && 'Click Run to start the probe.'}
        </div>
        <Button kind="ghost" size="sm" onClick={() => void run()} disabled={isPending}>
          {data ? 'Retest' : 'Run'}
        </Button>
      </div>
    </div>
  );
}

interface Step6Props {
  run: () => Promise<unknown>;
  data: { port_count: number; sample_ports: string[]; config_excerpt: string } | undefined;
  isPending: boolean;
}

function Step6Discover({ run, data, isPending }: Step6Props) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-fg-muted">
        Pull the live port inventory and a config snippet. Nothing is committed yet.
      </p>
      {!data && !isPending && (
        <Button kind="primary" onClick={() => void run()}>
          Run discovery
        </Button>
      )}
      {isPending && (
        <div className="flex items-center gap-2 text-sm text-fg-muted">
          <Loader2 className="animate-spin" size={16} /> Discovering…
        </div>
      )}
      {data && (
        <div className="space-y-3">
          <div className="grid grid-cols-3 gap-3">
            <Stat label="Ports found" value={data.port_count} />
            <Stat label="Sample" value={data.sample_ports[0] ?? '—'} mono />
            <Stat label="Status" value="OK" />
          </div>
          <div>
            <div className="mb-1 text-[10px] uppercase tracking-wider text-fg-subtle">
              Config excerpt
            </div>
            <pre className="nb-mono overflow-x-auto rounded-md border border-border bg-bg-elev-1 p-3 text-[11px]">
              <code>{data.config_excerpt}</code>
            </pre>
          </div>
        </div>
      )}
    </div>
  );
}

interface Step7Props {
  draft: OnboardingDraft;
  platform?: PlatformRegistryEntry;
  discoverData: { port_count: number } | undefined;
}

function Step7Confirm({ draft, platform, discoverData }: Step7Props) {
  return (
    <div className="space-y-4">
      <p className="text-sm text-fg-muted">
        On confirm, we run a single transaction: insert device, port_metadata for each port, an
        initial config_backup, and the audit entry. If any step fails we roll back — no half-state.
      </p>
      <div className="space-y-1.5 rounded-md border border-border bg-bg-elev-1 p-4 text-sm">
        <Row k="Platform" v={platform?.display_name ?? draft.platform_id ?? '—'} />
        <Row k="Name" v={draft.name} mono />
        <Row k="Environment" v={draft.env.toUpperCase()} />
        <Row k="Role" v={draft.role} />
        <Row k="Management IP" v={`${draft.mgmt_ip}:${draft.port}`} mono />
        <Row k="Native API" v={draft.prefer_native_api ? 'preferred' : 'off'} />
        <Row
          k="Auth"
          v={
            draft.auth_method === 'snmp_v2c_community'
              ? `SNMP v2c community`
              : `${draft.username} · ${AUTH_LABELS[draft.auth_method]}`
          }
        />
        <Row k="Discovered ports" v={discoverData?.port_count ?? '—'} />
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------
 * Small helpers
 * ------------------------------------------------------------------------- */

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[11px] font-medium uppercase tracking-wider text-fg-subtle">
        {label}
      </span>
      {children}
    </label>
  );
}

interface SegmentedOption<T extends string> {
  value: T;
  label: string;
}

function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: Array<SegmentedOption<T>>;
  onChange: (v: T) => void;
}) {
  return (
    <div className="flex h-9 items-center rounded-md border border-border bg-bg-elev-1 p-0.5 text-xs">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={cn(
            'flex-1 rounded-[4px] px-2 py-1.5 text-fg-muted transition-colors',
            value === o.value && 'bg-bg-elev-2 text-fg shadow-sm',
            value !== o.value && 'hover:text-fg',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function Stat({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="rounded-md border border-border bg-bg-elev-1 p-3">
      <div className="text-[10px] uppercase tracking-wider text-fg-subtle">{label}</div>
      <div className={cn('mt-0.5 text-base font-semibold text-fg', mono && 'nb-mono')}>
        {value}
      </div>
    </div>
  );
}

function Row({ k, v, mono }: { k: string; v: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-xs uppercase tracking-wider text-fg-subtle">{k}</span>
      <span className={cn('text-fg', mono && 'nb-mono text-xs')}>{v}</span>
    </div>
  );
}
