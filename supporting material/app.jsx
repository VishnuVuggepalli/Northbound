// Northbound — root app: state, routing, ties everything together

const { useState: useSA, useEffect: useEA, useMemo: useMA, useCallback: useCA, useRef: useRA } = React;
const { TWEAK_DEFAULTS } = window;

function useReqState(initial) {
  const [list, setList] = useSA(initial);
  return [list, setList];
}

// NOC live-state ribbon — mono one-liner of environment health
function NocRibbon({ env, devices, ports, requests }) {
  const stats = useMA(() => {
    let up = 0, down = 0, dis = 0, total = 0;
    for (const d of devices) {
      const arr = ports[d.id] || [];
      for (const p of arr) {
        total++;
        if (p.state === 'up') up++;
        else if (p.state === 'disabled') dis++;
        else down++;
      }
    }
    const pending = requests.filter(r => r.status === 'pending' && devices.some(d => d.id === r.device_id)).length;
    return { up, down, dis, total, pending };
  }, [devices, ports, requests]);
  const [now, setNow] = useSA(new Date());
  useEA(() => {
    const t = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(t);
  }, []);
  const hh = String(now.getUTCHours()).padStart(2, '0');
  const mm = String(now.getUTCMinutes()).padStart(2, '0');
  const ss = String(now.getUTCSeconds()).padStart(2, '0');
  return (
    <div className="nb-nocribbon">
      <span className="nb-nocribbon__cell">
        <span className="nb-nocribbon__pulse" />
        <span className="nb-nocribbon__tag">{env.toUpperCase()}</span>
      </span>
      <span className="nb-nocribbon__cell">
        <span className="nb-nocribbon__lbl">dev</span>
        <span className="nb-nocribbon__num">{devices.length}</span>
      </span>
      <span className="nb-nocribbon__cell">
        <span className="nb-nocribbon__lbl">ports</span>
        <span className="nb-nocribbon__num">{stats.total}</span>
      </span>
      <span className="nb-nocribbon__cell">
        <span className="nb-nocribbon__lbl">up</span>
        <span className="nb-nocribbon__num nb-nocribbon__num--up">↑{stats.up}</span>
      </span>
      <span className="nb-nocribbon__cell">
        <span className="nb-nocribbon__lbl">down</span>
        <span className="nb-nocribbon__num nb-nocribbon__num--down">↓{stats.down}</span>
      </span>
      <span className="nb-nocribbon__cell">
        <span className="nb-nocribbon__lbl">dis</span>
        <span className="nb-nocribbon__num nb-nocribbon__num--warn">◌{stats.dis}</span>
      </span>
      {stats.pending > 0 && (
        <span className="nb-nocribbon__cell">
          <span className="nb-nocribbon__lbl">pending</span>
          <span className="nb-nocribbon__num nb-nocribbon__num--warn">{stats.pending}</span>
        </span>
      )}
      <span className="nb-nocribbon__cell" style={{ marginLeft: 'auto' }}>
        <span className="nb-nocribbon__lbl">utc</span>
        <span className="nb-nocribbon__time">{hh}:{mm}:{ss}</span>
      </span>
    </div>
  );
}

