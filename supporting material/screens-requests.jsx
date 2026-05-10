// Northbound — My requests, Admin queue, Device config view

const { useState: useS3, useEffect: useE3, useMemo: useM3 } = React;

function StatusBadge({ status }) {
  const labels = { pending: 'Pending', approved: 'Approved', applied: 'Applied', rejected: 'Rejected', failed: 'Failed' };
  return <span className={`nb-status nb-status--${status}`}>{labels[status]}</span>;
}

// ---------- My Requests / All requests (read view) ----------
function RequestsList({ requests, devices, ports, theme, user, scope = 'mine', onApprove, onApply, onReject, onPickDevice }) {
  const [filter, setFilter] = useS3('all');
  const filtered = useM3(() => {
    let list = requests;
    if (scope === 'mine') list = list.filter(r => r.requested_by === user.username);
    if (filter !== 'all') list = list.filter(r => r.status === filter);
    return [...list].sort((a, b) => b.created_at - a.created_at);
  }, [requests, filter, user.username, scope]);
  const [expanded, setExpanded] = useS3(null);

  const counts = useM3(() => {
    const base = scope === 'mine' ? requests.filter(r => r.requested_by === user.username) : requests;
    return {
      all: base.length,
      pending: base.filter(r => r.status === 'pending').length,
      approved: base.filter(r => r.status === 'approved').length,
      applied: base.filter(r => r.status === 'applied').length,
      rejected: base.filter(r => r.status === 'rejected').length,
    };
  }, [requests, scope, user.username]);

  return (
    <div className="nb-page">
      <div className="nb-page__head">
        <div>
          <div className="nb-page__eyebrow">{scope === 'mine' ? 'Filed by you' : 'Across both environments'}</div>
          <h1 className="nb-page__title">{scope === 'mine' ? 'My requests' : 'All requests'}</h1>
        </div>
      </div>
      <div className="nb-filters">
        {['all', 'pending', 'approved', 'applied', 'rejected'].map(k => (
          <button key={k} className={`nb-filter ${filter === k ? 'is-on' : ''}`} onClick={() => setFilter(k)}>
            <span>{k}</span>
            <span className="nb-filter__count">{counts[k]}</span>
          </button>
        ))}
      </div>
      <div className="nb-rqlist">
        {filtered.length === 0 ? <div className="nb-empty">No requests in this view.</div> : filtered.map(req => {
          const dev = devices.find(d => d.id === req.device_id);
          const port = (ports[req.device_id] || []).find(p => p.name === req.port_name);
          const isOpen = expanded === req.id;
          return (
            <div key={req.id} className={`nb-rqrow ${isOpen ? 'is-open' : ''}`}>
              <button className="nb-rqrow__head" onClick={() => setExpanded(isOpen ? null : req.id)}>
                <div className="nb-rqrow__id">
                  <Icon name={isOpen ? 'chev-d' : 'chev-r'} size={14} />
                  <span className="nb-mono">#{req.id}</span>
                </div>
                <div className="nb-rqrow__where">
                  <span className="nb-rqrow__env">{dev.env}</span>
                  <span className="nb-mono">{dev.name}</span>
                  <Icon name="chev-r" size={12} />
                  <span className="nb-mono">{req.port_name}</span>
                </div>
                <div className="nb-rqrow__sum">
                  <VlanChip vlan={port?.untagged_vlan} theme={theme} />
                  <Icon name="arrow-r" size={12} />
                  <VlanChip vlan={req.requested_changes.untagged_vlan} theme={theme} />
                  {req.requested_changes.tagged_vlans?.length ? <span className="nb-mono nb-muted">+{req.requested_changes.tagged_vlans.length}T</span> : null}
                </div>
                <div className="nb-rqrow__meta">
                  <span>@{req.requested_by}</span>
                  <span className="nb-rqrow__age">{timeAgo(req.created_at)}</span>
                  <StatusBadge status={req.status} />
                </div>
              </button>
              {isOpen && port && (
                <div className="nb-rqrow__body">
                  <div className="nb-rqrow__reason">
                    <div className="nb-kv__label">Reason</div>
                    <div>{req.reason}</div>
                  </div>
                  {req.reviewer_comment && (
                    <div className="nb-rqrow__reason">
                      <div className="nb-kv__label">Reviewer comment</div>
                      <div>{req.reviewer_comment}</div>
                    </div>
                  )}
                  <div className="nb-rqrow__diff">
                    <div className="nb-kv__label">Proposed change</div>
                    <Diff before={portToDiff(port)} after={mergeChange(port, req.requested_changes)} />
                  </div>
                  <div className="nb-rqrow__cfg">
                    <div className="nb-kv__label">Rendered config delta</div>
                    <ConfigDiff device={dev} portBefore={port} portAfter={mergeChange(port, req.requested_changes)} />
                  </div>
                  <div className="nb-rqrow__actions">
                    <button className="nb-linkbtn" onClick={() => onPickDevice?.(dev, req.port_name)}>
                      Open port <Icon name="arrow-r" size={12} />
                    </button>
                    {user.role === 'admin' && req.status === 'pending' && (
                      <>
                        <Button kind="success" size="sm" icon="check" onClick={() => onApply(req)}>Approve & apply</Button>
                        <Button kind="ghost" size="sm" onClick={() => onApprove(req)}>Approve only</Button>
                        <Button kind="danger" size="sm" onClick={() => onReject(req)}>Reject</Button>
                      </>
                    )}
                    {user.role === 'admin' && req.status === 'approved' && (
                      <Button kind="success" size="sm" icon="check" onClick={() => onApply(req)}>Apply now</Button>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------- Admin queue ----------
function AdminQueue({ requests, devices, ports, theme, user, onApprove, onApply, onReject, onPickDevice, lastBackupFor }) {
  const [sort, setSort] = useS3('age');
  const [envFilter, setEnvFilter] = useS3('all');
  const [expanded, setExpanded] = useS3(null);
  const [rejectingId, setRejectingId] = useS3(null);
  const [rejectComment, setRejectComment] = useS3('');

  const list = useM3(() => {
    let l = requests.filter(r => r.status === 'pending' || r.status === 'approved');
    if (envFilter !== 'all') {
      l = l.filter(r => devices.find(d => d.id === r.device_id)?.env === envFilter);
    }
    if (sort === 'age') l = [...l].sort((a, b) => a.created_at - b.created_at);
    if (sort === 'env') l = [...l].sort((a, b) => (devices.find(d => d.id === a.device_id)?.env || '').localeCompare(devices.find(d => d.id === b.device_id)?.env || ''));
    if (sort === 'requester') l = [...l].sort((a, b) => a.requested_by.localeCompare(b.requested_by));
    return l;
  }, [requests, sort, envFilter, devices]);

  const counts = useM3(() => ({
    pending: requests.filter(r => r.status === 'pending').length,
    approved: requests.filter(r => r.status === 'approved').length,
  }), [requests]);

  return (
    <div className="nb-page">
      <div className="nb-page__head">
        <div>
          <div className="nb-page__eyebrow">{counts.pending} pending · {counts.approved} approved waiting to apply</div>
          <h1 className="nb-page__title">Request queue</h1>
        </div>
        <div className="nb-page__actions">
          <div className="nb-segmented">
            {['all', 'lab', 'dc'].map(k => (
              <button key={k} className={envFilter === k ? 'is-on' : ''} onClick={() => setEnvFilter(k)}>{k.toUpperCase()}</button>
            ))}
          </div>
          <div className="nb-segmented">
            <button className={sort === 'age' ? 'is-on' : ''} onClick={() => setSort('age')}>Oldest first</button>
            <button className={sort === 'env' ? 'is-on' : ''} onClick={() => setSort('env')}>Env</button>
            <button className={sort === 'requester' ? 'is-on' : ''} onClick={() => setSort('requester')}>Requester</button>
          </div>
        </div>
      </div>

      <div className="nb-rqlist">
        {list.length === 0 ? <div className="nb-empty">Inbox zero. Nice.</div> : list.map(req => {
          const dev = devices.find(d => d.id === req.device_id);
          const port = (ports[req.device_id] || []).find(p => p.name === req.port_name);
          const isOpen = expanded === req.id;
          if (!port) return null;
          return (
            <div key={req.id} className={`nb-rqrow ${isOpen ? 'is-open' : ''}`}>
              <button className="nb-rqrow__head" onClick={() => setExpanded(isOpen ? null : req.id)}>
                <div className="nb-rqrow__id">
                  <Icon name={isOpen ? 'chev-d' : 'chev-r'} size={14} />
                  <span className="nb-mono">#{req.id}</span>
                </div>
                <div className="nb-rqrow__where">
                  <span className="nb-rqrow__env">{dev.env}</span>
                  <span className="nb-mono">{dev.name}</span>
                  <Icon name="chev-r" size={12} />
                  <span className="nb-mono">{req.port_name}</span>
                </div>
                <div className="nb-rqrow__sum">
                  <VlanChip vlan={port.untagged_vlan} theme={theme} />
                  <Icon name="arrow-r" size={12} />
                  <VlanChip vlan={req.requested_changes.untagged_vlan} theme={theme} />
                </div>
                <div className="nb-rqrow__meta">
                  <span>@{req.requested_by}</span>
                  <span className="nb-rqrow__age">{timeAgo(req.created_at)}</span>
                  <StatusBadge status={req.status} />
                </div>
              </button>
              {isOpen && (
                <div className="nb-rqrow__body">
                  <div className="nb-safety">
                    <Icon name="history" size={14} />
                    <span>Last config backup of <strong>{dev.name}</strong>: {timeAgo(lastBackupFor(dev.id))}</span>
                    <span className="nb-safety__sep">·</span>
                    <span>Apply will run <em>backup → diff → push</em>{dev.platform !== 'freebsd' ? ' with commit-confirm.' : ' with at-based revert in 2m.'}</span>
                  </div>
                  <div className="nb-rqrow__reason">
                    <div className="nb-kv__label">Reason</div>
                    <div>{req.reason}</div>
                  </div>
                  <div className="nb-rqrow__split">
                    <div>
                      <div className="nb-kv__label">Field changes</div>
                      <Diff before={portToDiff(port)} after={mergeChange(port, req.requested_changes)} />
                    </div>
                    <div>
                      <div className="nb-kv__label">Rendered config</div>
                      <ConfigDiff device={dev} portBefore={port} portAfter={mergeChange(port, req.requested_changes)} />
                    </div>
                  </div>

                  {rejectingId === req.id ? (
                    <div className="nb-reject">
                      <textarea autoFocus rows={2} value={rejectComment} onChange={e => setRejectComment(e.target.value)} placeholder="Required: tell @{requested_by} why and what to do." />
                      <div className="nb-rqrow__actions">
                        <Button kind="ghost" size="sm" onClick={() => { setRejectingId(null); setRejectComment(''); }}>Cancel</Button>
                        <Button kind="danger" size="sm" disabled={!rejectComment.trim()} onClick={() => { onReject(req, rejectComment); setRejectingId(null); setRejectComment(''); }}>Confirm reject</Button>
                      </div>
                    </div>
                  ) : (
                    <div className="nb-rqrow__actions">
                      <Button kind="success" icon="check" onClick={() => onApply(req)}>Approve & apply</Button>
                      {req.status === 'pending' && <Button kind="ghost" onClick={() => onApprove(req)}>Approve only</Button>}
                      <Button kind="danger" onClick={() => setRejectingId(req.id)}>Reject…</Button>
                      <button className="nb-linkbtn nb-rqrow__open" onClick={() => onPickDevice?.(dev, req.port_name)}>
                        Open port <Icon name="arrow-r" size={12} />
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------- ConfigDiff: render before/after configs, line-by-line color ----------
function ConfigDiff({ device, portBefore, portAfter }) {
  const before = renderConfigSnippet(device, portBefore).split('\n');
  const after = renderConfigSnippet(device, portAfter).split('\n');
  const max = Math.max(before.length, after.length);
  const lines = [];
  // naive line-aligned diff (these rendered configs are short and structurally similar)
  for (let i = 0; i < max; i++) {
    const a = before[i] || '';
    const b = after[i] || '';
    if (a === b) lines.push({ kind: 'eq', text: a });
    else {
      if (a) lines.push({ kind: 'rem', text: a });
      if (b) lines.push({ kind: 'add', text: b });
    }
  }
  return (
    <pre className="nb-cfgdiff"><code>
      {lines.map((l, i) => (
        <div key={i} className={`nb-cfgdiff__line nb-cfgdiff__line--${l.kind}`}>
          <span className="nb-cfgdiff__mark">{l.kind === 'add' ? '+' : l.kind === 'rem' ? '-' : ' '}</span>
          <span>{l.text}</span>
        </div>
      ))}
    </code></pre>
  );
}

// ---------- Device Config tab ----------
function highlightLine(line, platform) {
  // simple syntax highlighter — keyword / string / comment / number
  const isComment = /^\s*[#!;]/.test(line);
  if (isComment) return <span className="nb-syn-com">{line}</span>;
  // tokenize by spaces but preserve quoted
  const parts = line.split(/(".*?")/g);
  return parts.map((part, i) => {
    if (part.startsWith('"')) return <span key={i} className="nb-syn-str">{part}</span>;
    return part.split(/(\s+)/).map((tok, j) => {
      if (/^\s+$/.test(tok)) return <span key={i + ':' + j}>{tok}</span>;
      const t = tok.trim();
      if (/^\d+(\.\d+){0,3}(\/\d+)?$/.test(t)) return <span key={i + ':' + j} className="nb-syn-num">{tok}</span>;
      const KW_BY = {
        mikrotik: ['add', 'set', 'find', 'name', 'comment', 'disabled', 'bridge', 'vlan-ids', 'untagged', 'tagged', 'interface'],
        arista: ['interface', 'description', 'no', 'shutdown', 'switchport', 'mode', 'access', 'trunk', 'native', 'vlan', 'allowed', 'router', 'bgp', 'neighbor'],
        pica8: ['set', 'interface', 'description', 'enable', 'disable', 'vlans', 'tagged', 'untagged', 'protocols'],
        freebsd: ['ifconfig_', 'inet', 'up', 'down', 'mtu', 'pf', 'rc.conf'],
      };
      const kw = (KW_BY[platform] || []).some(k => t === k || t.startsWith(k));
      if (kw) return <span key={i + ':' + j} className="nb-syn-kw">{tok}</span>;
      return <span key={i + ':' + j}>{tok}</span>;
    });
  });
}

function DeviceConfigView({ device, ports, user }) {
  const isAdmin = user.role === 'admin';
  const [query, setQuery] = useS3('');
  const [showDiff, setShowDiff] = useS3(false);
  const lines = useM3(() => generateFullConfig(device, ports), [device, ports]);
  const filteredIdx = useM3(() => {
    if (!query) return null;
    return new Set(lines.map((l, i) => l.toLowerCase().includes(query.toLowerCase()) ? i : -1).filter(i => i >= 0));
  }, [query, lines]);

  if (!isAdmin) {
    return (
      <div className="nb-cfgview">
        <div className="nb-empty">
          <Icon name="config" size={20} />
          <div>The full running config is admin-only.</div>
          <div className="nb-muted">Per-port snippets remain visible in the port detail panel.</div>
        </div>
      </div>
    );
  }

  return (
    <div className="nb-cfgview">
      <div className="nb-cfgview__bar">
        <div className="nb-cfgview__search">
          <Icon name="search" size={14} />
          <input placeholder={`Search running config of ${device.name}…`} value={query} onChange={e => setQuery(e.target.value)} />
        </div>
        <div className="nb-cfgview__actions">
          <Button kind="ghost" size="sm" icon="history" onClick={() => setShowDiff(s => !s)}>
            {showDiff ? 'Hide diff' : 'Compare to last backup'}
          </Button>
          <Button kind="ghost" size="sm" icon="refresh">Backup now</Button>
          <span className="nb-cfgview__last">last backup · 2 h ago</span>
        </div>
      </div>
      {showDiff ? (
        <div className="nb-cfgdiff-wrap">
          <ConfigDiff
            device={device}
            portBefore={{ ...ports[0], description: '' }}
            portAfter={ports[0]}
          />
          <div className="nb-muted nb-cfgview__hint">Showing illustrative diff against the most recent backup of {device.name}.</div>
        </div>
      ) : (
        <pre className="nb-cfg-full"><code>
          {lines.map((line, i) => (
            <div key={i} className={`nb-cfg-line ${filteredIdx && !filteredIdx.has(i) ? 'is-dim' : ''} ${filteredIdx && filteredIdx.has(i) ? 'is-hit' : ''}`}>
              <span className="nb-cfg-num">{i + 1}</span>
              <span className="nb-cfg-text">{highlightLine(line, device.platform)}</span>
            </div>
          ))}
        </code></pre>
      )}
    </div>
  );
}

function generateFullConfig(device, ports) {
  if (device.platform === 'mikrotik') {
    const lines = [
      `# RouterOS 7.x · ${device.model}`,
      `# system identity = "${device.name}"`,
      ``,
      `/interface bridge`,
      `add name=br1 vlan-filtering=yes`,
      ``,
      `/interface ethernet`,
    ];
    for (const p of ports) {
      lines.push(`set [find name="${p.name}"] comment="${p.description}" ${p.admin_up ? 'disabled=no' : 'disabled=yes'}`);
    }
    lines.push(``, `/interface bridge vlan`);
    const byVlan = {};
    for (const p of ports) {
      (byVlan[p.untagged_vlan] = byVlan[p.untagged_vlan] || { u: [], t: [] }).u.push(p.name);
      for (const t of p.tagged_vlans) (byVlan[t] = byVlan[t] || { u: [], t: [] }).t.push(p.name);
    }
    for (const v of Object.keys(byVlan).sort()) {
      const grp = byVlan[v];
      lines.push(`add bridge=br1 vlan-ids=${v} untagged="${grp.u.join(',')}"${grp.t.length ? ' tagged="' + grp.t.join(',') + '"' : ''}`);
    }
    lines.push(``, `/ip service`, `set telnet disabled=yes`, `set api disabled=yes`, `set winbox disabled=no`);
    return lines;
  }
  if (device.platform === 'arista') {
    const lines = [
      `! EOS · ${device.model}`,
      `hostname ${device.name}`,
      `!`,
    ];
    const vlans = new Set();
    for (const p of ports) { vlans.add(p.untagged_vlan); p.tagged_vlans.forEach(v => vlans.add(v)); }
    for (const v of [...vlans].sort()) lines.push(`vlan ${v}`, `   name VLAN_${v}`, `!`);
    for (const p of ports) {
      lines.push(`interface ${p.name}`);
      if (p.description) lines.push(`   description ${p.description}`);
      lines.push(`   ${p.admin_up ? 'no shutdown' : 'shutdown'}`);
      if (p.tagged_vlans.length) {
        lines.push(`   switchport mode trunk`, `   switchport trunk native vlan ${p.untagged_vlan}`, `   switchport trunk allowed vlan ${[p.untagged_vlan, ...p.tagged_vlans].join(',')}`);
      } else {
        lines.push(`   switchport mode access`, `   switchport access vlan ${p.untagged_vlan}`);
      }
      lines.push(`!`);
    }
    return lines;
  }
  if (device.platform === 'pica8') {
    const lines = [`# PicOS · ${device.model}`, `set system hostname ${device.name}`, ``];
    const vlans = new Set();
    for (const p of ports) { vlans.add(p.untagged_vlan); p.tagged_vlans.forEach(v => vlans.add(v)); }
    for (const v of [...vlans].sort()) lines.push(`set vlans v${v} description "VLAN ${v}"`);
    lines.push(``);
    for (const p of ports) {
      lines.push(`set interface ${p.name} description "${p.description}"`);
      lines.push(`set interface ${p.name} ${p.admin_up ? 'enable' : 'disable'}`);
      lines.push(`set vlans v${p.untagged_vlan} interface ${p.name} untagged`);
      for (const t of p.tagged_vlans) lines.push(`set vlans v${t} interface ${p.name} tagged`);
    }
    return lines;
  }
  if (device.platform === 'freebsd') {
    const lines = [
      `# /etc/rc.conf`,
      `hostname="${device.name}"`,
      `gateway_enable="YES"`,
      `# interfaces`,
    ];
    for (const p of ports) lines.push(`ifconfig_${p.name}="${p.admin_up ? 'up' : 'down'}"`);
    lines.push(`# vlans`);
    for (const p of ports) for (const v of [p.untagged_vlan, ...p.tagged_vlans]) {
      lines.push(`ifconfig_${p.name}_${v}="inet 10.0.${v}.1/24"`);
    }
    lines.push(``, `# /usr/local/etc/frr/frr.conf (excerpt)`, `frr defaults traditional`, `router bgp 65001`, `   bgp router-id 10.20.0.1`);
    return lines;
  }
  return [];
}

window.RequestsList = RequestsList;
window.AdminQueue = AdminQueue;
window.DeviceConfigView = DeviceConfigView;
window.ConfigDiff = ConfigDiff;
window.StatusBadge = StatusBadge;
