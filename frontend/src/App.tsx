import { useEffect, useMemo } from 'react';
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { TopBar } from '@/components/layout/TopBar';
import { ErrorBoundary } from '@/components/ErrorBoundary';
import { Breadcrumbs } from '@/components/ui/Breadcrumbs';
import { Toaster } from '@/components/ui/Toaster';
import { HelpOverlay } from '@/components/HelpOverlay';
import { RequestModal } from '@/components/RequestModal';
import { LoginPage } from '@/pages/LoginPage';
import { EnvPickerPage } from '@/pages/EnvPickerPage';
import { EnvironmentPage } from '@/pages/EnvironmentPage';
import { EnvironmentTopologyPage } from '@/pages/EnvironmentTopologyPage';
import { DeviceDetailPage } from '@/pages/DeviceDetailPage';
import { RequestsPage } from '@/pages/RequestsPage';
import { AdminQueuePage } from '@/pages/AdminQueuePage';
import { OnboardPage } from '@/pages/OnboardPage';
import { SearchResultsPage } from '@/pages/SearchResultsPage';
import { AboutPage } from '@/pages/About';
import { SettingsPage } from '@/pages/SettingsPage';
import { useAuthStore } from '@/store/auth';
import { useUIStore } from '@/store/ui';
import { useThemeStore } from '@/store/theme';
import { useHotkeys, useSequenceHotkeys } from '@/hooks/useHotkeys';
import { useEventStream } from '@/hooks/useEventStream';
import { useCreateRequest, useDevice, usePorts, useVlans } from '@/api/queries';
import { pushToast } from '@/store/toast';
import { apiClient, isApiError } from '@/api';

/**
 * Validate / refresh the persisted session against `GET /api/users/me` once on
 * mount. A 401 (expired or revoked token) clears the store; the route guard
 * then bounces to /login. Mock client always resolves, so E2E is unaffected.
 */
function useValidateSession(): void {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const setUser = useAuthStore((s) => s.setUser);
  const logout = useAuthStore((s) => s.logout);
  useEffect(() => {
    // The session lives in the httpOnly cookie, not JS — so validate by calling
    // /me (cookie-authed). The request helper silently refreshes once on a 401;
    // a still-401 means the session is truly gone, so clear it.
    if (!isAuthenticated) return;
    let cancelled = false;
    apiClient
      .getCurrentUser()
      .then((user) => {
        if (!cancelled) setUser(user);
      })
      .catch((err) => {
        if (!cancelled && isApiError(err) && err.status === 401) logout();
      });
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated, setUser, logout]);
}

