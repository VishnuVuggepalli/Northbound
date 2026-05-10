import { useEffect, useMemo } from 'react';
import { BrowserRouter, Navigate, Outlet, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { TopBar } from '@/components/layout/TopBar';
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
import { useAuthStore } from '@/store/auth';
import { useUIStore } from '@/store/ui';
import { useThemeStore } from '@/store/theme';
import { useHotkeys, useSequenceHotkeys } from '@/hooks/useHotkeys';
import { useCreateRequest, useDevice, usePorts } from '@/api/queries';
import { pushToast } from '@/store/toast';
import { VLANS } from '@/api/client';

function ProtectedShell() {
  const isAuthed = useAuthStore((s) => s.isAuthenticated);
  const location = useLocation();
  if (!isAuthed) return <Navigate to="/login" replace state={{ from: location }} />;
  // The TopBar renders its own <header>; the rest of the page lives in
  // <main> so screen-reader landmark navigation works (axe `landmark-one-main`).
  return (
    <>
      <TopBar />
      <main id="main-content">
        <Outlet />
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
        <Route path="/onboard" element={<OnboardPage />} />
        <Route path="/requests" element={<RequestsPage />} />
        <Route path="/queue" element={<AdminQueuePage />} />
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

  return (
    <>
      <HelpOverlay open={helpOpen} onClose={closeHelp} />
      <RequestModal
        open={requestModal.open}
        port={requestModal.port}
        device={device ?? null}
        theme={theme}
        vlanOptions={VLANS}
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
      <GlobalShortcuts />
      <AppRoutes />
      <GlobalDialogs />
    </BrowserRouter>
  );
}