function App() {
  const { theme } = useTheme();
  const toast = useToast();

  // Mock data, mutable in-session so apply/approve/etc actually flip state.
  const [requests, setRequests] = useReqState(NB_DATA.CHANGE_REQUESTS);
  const [ports, setPorts] = useSA(NB_DATA.PORTS);
  const audit = NB_DATA.AUDIT;

  // Auth + role
  const [user, setUser] = useSA(NB_DATA.USERS[0]);
  const roles = NB_DATA.USERS;

  // Routing — light client-side
  const [route, setRoute] = useSA({ name: 'envpicker' }); // login | envpicker | env | myreq | queue | help
  const [env, setEnv] = useSA('lab');
  const [selectedDeviceId, setSelectedDeviceId] = useSA(null);
  const [selectedPort, setSelectedPort] = useSA(null);
  const [openTab, setOpenTab] = useSA('ports');
  const [search, setSearch] = useSA('');
  const [helpOpen, setHelpOpen] = useSA(false);
  const [reqModal, setReqModal] = useSA({ open: false, port: null });
  const [sidebarW, setSidebarW] = useSA(280);

  const devices = NB_DATA.DEVICES;
  const envDevices = useMA(() => devices.filter(d => d.env === env), [devices, env]);
  const selectedDevice = useMA(() => devices.find(d => d.id === selectedDeviceId), [devices, selectedDeviceId]);
  const selectedDevicePorts = useMA(() => selectedDevice ? ports[selectedDevice.id] : [], [ports, selectedDevice]);
  const selectedPortObj = useMA(() => selectedDevicePorts?.find(p => p.name === selectedPort), [selectedDevicePorts, selectedPort]);

  const lastBackupFor = useCA((id) => Date.now() - 1000 * 60 * 60 * 4, []);

  // Hotkeys
  useHotkeys({
    '/': () => { document.querySelector('.nb-search input')?.focus(); },
    '?': () => setHelpOpen(true),
    'escape': () => {
      if (helpOpen) { setHelpOpen(false); return; }
      if (reqModal.open) { setReqModal({ open: false, port: null }); return; }
      if (selectedPort) { setSelectedPort(null); return; }
      return false;
    },
    'j': () => moveSelection(+1),
    'k': () => moveSelection(-1),
    'r': () => {
      if (selectedPortObj) setReqModal({ open: true, port: selectedPortObj });
    },
  }, [helpOpen, reqModal.open, selectedPort, selectedPortObj]);

  useSequenceHotkeys({
    'g l': () => { setEnv('lab'); setRoute({ name: 'env' }); },
    'g d': () => { setEnv('dc'); setRoute({ name: 'env' }); },
    'g q': () => { if (user.role === 'admin') setRoute({ name: 'queue' }); },
    'g r': () => setRoute({ name: 'myreq' }),
    'g h': () => setRoute({ name: 'envpicker' }),
  }, [user.role]);

  function moveSelection(delta) {
    if (!selectedDevice || !selectedDevicePorts.length) return;
    const idx = selectedDevicePorts.findIndex(p => p.name === selectedPort);
    const next = (idx === -1 ? 0 : (idx + delta + selectedDevicePorts.length) % selectedDevicePorts.length);
    setSelectedPort(selectedDevicePorts[next].name);
  }

  // Tweak protocol — palette + role
  const { palette, setPalette, palettes } = useTheme();
  const [tweaksOpen, setTweaksOpen] = useSA(false);
  useEA(() => {
    const onMsg = (e) => {
      const d = e.data;
      if (d?.type === '__activate_edit_mode') setTweaksOpen(true);
      if (d?.type === '__deactivate_edit_mode') setTweaksOpen(false);
    };
    window.addEventListener('message', onMsg);
    window.parent.postMessage({ type: '__edit_mode_available' }, '*');
    return () => window.removeEventListener('message', onMsg);
  }, []);
  // Apply palette default from TWEAK_DEFAULTS once
  useEA(() => {
    if (TWEAK_DEFAULTS?.palette && TWEAK_DEFAULTS.palette !== palette) setPalette(TWEAK_DEFAULTS.palette);
    if (TWEAK_DEFAULTS?.role && TWEAK_DEFAULTS.role !== user.role) {
      const u = roles.find(r => r.role === TWEAK_DEFAULTS.role);
      if (u) setUser(u);
    }
  // eslint-disable-next-line
  }, []);
  function setTweak(patch) {
    window.parent.postMessage({ type: '__edit_mode_set_keys', edits: patch }, '*');
  }

  // Actions
  const handleSubmitRequest = (form) => {
    const dev = selectedDevice; const port = reqModal.port;
    const id = 'r-' + Math.random().toString(36).slice(2, 6);
    const newReq = {
      id, device_id: dev.id, port_name: port.name,
      requested_by: user.username,
      requested_changes: { untagged_vlan: form.untagged_vlan, tagged_vlans: form.tagged_vlans, host_model: form.host_model, bmc_ip: form.bmc_ip, notes: form.notes },
      reason: form.reason,
      status: 'pending', reviewer_id: null, reviewer_comment: '',
      created_at: Date.now(), reviewed_at: null, applied_at: null,
    };
    setRequests(rs => [newReq, ...rs]);
    setReqModal({ open: false, port: null });
    toast({ title: 'Request submitted', message: `#${id} on ${dev.name}/${port.name}`, kind: 'success' });
  };

  const approveOnly = (req) => {
    setRequests(rs => rs.map(r => r.id === req.id ? { ...r, status: 'approved', reviewer_id: user.username, reviewed_at: Date.now() } : r));
    toast({ title: 'Approved', message: `#${req.id} marked approved. Apply when ready.` });
  };

  const applyRequest = (req) => {
    setRequests(rs => rs.map(r => r.id === req.id ? { ...r, status: 'approved', reviewer_id: user.username, reviewed_at: Date.now() } : r));
    toast({ title: 'Applying…', message: `Backup → diff → push to ${devices.find(d => d.id === req.device_id).name}` });
    setTimeout(() => {
      setRequests(rs => rs.map(r => r.id === req.id ? { ...r, status: 'applied', applied_at: Date.now() } : r));
      setPorts(ps => {
        const arr = [...ps[req.device_id]];
        const i = arr.findIndex(p => p.name === req.port_name);
        if (i >= 0) {
          const p = arr[i];
          const newVlan = req.requested_changes.untagged_vlan ?? p.untagged_vlan;
          const newTagged = req.requested_changes.tagged_vlans ?? p.tagged_vlans;
          const newHost = req.requested_changes.host_model ?? p.host_model;
          const newBmc = req.requested_changes.bmc_ip ?? p.bmc_ip;
          arr[i] = {
            ...p,
            untagged_vlan: newVlan,
            tagged_vlans: newTagged,
            host_model: newHost,
            bmc_ip: newBmc,
            description: newVlan && newHost && newBmc ? `VLAN-${newVlan} | ${newHost} | ${newBmc}` : p.description,
          };
        }
        return { ...ps, [req.device_id]: arr };
      });
      toast({ title: 'Applied', message: `#${req.id} pushed. Commit-confirm window: 60s.`, kind: 'success' });
    }, 700);
  };

  const rejectRequest = (req, comment) => {
    setRequests(rs => rs.map(r => r.id === req.id ? { ...r, status: 'rejected', reviewer_id: user.username, reviewed_at: Date.now(), reviewer_comment: comment || r.reviewer_comment } : r));
    toast({ title: 'Rejected', message: `#${req.id} sent back to @${req.requested_by}.` });
  };

  const refetchPort = () => {
    toast({ title: 'Refetching live state', message: '~600ms typical' });
  };

  const adminEditPort = () => {
    toast({ title: 'Direct edit', message: 'Admin direct-edit dialog would open here.' });
  };

  const onSearch = (q) => {
    if (!q.trim()) return;
    // jump to first match
    for (const d of envDevices) {
      const p = ports[d.id]?.find(pt =>
        pt.name.toLowerCase().includes(q.toLowerCase()) ||
        pt.description.toLowerCase().includes(q.toLowerCase()) ||
        String(pt.untagged_vlan) === q.trim() ||
        pt.host_model.toLowerCase().includes(q.toLowerCase()) ||
        pt.bmc_ip.includes(q)
      );
      if (p) {
        setSelectedDeviceId(d.id); setSelectedPort(p.name); setRoute({ name: 'env' });
        toast({ title: 'Jumped', message: `${d.name} / ${p.name}` });
        return;
      }
    }
    toast({ title: 'No match', message: `Nothing in ${env.toUpperCase()} matched "${q}"` });
  };

  // Render
  if (route.name === 'login') {
    return <Login onLogin={(u) => { setUser(roles.find(r => r.username === u) || roles[0]); setRoute({ name: 'envpicker' }); }} />;
  }

  return (
    <div className={`nb-app nb-theme-${theme}`}>
      {route.name !== 'envpicker' && (
        <TopBar
          env={env}
          setEnv={(e) => { setEnv(e); if (route.name !== 'env') setRoute({ name: 'env' }); }}
          search={search}
          setSearch={setSearch}
          onSearch={onSearch}
          route={route}
          setRoute={setRoute}
          user={user}
          setUser={setUser}
          roles={roles}
        />
      )}

      {route.name === 'envpicker' && (
        <EnvPicker devices={devices} ports={ports} requests={requests} theme={theme}
          onPick={(e) => { setEnv(e); setRoute({ name: 'env' }); setSelectedDeviceId(null); }} />
      )}

      {route.name === 'env' && (
        <div className="nb-shell">
          <Sidebar
            env={env}
            devices={devices}
            ports={ports}
            requests={requests}
            selected={selectedDeviceId}
            onSelect={(id) => { setSelectedDeviceId(id); setSelectedPort(null); setOpenTab('ports'); }}
            width={sidebarW}
            setWidth={setSidebarW}
          />
          <main className="nb-main">
            {!selectedDevice ? (
              <div className="nb-topo">
                <NocRibbon env={env} devices={envDevices} ports={ports} requests={requests} />
                <div className="nb-topo__head">
                  <div>
                    <div className="nb-page__eyebrow">{env === 'lab' ? 'Lab environment' : 'Datacenter'} · live topology</div>
                    <h1 className="nb-page__title">{envDevices.length} devices · {envDevices.reduce((a, d) => a + d.portCount, 0)} ports</h1>
                  </div>
                  <div className="nb-page__actions">
                    <span className="nb-mono nb-muted">click a device to inspect</span>
                  </div>
                </div>
                <div className="nb-topo__canvas">
                  <Topology3D
                    env={env}
                    devices={envDevices}
                    links={NB_DATA.LINKS.filter(([a, b]) => devices.find(d => d.id === a)?.env === env)}
                    theme={theme}
                    onPickDevice={(d) => { setSelectedDeviceId(d.id); setSelectedPort(null); }}
                  />
                </div>
              </div>
            ) : (
              <DeviceDetail
                device={selectedDevice}
                ports={selectedDevicePorts}
                allRequests={requests}
                audit={audit}
                theme={theme}
                user={user}
                selectedPort={selectedPort}
                setSelectedPort={setSelectedPort}
                openTab={openTab}
                setOpenTab={setOpenTab}
                onOpenRequest={() => selectedPortObj && setReqModal({ open: true, port: selectedPortObj })}
                onApplyRequest={applyRequest}
                onRejectRequest={(req) => rejectRequest(req, 'Rejected from port panel.')}
                onAdminEdit={adminEditPort}
                onRefetch={refetchPort}
                onPanelClose={() => setSelectedPort(null)}
              />
            )}
          </main>
          {selectedPortObj && (
            <PortPanel
              device={selectedDevice}
              port={selectedPortObj}
              allPorts={selectedDevicePorts}
              allRequests={requests}
              audit={audit}
              theme={theme}
              user={user}
              onClose={() => setSelectedPort(null)}
              onOpenRequest={() => setReqModal({ open: true, port: selectedPortObj })}
              onApply={applyRequest}
              onReject={(req) => rejectRequest(req, 'Rejected from port panel.')}
              onAdminEdit={adminEditPort}
              onRefetch={refetchPort}
            />
          )}
        </div>
      )}

      {route.name === 'myreq' && (
        <main className="nb-main nb-main--solo">
          <RequestsList
            requests={requests}
            devices={devices}
            ports={ports}
            theme={theme}
            user={user}
            scope={user.role === 'admin' ? 'all' : 'mine'}
            onApprove={approveOnly}
            onApply={applyRequest}
            onReject={(req) => rejectRequest(req, 'Rejected from requests list.')}
            onPickDevice={(d, port) => { setSelectedDeviceId(d.id); setEnv(d.env); setSelectedPort(port); setRoute({ name: 'env' }); }}
          />
        </main>
      )}

      {route.name === 'queue' && user.role === 'admin' && (
        <main className="nb-main nb-main--solo">
          <AdminQueue
            requests={requests}
            devices={devices}
            ports={ports}
            theme={theme}
            user={user}
            onApprove={approveOnly}
            onApply={applyRequest}
            onReject={rejectRequest}
            onPickDevice={(d, port) => { setSelectedDeviceId(d.id); setEnv(d.env); setSelectedPort(port); setRoute({ name: 'env' }); }}
            lastBackupFor={lastBackupFor}
          />
        </main>
      )}

      <RequestModal
        open={reqModal.open}
        device={selectedDevice}
        port={reqModal.port}
        theme={theme}
        vlanOptions={NB_DATA.VLANS}
        onClose={() => setReqModal({ open: false, port: null })}
        onSubmit={handleSubmitRequest}
      />

      <HelpOverlay open={helpOpen || route.name === 'help'} onClose={() => { setHelpOpen(false); if (route.name === 'help') setRoute({ name: 'env' }); }} />

      {tweaksOpen && (
        <div className="nb-tweaks">
          <div className="nb-tweaks__head">
            <div className="nb-tweaks__title">Tweaks</div>
            <button className="nb-iconbtn" onClick={() => { setTweaksOpen(false); window.parent.postMessage({ type: '__edit_mode_dismissed' }, '*'); }}>
              <Icon name="close" size={14} />
            </button>
          </div>
          <div className="nb-tweaks__body">
            <div className="nb-tweaks__section">
              <div className="nb-tweaks__label">Palette</div>
              <div className="nb-tweaks__radio">
                {Object.entries(palettes).map(([k, p]) => (
                  <button key={k}
                    className={`nb-tweaks__opt ${palette === k ? 'is-on' : ''}`}
                    onClick={() => { setPalette(k); setTweak({ palette: k }); }}>
                    <span className="nb-tweaks__swatch" style={{ background: p.accent.dark }} />
                    {p.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="nb-tweaks__section">
              <div className="nb-tweaks__label">Role</div>
              <div className="nb-tweaks__radio">
                {roles.map(r => (
                  <button key={r.username}
                    className={`nb-tweaks__opt ${user.username === r.username ? 'is-on' : ''}`}
                    onClick={() => { setUser(r); setTweak({ role: r.role }); }}>
                    {r.role === 'admin' ? '◆' : '○'} {r.username} <span className="nb-mono nb-muted">· {r.role}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Root() {
  return (
    <ThemeProvider>
      <ToastProvider>
        <App />
      </ToastProvider>
    </ThemeProvider>
  );
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(<Root />);
