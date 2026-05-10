// Northbound — device detail (hero), port strip, port detail panel, request modal

const { useState: useS2, useEffect: useE2, useMemo: useM2, useRef: useR2, useLayoutEffect: useL2 } = React;

function PortCard({ port, selected, theme, requestsForPort, onClick }) {
  const v = port.untagged_vlan;
  const color = vlanColor(v, theme);
  const muted = vlanColorMuted(v, theme);
  const stateClass = `nb-portcard--${port.state}`;
  return (
    <button
      data-port={port.name}
      className={`nb-portcard ${stateClass} ${selected ? 'is-selected' : ''}`}
      onClick={onClick}
      style={{ '--vlan': color, '--vlan-muted': muted }}
    >
      <div className="nb-portcard__top">
        <span className="nb-portcard__name">{port.name}</span>
        <StatusDot state={port.state} pulse={port.state === 'up' && port.traffic > 0.4} />
      </div>
      <div className="nb-portcard__vlan">
        {port.state === 'up' || port.state === 'disabled' ? (
          <span className="nb-portcard__vnum">{v}</span>
        ) : (
          <span className="nb-portcard__vnum is-empty">—</span>
        )}
        {port.tagged_vlans.length > 0 && (
          <span className="nb-portcard__trunk">T+{port.tagged_vlans.length}</span>
        )}
      </div>
      <div className="nb-portcard__desc" title={port.description || ''}>
        {port.description || (port.state === 'down' ? 'no link' : port.state === 'disabled' ? 'admin disabled' : 'no description')}
      </div>
      {requestsForPort.length > 0 && (
        <div className="nb-portcard__pending">
          <Icon name="inbox" size={10} />
          <span>{requestsForPort.length} pending</span>
        </div>
      )}
    </button>
  );
}

