import { Link, matchRoutes, useLocation, useParams, type RouteObject } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import { useDevices, useSites } from '@/api/queries';
import type { Environment } from '@/models';

/**
 * Breadcrumbs derived from the matched route hierarchy — a single source of
 * truth, not hand-assembled per page. We're on the component router
 * (`<Routes>`), so the data-router `useMatches()`/`handle.crumb` API isn't
 * available; instead we match the current pathname against a small route→crumb
 * config with `matchRoutes()` (which works with the component router). If the
 * app later adopts `createBrowserRouter`, this config moves to route `handle`s.
 *
 * Dynamic segments resolve their label from the data layer (site name, device
 * name) with a graceful fallback to the raw value while that data loads.
 */

interface CrumbCtx {
  siteName: (slug?: string) => string;
  deviceName: (id?: string) => string;
}

type CrumbFn = (params: Record<string, string | undefined>, ctx: CrumbCtx) => string;

interface CrumbHandle {
  crumb: CrumbFn;
}
interface CrumbRoute {
  path: string;
  handle: CrumbHandle;
  children?: CrumbRoute[];
}

// Mirrors the route tree in App.tsx. Each route carries a `crumb` in `handle`.
// Typed as CrumbRoute (not RouteObject) so the inline crumb fns get typed params.
const CRUMB_ROUTES: CrumbRoute[] = [
  { path: '/requests', handle: { crumb: () => 'Requests' } },
  { path: '/queue', handle: { crumb: () => 'Queue' } },
  { path: '/settings', handle: { crumb: () => 'Settings' } },
  { path: '/onboard', handle: { crumb: () => 'Onboard a device' } },
  { path: '/about', handle: { crumb: () => 'About' } },
  {
    path: '/env/:env',
    handle: { crumb: (p, ctx) => ctx.siteName(p.env) },
    children: [
      { path: 'search', handle: { crumb: () => 'Search' } },
      { path: 'devices/:deviceId', handle: { crumb: (p, ctx) => ctx.deviceName(p.deviceId) } },
    ],
  },
];

interface Crumb {
  label: string;
  to: string;
}

export function Breadcrumbs() {
  const location = useLocation();
  const params = useParams();
  // env-scoped device list so the device crumb resolves to a name, not a UUID.
  const devices = useDevices(params.env as Environment | undefined).data ?? [];
  const sites = useSites().data ?? [];

  const ctx: CrumbCtx = {
    siteName: (slug) => sites.find((s) => s.slug === slug)?.name ?? slug ?? '',
    deviceName: (id) => devices.find((d) => d.id === id)?.name ?? id ?? '',
  };

  const matches = matchRoutes(CRUMB_ROUTES as unknown as RouteObject[], location.pathname) ?? [];
  const trail: Crumb[] = [];
  for (const m of matches) {
    const handle = m.route.handle as CrumbHandle | undefined;
    if (handle?.crumb) trail.push({ label: handle.crumb(m.params, ctx), to: m.pathname });
  }

  // Home (/) and unmatched routes get no bar — a single "Home" crumb adds noise.
  if (trail.length === 0) return null;

  return (
    <nav
      aria-label="Breadcrumb"
      className="flex h-8 shrink-0 items-center border-b border-border bg-bg-elev-1/40 px-4"
    >
      <ol className="flex items-center gap-1 text-xs">
        <li>
          <Link to="/" className="text-fg-muted hover:text-fg">
            Home
          </Link>
        </li>
        {trail.map((c, i) => {
          const last = i === trail.length - 1;
          return (
            <li key={c.to} className="flex items-center gap-1">
              <ChevronRight size={12} className="text-fg-subtle" aria-hidden />
              {last ? (
                <span aria-current="page" className="nb-mono text-fg">
                  {c.label}
                </span>
              ) : (
                <Link to={c.to} className="text-fg-muted hover:text-fg">
                  {c.label}
                </Link>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