function ProtectedShell() {
  const isAuthed = useAuthStore((s) => s.isAuthenticated);
  const location = useLocation();
  useValidateSession();
  // Live-state push (F157): open the SSE stream while authenticated so device
  // reachability + port changes refresh the UI without polling.
  useEventStream(isAuthed);
  if (!isAuthed) return <Navigate to="/login" replace state={{ from: location }} />;
  // The TopBar renders its own <header>; the rest of the page lives in
  // <main> so screen-reader landmark navigation works (axe `landmark-one-main`).
  return (
    <>
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:bg-bg-elev-2 focus:px-3 focus:py-2 focus:text-sm focus:text-fg focus:shadow-lg focus:outline-none focus:ring-2 focus:ring-accent"
      >
        Skip to content
      </a>
      <TopBar />
      <Breadcrumbs />
      <main id="main-content" tabIndex={-1} className="outline-none">
        {/* Per-route boundary: a single page's crash shows a recoverable
            fallback while the shell/nav stays usable. Keyed by pathname so
            navigating to another route clears a stuck error. */}
        <ErrorBoundary key={location.pathname}>
          <Outlet />
        </ErrorBoundary>
      </main>
    </>
  );
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<ProtectedShell />}>
        <Route path="/" element={<EnvPickerPage />} />
        <Route path="/about" element={<AboutPage />} />
        <Route path="/onboard" element={<OnboardPage />} />
        <Route path="/requests" element={<RequestsPage />} />
        <Route path="/queue" element={<AdminQueuePage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/env/:env" element={<EnvironmentPage />}>
          <Route index element={<EnvironmentTopologyPage />} />
          <Route path="search" element={<SearchResultsPage />} />
          <Route path="devices/:deviceId" element={<DeviceDetailPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}

function GlobalShortcuts() {
  const navigate = useNavigate();
  const closeOverlays = useUIStore((s) => s.closeOverlays);
  const openHelp = useUIStore((s) => s.openHelp);
  const helpOpen = useUIStore((s) => s.helpOpen);
  const requestModalOpen = useUIStore((s) => s.requestModal.open);
  const closeRequest = useUIStore((s) => s.closeRequest);
  const selectedPortName = useUIStore((s) => s.selectedPortName);
  const selectedDeviceId = useUIStore((s) => s.selectedDeviceId);
  const selectPort = useUIStore((s) => s.selectPort);
  const setEnv = useUIStore((s) => s.setEnv);
  const openRequest = useUIStore((s) => s.openRequest);
  const userRole = useAuthStore((s) => s.user?.role);

  const { data: portSnapshot } = usePorts(selectedDeviceId);
  const ports = useMemo(() => portSnapshot?.ports ?? [], [portSnapshot]);
  const selectedPort = ports.find((p) => p.name === selectedPortName) ?? null;

  useHotkeys({
    '/': () => {
      const el = document.querySelector<HTMLInputElement>('.nb-search-input');
      el?.focus();
    },
    '?': () => openHelp(),
    escape: () => {
      if (helpOpen) {
        closeOverlays();
        return;
      }
      if (requestModalOpen) {
        closeRequest();
        return;
      }
      if (selectedPortName) {
        selectPort(null);
        return;
      }
      return false;
    },
    j: () => {
      if (!ports.length) return;
      const idx = ports.findIndex((p) => p.name === selectedPortName);
      const next = idx === -1 ? 0 : (idx + 1) % ports.length;
      selectPort(ports[next]!.name);
    },
    k: () => {
      if (!ports.length) return;
      const idx = ports.findIndex((p) => p.name === selectedPortName);
      const next = idx === -1 ? ports.length - 1 : (idx - 1 + ports.length) % ports.length;
      selectPort(ports[next]!.name);
    },
    r: () => {
      if (selectedPort) openRequest(selectedPort);
    },
  });

  useSequenceHotkeys({
    'g l': () => {
      setEnv('lab');
      navigate('/env/lab');
    },
    'g d': () => {
      setEnv('dc');
      navigate('/env/dc');
    },
    'g h': () => navigate('/'),
    'g r': () => navigate('/requests'),
    'g q': () => {
      if (userRole === 'admin') navigate('/queue');
    },
  });

  // Close overlays on route change
  const location = useLocation();
  useEffect(() => {
    closeOverlays();
    // Don't depend on closeOverlays — it's stable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname]);

  // Close overlays don't depend on env/path used here.
  return null;
}

function GlobalDialogs() {
  const helpOpen = useUIStore((s) => s.helpOpen);
  const closeHelp = useUIStore((s) => s.closeHelp);
  const requestModal = useUIStore((s) => s.requestModal);
  const closeRequest = useUIStore((s) => s.closeRequest);
  const theme = useThemeStore((s) => s.theme);
  const selectedDeviceId = useUIStore((s) => s.selectedDeviceId);
  const user = useAuthStore((s) => s.user);
  const createReq = useCreateRequest();
  const { data: device } = useDevice(selectedDeviceId);
  const { data: portSnapshot } = usePorts(selectedDeviceId);
  const { data: vlans = [] } = useVlans(selectedDeviceId);

  // VLAN quick-pick suggestions from REAL data — the device's full VLAN database
  // (so any defined VLAN is pickable, not only ones already on a port), unioned
  // with VLANs observed on this device's ports. Sorted unique. The modal's
  // numeric input still allows any 1–4094.
  const vlanOptions = useMemo(() => {
    const seen = new Set<number>();
    for (const v of vlans) seen.add(v.vlan_id);
    for (const p of portSnapshot?.ports ?? []) {
      if (typeof p.untagged_vlan === 'number') seen.add(p.untagged_vlan);
      for (const v of p.tagged_vlans ?? []) seen.add(v);
    }
    return [...seen].sort((a, b) => a - b);
  }, [vlans, portSnapshot]);

  return (
    <>
      <HelpOverlay open={helpOpen} onClose={closeHelp} />
      <RequestModal
        open={requestModal.open}
        port={requestModal.port}
        device={device ?? null}
        theme={theme}
        vlanOptions={vlanOptions}
        onClose={closeRequest}
        submitting={createReq.isPending}
        onSubmit={({ changes, reason }) => {
          if (!device || !requestModal.port || !user) return;
          createReq.mutate(
            {
              device_id: device.id,
              port_name: requestModal.port.name,
              requested_by: user.username,
              requested_changes: changes,
              reason,
            },
            {
              onSuccess: (req) => {
                pushToast({
                  kind: 'success',
                  title: 'Request submitted',
                  message: `#${req.id} on ${device.name}/${req.port_name}`,
                });
                closeRequest();
              },
              onError: (err) =>
                pushToast({
                  kind: 'error',
                  title: 'Submit failed',
                  message: err instanceof Error ? err.message : 'Unknown error',
                }),
            },
          );
        }}
      />
      <Toaster />
    </>
  );
}

export function App() {
  return (
    <BrowserRouter>
      {/* App-root boundary: a catastrophic shell crash falls back to a full
          reload rather than a blank white screen. */}
      <ErrorBoundary fullReload title="Northbound hit an unexpected error.">
        <GlobalShortcuts />
        <AppRoutes />
        <GlobalDialogs />
      </ErrorBoundary>
    </BrowserRouter>
  );
}