function PortStrip({ device, ports, selected, requests, theme, onSelect }) {
  const wrapRef = useR2(null);
  // Auto-scroll selection into view
  useE2(() => {
    if (!selected) return;
    const el = wrapRef.current?.querySelector(`[data-port="${CSS.escape(selected)}"]`);
    if (el) el.scrollIntoView?.({ behavior: 'smooth', block: 'nearest', inline: 'center' });
  }, [selected]);
  return (
    <div className="nb-portstrip">
      <div className="nb-portstrip__head">
        <div className="nb-portstrip__title">
          {ports.length} ports
          <span className="nb-portstrip__legend">
            <span><span className="nb-d nb-d--up" />{ports.filter(p => p.state === 'up').length} up</span>
            <span><span className="nb-d nb-d--down" />{ports.filter(p => p.state === 'down').length} down</span>
            <span><span className="nb-d nb-d--disabled" />{ports.filter(p => p.state === 'disabled').length} disabled</span>
          </span>
        </div>
        <div className="nb-portstrip__keys">
          <Kbd>j</Kbd> <Kbd>k</Kbd> to move · <Kbd>r</Kbd> to request
        </div>
      </div>
      <div className="nb-portstrip__scroll" ref={wrapRef}>
        <div className="nb-portstrip__grid">
          {ports.map(p => (
            <PortCard
              key={p.name}
              port={p}
              theme={theme}
              selected={selected === p.name}
              requestsForPort={requests.filter(r => r.device_id === device.id && r.port_name === p.name && r.status === 'pending')}
              onClick={() => onSelect(p.name)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

function VlanChip({ vlan, theme, onRemove, large = false }) {
  return (
    <span className={`nb-vchip ${large ? 'nb-vchip--lg' : ''}`} style={{ '--vlan': vlanColor(vlan, theme), '--vlan-muted': vlanColorMuted(vlan, theme) }}>
      <span className="nb-vchip__dot" />
      <span className="nb-vchip__num">{vlan}</span>
      {onRemove && <button className="nb-vchip__x" onClick={onRemove}><Icon name="x" size={10} /></button>}
    </span>
  );
}

// ---------- Port detail panel ----------
function PortPanel({ device, port, allPorts, allRequests, theme, user, onClose, onOpenRequest, onApply, onReject, onAdminEdit, onRefetch, audit }) {
  const pending = allRequests.filter(r => r.device_id === device.id && r.port_name === port.name && r.status === 'pending');
  const isAdmin = user.role === 'admin';
  const portAudit = audit.filter(a => a.device_id === device.id && a.port_name === port.name).slice(0, 6);

  return (
    <aside className="nb-portpanel" key={device.id + ':' + port.name}>
      <div className="nb-portpanel__head">
        <div>
          <div className="nb-portpanel__crumb">
            <span className="nb-mono">{device.name}</span>
            <Icon name="chev-r" size={12} />
            <span className="nb-mono">{port.name}</span>
          </div>
          <div className="nb-portpanel__title">
            <StatusDot state={port.state} pulse={port.state === 'up' && port.traffic > 0.4} size={10} />
            <span>{port.state === 'up' ? 'Link up' : port.state === 'down' ? 'No link' : 'Admin disabled'}</span>
            <span className="nb-portpanel__vinline">on VLAN
              <VlanChip vlan={port.untagged_vlan} theme={theme} />
            </span>
          </div>
        </div>
        <button className="nb-iconbtn" onClick={onClose}><Icon name="x" /></button>
      </div>

      <div className="nb-portpanel__body">
        <Section title="Overview">
          <div className="nb-kv">
            <div><span>Description</span><span className="nb-mono">{port.description || '—'}</span></div>
            <div><span>Host model</span><span>{port.host_model || '—'}</span></div>
            <div><span>BMC IP</span><span className="nb-mono">{port.bmc_ip || '—'}</span></div>
            <div><span>MAC</span><span className="nb-mono">{port.mac || '—'}</span></div>
            <div><span>Speed</span><span>{port.speed_mbps ? (port.speed_mbps >= 1000 ? port.speed_mbps / 1000 + ' Gbps' : port.speed_mbps + ' Mbps') : '—'}</span></div>
            <div><span>Duplex</span><span>{port.duplex || '—'}</span></div>
            <div><span>MTU</span><span>{port.mtu}</span></div>
          </div>
          <div className="nb-portpanel__notes">
            <div className="nb-portpanel__notes-label">Notes</div>
            <div className="nb-portpanel__notes-body">{port.notes || <em>No notes</em>}</div>
          </div>
        </Section>

        <Section title="VLANs">
          <div className="nb-vlanrow">
            <div className="nb-vlanrow__label">Untagged</div>
            <VlanChip vlan={port.untagged_vlan} theme={theme} large />
          </div>
          <div className="nb-vlanrow">
            <div className="nb-vlanrow__label">Tagged</div>
            <div className="nb-vlanrow__chips">
              {port.tagged_vlans.length === 0 ? <span className="nb-muted">none</span> :
                port.tagged_vlans.map(v => <VlanChip key={v} vlan={v} theme={theme} onRemove={isAdmin ? () => {} : null} />)}
              {isAdmin && <button className="nb-vchip nb-vchip--add"><Icon name="plus" size={10} /> add</button>}
            </div>
          </div>
        </Section>

        <Section title="Live config" right={<button className="nb-linkbtn" onClick={onRefetch}><Icon name="refresh" size={12} /> Refetch</button>}>
          <pre className="nb-config"><code>{renderConfigSnippet(device, port)}</code></pre>
          <div className="nb-portpanel__lastfetch">last fetched 8s ago · cache TTL 30s</div>
        </Section>

        <Section title="Services">
          <div className="nb-services">
            {Object.entries(port.services).map(([k, on]) => (
              <span key={k} className={`nb-service ${on ? 'is-on' : ''}`}>
                <StatusDot state={on ? 'up' : 'off'} size={6} />
                <span>{k.toUpperCase()}</span>
              </span>
            ))}
          </div>
          {isAdmin && <div className="nb-portpanel__hint">Disabling a service may affect routing scope. A confirmation will be required.</div>}
        </Section>

        <Section title="Pending requests" defaultOpen={pending.length > 0}>
          {pending.length === 0 ? <div className="nb-muted">No open requests on this port.</div> :
            pending.map(req => (
              <div key={req.id} className="nb-pendinline">
                <div className="nb-pendinline__head">
                  <span className="nb-mono">#{req.id}</span> · @{req.requested_by} · {timeAgo(req.created_at)}
                </div>
                <Diff before={portToDiff(port)} after={mergeChange(port, req.requested_changes)} compact />
                {isAdmin && (
                  <div className="nb-pendinline__actions">
                    <Button kind="primary" size="sm" icon="check" onClick={() => onApply(req)}>Approve & apply</Button>
                    <Button kind="ghost" size="sm" onClick={() => onReject(req)}>Reject</Button>
                  </div>
                )}
              </div>
            ))
          }
        </Section>

        <Section title="History">
          {portAudit.length === 0 ? <div className="nb-muted">No recent activity on this port.</div> :
            <ul className="nb-history">
              {portAudit.map(a => (
                <li key={a.id}>
                  <span className="nb-history__when">{timeAgoMin(a.ago_minutes)}</span>
                  <span className="nb-history__who">@{a.user}</span>
                  <span className="nb-history__what">{a.summary}</span>
                </li>
              ))}
            </ul>
          }
        </Section>
      </div>

      <div className="nb-portpanel__foot">
        {isAdmin ? (
          <>
            <Button kind="primary" icon="edit" onClick={onAdminEdit}>Edit directly</Button>
            {pending.length > 0 && <Button kind="success" icon="check" onClick={() => onApply(pending[0])}>Apply pending</Button>}
            <Button kind="ghost" icon="refresh" onClick={onRefetch}>Refetch</Button>
          </>
        ) : (
          <Button kind="primary" icon="send" onClick={onOpenRequest}>Request change <Kbd>r</Kbd></Button>
        )}
      </div>
    </aside>
  );
}

// ---------- Request change modal ----------
function RequestModal({ open, device, port, theme, vlanOptions, onClose, onSubmit }) {
  const [untagged, setUntagged] = useS2(port?.untagged_vlan || 100);
  const [tagged, setTagged] = useS2(port?.tagged_vlans || []);
  const [host, setHost] = useS2(port?.host_model || '');
  const [bmc, setBmc] = useS2(port?.bmc_ip || '');
  const [notes, setNotes] = useS2(port?.notes || '');
  const [reason, setReason] = useS2('');
  useE2(() => {
    if (open && port) {
      setUntagged(port.untagged_vlan); setTagged(port.tagged_vlans);
      setHost(port.host_model); setBmc(port.bmc_ip); setNotes(port.notes); setReason('');
    }
  }, [open, port?.name]);

  if (!open || !port) return null;

  const valid = !!reason.trim();
  const ipValid = !bmc || /^\d{1,3}(\.\d{1,3}){3}$/.test(bmc);

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Request port change"
      subtitle={`${device.name} · ${port.name}`}
      width={620}
      footer={
        <>
          <Button kind="ghost" onClick={onClose}>Cancel</Button>
          <Button kind="primary" icon="send" disabled={!valid || !ipValid} onClick={() => onSubmit({ untagged_vlan: untagged, tagged_vlans: tagged, host_model: host, bmc_ip: bmc, notes, reason })}>Submit request</Button>
        </>
      }
    >
      <div className="nb-form">
        <div className="nb-form__row">
          <label className="nb-field">
            <span>Untagged VLAN</span>
            <div className="nb-vlanpick">
              <input type="number" value={untagged} onChange={e => setUntagged(parseInt(e.target.value) || 0)} />
              <div className="nb-vlanpick__suggest">
                {vlanOptions.map(v => (
                  <button key={v} type="button" className={`nb-vchip ${untagged === v ? 'is-on' : ''}`}
                    style={{ '--vlan': vlanColor(v, theme), '--vlan-muted': vlanColorMuted(v, theme) }}
                    onClick={() => setUntagged(v)}>
                    <span className="nb-vchip__dot" /><span className="nb-vchip__num">{v}</span>
                  </button>
                ))}
              </div>
            </div>
          </label>
        </div>
        <div className="nb-form__row">
          <label className="nb-field">
            <span>Tagged VLANs (trunk)</span>
            <div className="nb-vlanpick__suggest">
              {vlanOptions.filter(v => v !== untagged).map(v => {
                const on = tagged.includes(v);
                return (
                  <button key={v} type="button" className={`nb-vchip ${on ? 'is-on' : ''}`}
                    style={{ '--vlan': vlanColor(v, theme), '--vlan-muted': vlanColorMuted(v, theme) }}
                    onClick={() => setTagged(t => on ? t.filter(x => x !== v) : [...t, v])}>
                    <span className="nb-vchip__dot" /><span className="nb-vchip__num">{v}</span>
                  </button>
                );
              })}
            </div>
          </label>
        </div>
        <div className="nb-form__row nb-form__row--2">
          <label className="nb-field">
            <span>Host model</span>
            <input value={host} onChange={e => setHost(e.target.value)} placeholder="e.g. Dell R740" />
          </label>
          <label className="nb-field">
            <span>BMC IP</span>
            <input value={bmc} onChange={e => setBmc(e.target.value)} placeholder="10.0.0.55" className="nb-mono" />
            {!ipValid && <span className="nb-field__err">Use dotted-quad format.</span>}
          </label>
        </div>
        <div className="nb-form__row">
          <label className="nb-field">
            <span>Notes <em>(optional)</em></span>
            <textarea value={notes} onChange={e => setNotes(e.target.value)} rows={2} />
          </label>
        </div>
        <div className="nb-form__row">
          <label className="nb-field">
            <span>Reason for change <em>(required)</em></span>
            <textarea value={reason} onChange={e => setReason(e.target.value)} rows={3} placeholder="What's this for? Tickets, dates, who's affected." />
          </label>
        </div>
      </div>
    </Modal>
  );
}

// ---------- Diff helpers ----------
function portToDiff(p) {
  return {
    untagged_vlan: p.untagged_vlan,
    tagged_vlans: [...p.tagged_vlans],
    host_model: p.host_model,
    bmc_ip: p.bmc_ip,
    notes: p.notes,
  };
}
function mergeChange(p, change) {
  return {
    untagged_vlan: change.untagged_vlan ?? p.untagged_vlan,
    tagged_vlans: change.tagged_vlans ?? p.tagged_vlans,
    host_model: change.host_model ?? p.host_model,
    bmc_ip: change.bmc_ip ?? p.bmc_ip,
    notes: change.notes ?? p.notes,
  };
}

function Diff({ before, after, compact }) {
  const keys = ['untagged_vlan', 'tagged_vlans', 'host_model', 'bmc_ip', 'notes'];
  const labels = { untagged_vlan: 'untagged', tagged_vlans: 'tagged', host_model: 'host', bmc_ip: 'bmc', notes: 'notes' };
  const fmt = (v) => Array.isArray(v) ? (v.length ? v.join(',') : '—') : (v === '' || v == null ? '—' : v);
  return (
    <div className={`nb-diff ${compact ? 'nb-diff--compact' : ''}`}>
      {keys.map(k => {
        const a = JSON.stringify(before[k]); const b = JSON.stringify(after[k]);
        const changed = a !== b;
        return (
          <div key={k} className={`nb-diffrow ${changed ? 'is-changed' : ''}`}>
            <span className="nb-diffrow__key nb-mono">{labels[k]}</span>
            <span className="nb-diffrow__before"><span className="nb-diffmark">-</span><span>{fmt(before[k])}</span></span>
            <span className="nb-diffrow__after"><span className="nb-diffmark">+</span><span>{fmt(after[k])}</span></span>
          </div>
        );
      })}
    </div>
  );
}

// ---------- Per-platform config snippet (read-only display) ----------
function renderConfigSnippet(device, port) {
  const v = port.untagged_vlan;
  const tagged = port.tagged_vlans;
  const desc = port.description || '';
  if (device.platform === 'mikrotik') {
    return [
      `/interface ethernet`,
      `set [find name="${port.name}"] comment="${desc}" ${port.admin_up ? 'disabled=no' : 'disabled=yes'}`,
      `/interface bridge vlan`,
      `add bridge=br1 vlan-ids=${v} untagged="${port.name}"`,
      ...tagged.map(t => `add bridge=br1 vlan-ids=${t} tagged="${port.name}"`),
    ].join('\n');
  }
  if (device.platform === 'arista') {
    return [
      `interface ${port.name}`,
      `   description ${desc}`,
      `   ${port.admin_up ? 'no shutdown' : 'shutdown'}`,
      `   switchport mode ${tagged.length ? 'trunk' : 'access'}`,
      tagged.length ? `   switchport trunk native vlan ${v}` : `   switchport access vlan ${v}`,
      tagged.length ? `   switchport trunk allowed vlan ${[v, ...tagged].join(',')}` : null,
    ].filter(Boolean).join('\n');
  }
  if (device.platform === 'pica8') {
    return [
      `set interface ${port.name} description "${desc}"`,
      `set interface ${port.name} ${port.admin_up ? 'enable' : 'disable'}`,
      `set vlans v${v} interface ${port.name} untagged`,
      ...tagged.map(t => `set vlans v${t} interface ${port.name} tagged`),
    ].join('\n');
  }
  if (device.platform === 'freebsd') {
    return [
      `# /etc/rc.conf snippet`,
      `ifconfig_${port.name}="up"`,
      `# vlans on ${port.name}: ${[v, ...tagged].join(',')}`,
      `ifconfig_${port.name}_${v}="inet 10.0.${v}.1/24"`,
    ].join('\n');
  }
  return '';
}

// ---------- Device detail screen ----------
function DeviceDetail({ device, ports, allRequests, audit, theme, user, selectedPort, setSelectedPort, openTab, setOpenTab, onOpenRequest, onApplyRequest, onRejectRequest, onAdminEdit, onRefetch, onPanelClose }) {
  return (
    <div className="nb-devdetail">
      <div className="nb-devdetail__head">
        <div className="nb-devdetail__title">
          <span className={`nb-platicon nb-platicon--${device.platform} nb-platicon--lg`}>
            <Icon name={device.role === 'spine' ? 'spine' : device.role === 'router' ? 'router' : device.role === 'vpn' ? 'vpn' : 'leaf'} size={16} />
          </span>
          <div>
            <div className="nb-devdetail__name">{device.name}</div>
            <div className="nb-devdetail__sub">
              <span className="nb-mono">{device.platform}</span>
              <span>·</span>
              <span>{device.model}</span>
              <span>·</span>
              <span className="nb-mono">{device.mgmt_ip}</span>
              <span>·</span>
              <span><StatusDot state={device.reachable ? 'up' : 'down'} size={7} /> {device.reachable ? 'reachable' : 'unreachable'}</span>
            </div>
          </div>
        </div>
        <div className="nb-tabs">
          <button className={`nb-tab ${openTab === 'ports' ? 'is-on' : ''}`} onClick={() => setOpenTab('ports')}>Ports</button>
          <button className={`nb-tab ${openTab === 'config' ? 'is-on' : ''}`} onClick={() => setOpenTab('config')}>
            Config {user.role === 'admin' ? '' : <Icon name="config" size={12} />}
          </button>
        </div>
      </div>

      {openTab === 'ports' && (
        <div className="nb-devdetail__split">
          <div className="nb-devdetail__top">
            <Switch3D device={device} ports={ports} theme={theme} selectedPort={selectedPort}
              onPick={(p) => setSelectedPort(p.name)} />
          </div>
          <div className="nb-devdetail__bottom">
            <PortStrip device={device} ports={ports} requests={allRequests} selected={selectedPort} theme={theme}
              onSelect={(name) => setSelectedPort(name)} />
          </div>
        </div>
      )}
      {openTab === 'config' && (
        <DeviceConfigView device={device} ports={ports} user={user} />
      )}
    </div>
  );
}

window.PortStrip = PortStrip;
window.PortPanel = PortPanel;
window.RequestModal = RequestModal;
window.DeviceDetail = DeviceDetail;
window.Diff = Diff;
window.portToDiff = portToDiff;
window.mergeChange = mergeChange;
window.renderConfigSnippet = renderConfigSnippet;
window.VlanChip = VlanChip;
