import { useNavigate, useParams } from 'react-router-dom';
import { Topology3D } from '@/components/three/Topology3D';
import { NocRibbon } from '@/components/layout/NocRibbon';
import { useAllPorts, useDevices, useLinks, useRequests } from '@/api/queries';
import { useThemeStore } from '@/store/theme';
import type { Environment } from '@/types';

export function EnvironmentTopologyPage() {
  const navigate = useNavigate();
  const { env } = useParams<{ env: Environment }>();
  const theme = useThemeStore((s) => s.theme);
  const { data: devices = [] } = useDevices(env);
  const { data: ports = {} } = useAllPorts();
  const { data: links = [] } = useLinks(env);
  const { data: requests = [] } = useRequests();

  if (env !== 'lab' && env !== 'dc') return null;

  return (
    <div className="flex h-full flex-col">
      <NocRibbon env={env} devices={devices} ports={ports} requests={requests} />
      <div className="flex items-center justify-between border-b border-border bg-bg-elev-1/40 px-6 py-3">
        <div>
          <div className="text-xs uppercase tracking-wider text-fg-subtle">
            {env === 'lab' ? 'Lab environment' : 'Datacenter'} · live topology
          </div>
          <h1 className="text-lg font-semibold text-fg">
            {devices.length} devices · {devices.reduce((a, d) => a + d.portCount, 0)} ports
          </h1>
        </div>
        <span className="nb-mono text-xs text-fg-muted">click a device to inspect</span>
      </div>
      <div className="flex-1 p-4">
        <Topology3D
          devices={devices}
          links={links}
          theme={theme}
          onPickDevice={(d) => navigate(`/env/${env}/devices/${d.id}`)}
        />
      </div>
    </div>
  );
}
