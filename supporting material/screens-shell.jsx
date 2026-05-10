// Northbound — login, environment picker, environment view shell

const { useState: useS1, useEffect: useE1, useMemo: useM1, useRef: useR1 } = React;

// ---------- Top bar ----------
function TopBar({ env, setEnv, search, setSearch, route, setRoute, user, setUser, roles, onSearch }) {
  const { theme, toggle } = useTheme();
  const [menuOpen, setMenuOpen] = useS1(false);
  const ref = useR1(null);
  useE1(() => {
    const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setMenuOpen(false); };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);
  return (
    <div className="nb-topbar">
      <div className="nb-topbar__left">
        <button className="nb-brand-btn" onClick={() => setRoute({ name: 'envpicker' })}>
          <Wordmark size={15} />
        </button>
        <div className="nb-env-tabs">
          <button className={`nb-env-tab ${env === 'lab' ? 'is-active' : ''}`} onClick={() => setEnv('lab')}>
            Lab
          </button>
          <button className={`nb-env-tab ${env === 'dc' ? 'is-active' : ''}`} onClick={() => setEnv('dc')}>
            DC
          </button>
        </div>
      </div>

      <div className="nb-topbar__center">
        <div className="nb-search">
          <Icon name="search" size={14} />
          <input
            placeholder="Search ports, VLANs, hosts, BMC IPs…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') onSearch?.(search); }}
          />
          <Kbd>/</Kbd>
        </div>
      </div>

      <div className="nb-topbar__right">
        {user.role === 'admin' && (
          <button className={`nb-toplink ${route.name === 'queue' ? 'is-active' : ''}`} onClick={() => setRoute({ name: 'queue' })}>
            <Icon name="queue" size={14} />
            <span>Queue</span>
            <span className="nb-badge nb-badge--accent">{NB_DATA.CHANGE_REQUESTS.filter(r => r.status === 'pending').length}</span>
          </button>
        )}
        <button className={`nb-toplink ${route.name === 'myreq' ? 'is-active' : ''}`} onClick={() => setRoute({ name: 'myreq' })}>
          <Icon name="inbox" size={14} />
          <span>{user.role === 'admin' ? 'All requests' : 'My requests'}</span>
        </button>
        <div className="nb-role-pill" role="group" aria-label="Role">
          <button className={`nb-role-pill__btn ${user.role === 'admin' ? 'is-on' : ''}`} onClick={() => setUser(roles[0])}>admin</button>
          <button className={`nb-role-pill__btn ${user.role === 'requester' ? 'is-on' : ''}`} onClick={() => setUser(roles[1])}>requester</button>
        </div>
        <div className="nb-usermenu" ref={ref}>
          <button className="nb-avatar" onClick={() => setMenuOpen(o => !o)} aria-label="Account">
            <span>{user.name.split(' ').map(s => s[0]).join('').slice(0, 2)}</span>
          </button>
          {menuOpen && (
            <div className="nb-menu">
              <div className="nb-menu__head">
                <div className="nb-menu__name">{user.name}</div>
                <div className="nb-menu__role">{user.role === 'admin' ? 'Admin' : 'Requester'} · @{user.username}</div>
              </div>
              <button className="nb-menu__item" onClick={() => { toggle(); }}>
                <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={14} />
                <span>{theme === 'dark' ? 'Light theme' : 'Dark theme'}</span>
              </button>
              <button className="nb-menu__item" onClick={() => { setRoute({ name: 'help' }); setMenuOpen(false); }}>
                <Icon name="kbd" size={14} />
                <span>Keyboard shortcuts</span>
                <Kbd>?</Kbd>
              </button>
              <button className="nb-menu__item" onClick={() => { setRoute({ name: 'myreq' }); setMenuOpen(false); }}>
                <Icon name="inbox" size={14} />
                <span>My requests</span>
              </button>
              <div className="nb-menu__sep" />
              <button className="nb-menu__item nb-menu__item--muted" onClick={() => setRoute({ name: 'login' })}>
                <Icon name="logout" size={14} />
                <span>Sign out</span>
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------- Sidebar ----------
function Sidebar({ env, devices, ports, requests, selected, onSelect, width, setWidth }) {
  const groups = useM1(() => {
    const map = { spine: [], leaf: [], router: [], vpn: [] };
    for (const d of devices) if (d.env === env) map[d.role].push(d);
    return map;
  }, [env, devices]);
  const labels = { spine: 'Spines', leaf: 'Leaves', router: 'Routers', vpn: 'VPN' };
  const order = ['spine', 'leaf', 'router', 'vpn'];

  const dragRef = useR1({ active: false, startX: 0, startW: 0 });
  const onDown = (e) => { dragRef.current = { active: true, startX: e.clientX, startW: width }; document.body.classList.add('nb-resizing'); };
  useE1(() => {
    const onMove = (e) => { if (dragRef.current.active) setWidth(Math.max(220, Math.min(420, dragRef.current.startW + (e.clientX - dragRef.current.startX)))); };
    const onUp = () => { dragRef.current.active = false; document.body.classList.remove('nb-resizing'); };
    window.addEventListener('mousemove', onMove); window.addEventListener('mouseup', onUp);
    return () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp); };
  }, [setWidth]);

  return (
    <aside className="nb-sidebar" style={{ width }}>
      <div className="nb-sidebar__inner">
        <div className="nb-sidebar__head">
          <div className="nb-sidebar__envname">{env === 'lab' ? 'Lab environment' : 'Datacenter'}</div>
          <div className="nb-sidebar__envsub">{devices.filter(d => d.env === env).length} devices</div>
        </div>
        {order.map(role => groups[role].length ? (
          <div key={role} className="nb-sidegroup">
            <div className="nb-sidegroup__title">{labels[role]}</div>
            <ul className="nb-sidelist">
              {groups[role].map(d => {
                const pendingCount = requests.filter(r => r.device_id === d.id && r.status === 'pending').length;
                return (
                  <li key={d.id}>
                    <button
                      className={`nb-siderow ${selected === d.id ? 'is-active' : ''}`}
                      onClick={() => onSelect(d.id)}
                    >
                      <span className={`nb-platicon nb-platicon--${d.platform}`}>
                        <Icon name={d.role === 'spine' ? 'spine' : d.role === 'router' ? 'router' : d.role === 'vpn' ? 'vpn' : 'leaf'} size={14} />
                      </span>
                      <span className="nb-siderow__name">{d.name}</span>
                      <span className="nb-siderow__meta">
                        {pendingCount > 0 && <span className="nb-badge nb-badge--accent" title={`${pendingCount} pending`}>{pendingCount}</span>}
                        <StatusDot state={d.reachable ? 'up' : 'down'} />
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null)}
      </div>
      <div className="nb-sidebar__resize" onMouseDown={onDown} />
    </aside>
  );
}

// ---------- Environment Picker ----------
function EnvPicker({ devices, ports, requests, theme, onPick }) {
  const stats = useM1(() => {
    const out = {};
    for (const env of ['lab', 'dc']) {
      const ds = devices.filter(d => d.env === env);
      const ps = ds.flatMap(d => ports[d.id]);
      const rq = requests.filter(r => ds.find(d => d.id === r.device_id) && r.status === 'pending');
      out[env] = {
        devices: ds.length,
        ports: ps.length,
        pending: rq.length,
        up: ps.filter(p => p.state === 'up').length,
        updated: Date.now() - 1000 * 60 * 2,
      };
    }
    return out;
  }, [devices, ports, requests]);

  return (
    <div className="nb-envpicker">
      <div className="nb-envpicker__hero">
        <div className="nb-envpicker__eyebrow">Northbound · v0.1 · internal</div>
        <h1 className="nb-envpicker__title">Pick an environment</h1>
        <div className="nb-envpicker__sub">Live state, structured requests, no more port-by-DM.</div>
      </div>
      <div className="nb-envpicker__grid">
        {['lab', 'dc'].map(env => {
          const ds = devices.filter(d => d.env === env);
          const s = stats[env];
          return (
            <button key={env} className="nb-envtile" onClick={() => onPick(env)}>
              <div className="nb-envtile__scene">
                <Topology3D env={env} devices={ds} links={NB_DATA.LINKS.filter(([a, b]) => devices.find(d => d.id === a)?.env === env)} theme={theme} ambient />
              </div>
              <div className="nb-envtile__meta">
                <div className="nb-envtile__head">
                  <div className="nb-envtile__name">{env === 'lab' ? 'Lab' : 'Datacenter'}</div>
                  <div className="nb-envtile__updated">updated {timeAgo(s.updated)}</div>
                </div>
                <div className="nb-envtile__stats">
                  <div><span className="nb-statn">{s.devices}</span><span className="nb-statl">devices</span></div>
                  <div><span className="nb-statn">{s.ports}</span><span className="nb-statl">ports</span></div>
                  <div><span className="nb-statn">{s.up}</span><span className="nb-statl">up</span></div>
                  <div className={s.pending ? 'is-warn' : ''}><span className="nb-statn">{s.pending}</span><span className="nb-statl">pending</span></div>
                </div>
                <div className="nb-envtile__cta">
                  Enter <Icon name="arrow-r" size={14} />
                </div>
              </div>
            </button>
          );
        })}
      </div>
      <div className="nb-envpicker__foot">
        <span>Connected as <strong>{NB_DATA.USERS[0].name}</strong></span>
        <span className="nb-mono">tailnet · northbound.lab</span>
      </div>
    </div>
  );
}

// ---------- Login screen ----------
function Login({ onLogin }) {
  const [u, setU] = useS1('admin');
  const [p, setP] = useS1('••••••••');
  const submit = (e) => { e.preventDefault(); onLogin(u); };
  return (
    <div className="nb-login">
      <form className="nb-login__card" onSubmit={submit}>
        <div className="nb-login__brand"><Wordmark size={22} /></div>
        <div className="nb-login__sub">SDN management plane</div>
        <label className="nb-field">
          <span>Username</span>
          <input value={u} onChange={e => setU(e.target.value)} autoFocus />
        </label>
        <label className="nb-field">
          <span>Password</span>
          <input type="password" value={p} onChange={e => setP(e.target.value)} />
        </label>
        <Button kind="primary" size="lg" type="submit">Sign in</Button>
        <div className="nb-login__tag">v0.1 · internal</div>
      </form>
    </div>
  );
}

// ---------- Help overlay ----------
function HelpOverlay({ open, onClose }) {
  const rows = [
    ['Search', '/'],
    ['Switch to Lab', 'g l'],
    ['Switch to DC', 'g d'],
    ['Move between ports', 'j / k'],
    ['Request change on selected port', 'r'],
    ['Help (this menu)', '?'],
    ['Close panel / modal', 'Esc'],
  ];
  return (
    <Modal open={open} onClose={onClose} title="Keyboard shortcuts" subtitle="Designed for one-handed operation while you read logs." width={520}>
      <ul className="nb-shortlist">
        {rows.map(([label, key]) => (
          <li key={label}>
            <span>{label}</span>
            <span className="nb-shortlist__keys">{key.split(' ').map((k, i) => <Kbd key={i}>{k}</Kbd>)}</span>
          </li>
        ))}
      </ul>
    </Modal>
  );
}

Object.assign(window, { TopBar, Sidebar, EnvPicker, Login, HelpOverlay });
