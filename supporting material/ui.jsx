// Northbound — UI primitives, toast, keyboard, layout helpers
const { useRef, useLayoutEffect, useCallback } = React;

// ---------- Toast ----------
const ToastContext = React.createContext(null);
function ToastProvider({ children }) {
  const [toasts, setToasts] = React.useState([]);
  const push = React.useCallback((t) => {
    const id = Math.random().toString(36).slice(2);
    setToasts(ts => [...ts, { id, kind: 'info', ...t }]);
    setTimeout(() => setToasts(ts => ts.filter(x => x.id !== id)), t.duration || 3200);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="nb-toast-stack">
        {toasts.map(t => (
          <div key={t.id} className={`nb-toast nb-toast--${t.kind}`}>
            <div className="nb-toast__dot" />
            <div className="nb-toast__body">
              {t.title && <div className="nb-toast__title">{t.title}</div>}
              {t.message && <div className="nb-toast__msg">{t.message}</div>}
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
const useToast = () => React.useContext(ToastContext);

// ---------- Keyboard ----------
function useHotkeys(map, deps = []) {
  React.useEffect(() => {
    const onKey = (e) => {
      const tag = e.target.tagName;
      if (['INPUT', 'TEXTAREA'].includes(tag) && e.key !== 'Escape') return;
      const key = (e.metaKey ? 'meta+' : '') + (e.ctrlKey ? 'ctrl+' : '') + (e.shiftKey ? 'shift+' : '') + e.key.toLowerCase();
      const fn = map[key] || map[e.key.toLowerCase()];
      if (fn) {
        const result = fn(e);
        if (result !== false) e.preventDefault();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line
  }, deps);
}

// Sequence keys (e.g. g then l)
function useSequenceHotkeys(map, deps = []) {
  React.useEffect(() => {
    let prefix = '';
    let timer = null;
    const onKey = (e) => {
      const tag = e.target.tagName;
      if (['INPUT', 'TEXTAREA'].includes(tag)) return;
      const k = e.key.toLowerCase();
      if (prefix) {
        const combo = prefix + ' ' + k;
        if (map[combo]) { map[combo](); prefix = ''; clearTimeout(timer); e.preventDefault(); return; }
        prefix = '';
        clearTimeout(timer);
      }
      // start prefix only on plain g (no mod)
      if (k === 'g' && !e.metaKey && !e.ctrlKey && !e.altKey) {
        prefix = 'g';
        timer = setTimeout(() => { prefix = ''; }, 900);
        e.preventDefault();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line
  }, deps);
}

// ---------- Icon glyphs (small monoline, original) ----------
function Icon({ name, size = 16, ...rest }) {
  const s = size;
  const stroke = 'currentColor';
  const sw = 1.5;
  const common = { width: s, height: s, viewBox: '0 0 24 24', fill: 'none', stroke, strokeWidth: sw, strokeLinecap: 'round', strokeLinejoin: 'round', ...rest };
  switch (name) {
    case 'compass-n': return (<svg {...common}><circle cx="12" cy="12" r="9"/><path d="M12 4l3 9-3 -2-3 2z" fill="currentColor" stroke="none"/></svg>);
    case 'search': return (<svg {...common}><circle cx="11" cy="11" r="6"/><path d="m20 20-3.5-3.5"/></svg>);
    case 'sun': return (<svg {...common}><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>);
    case 'moon': return (<svg {...common}><path d="M21 13a9 9 0 0 1-12-12 9 9 0 1 0 12 12z"/></svg>);
    case 'chev-r': return (<svg {...common}><path d="m9 6 6 6-6 6"/></svg>);
    case 'chev-d': return (<svg {...common}><path d="m6 9 6 6 6-6"/></svg>);
    case 'plus': return (<svg {...common}><path d="M12 5v14M5 12h14"/></svg>);
    case 'x': return (<svg {...common}><path d="m6 6 12 12M18 6 6 18"/></svg>);
    case 'check': return (<svg {...common}><path d="m4 12 5 5L20 6"/></svg>);
    case 'edit': return (<svg {...common}><path d="M4 20h4l10-10-4-4L4 16v4z"/><path d="m13 7 4 4"/></svg>);
    case 'send': return (<svg {...common}><path d="m4 12 16-8-8 16-2-6-6-2z"/></svg>);
    case 'refresh': return (<svg {...common}><path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 4v4h-4"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 20v-4h4"/></svg>);
    case 'kbd': return (<svg {...common}><rect x="2" y="6" width="20" height="12" rx="2"/><path d="M7 10h.01M11 10h.01M15 10h.01M7 14h10"/></svg>);
    case 'logout': return (<svg {...common}><path d="M9 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H10"/></svg>);
    case 'spine': return (<svg {...common}><rect x="3" y="3" width="18" height="6" rx="1"/><path d="M7 9v3M12 9v3M17 9v3"/><rect x="3" y="14" width="6" height="6" rx="1"/><rect x="10" y="14" width="6" height="6" rx="1"/><rect x="17" y="14" width="4" height="6" rx="1"/></svg>);
    case 'leaf': return (<svg {...common}><rect x="3" y="6" width="18" height="6" rx="1"/><path d="M5 8h.01M8 8h.01M11 8h.01M14 8h.01M17 8h.01M5 11h.01M8 11h.01M11 11h.01M14 11h.01M17 11h.01"/><path d="M12 12v8"/></svg>);
    case 'router': return (<svg {...common}><rect x="3" y="11" width="18" height="8" rx="1"/><path d="M7 15h10M12 4v7M9 7l3-3 3 3"/></svg>);
    case 'vpn': return (<svg {...common}><path d="M12 2 4 6v6c0 5 3.5 8.5 8 10 4.5-1.5 8-5 8-10V6l-8-4z"/><path d="m9 12 2 2 4-4"/></svg>);
    case 'reset': return (<svg {...common}><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/></svg>);
    case 'history': return (<svg {...common}><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/></svg>);
    case 'config': return (<svg {...common}><path d="M4 6h16M4 12h16M4 18h10"/></svg>);
    case 'queue': return (<svg {...common}><rect x="3" y="5" width="18" height="3" rx="1"/><rect x="3" y="11" width="18" height="3" rx="1"/><rect x="3" y="17" width="12" height="3" rx="1"/></svg>);
    case 'inbox': return (<svg {...common}><path d="M3 12v6a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-6"/><path d="M3 12h6l1 2h4l1-2h6"/><path d="m7 9 5-5 5 5"/></svg>);
    case 'arrow-r': return (<svg {...common}><path d="M5 12h14M13 5l7 7-7 7"/></svg>);
    case 'dot': return (<svg viewBox="0 0 8 8" width={s} height={s} {...rest}><circle cx="4" cy="4" r="3" fill="currentColor"/></svg>);
    default: return null;
  }
}

// ---------- Wordmark ----------
function Wordmark({ size = 20, glyph = true }) {
  return (
    <span className="nb-wordmark" style={{ fontSize: size }}>
      {glyph && (
        <span className="nb-wordmark__glyph" aria-hidden>
          <svg width={size * 1.05} height={size * 1.05} viewBox="0 0 24 24">
            <circle cx="12" cy="12" r="10.2" fill="none" stroke="currentColor" strokeOpacity="0.55" strokeWidth="1.2" />
            <path d="M12 3.5 L14.6 12.6 L12 11 L9.4 12.6 Z" fill="currentColor" />
            <path d="M12 20.5 L9.4 11.4 L12 13 L14.6 11.4 Z" fill="currentColor" fillOpacity="0.35" />
            <text x="12" y="22.6" textAnchor="middle" fontFamily="ui-monospace, monospace" fontSize="3.6" fill="currentColor" fillOpacity="0.6">N</text>
          </svg>
        </span>
      )}
      <span className="nb-wordmark__text">Northbound</span>
    </span>
  );
}

// ---------- Modal ----------
function Modal({ open, onClose, title, subtitle, children, footer, width = 520 }) {
  React.useEffect(() => {
    if (!open) return;
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="nb-modal-back" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="nb-modal" style={{ width }}>
        {(title || subtitle) && (
          <div className="nb-modal__head">
            <div>
              {title && <div className="nb-modal__title">{title}</div>}
              {subtitle && <div className="nb-modal__sub">{subtitle}</div>}
            </div>
            <button className="nb-iconbtn" onClick={onClose} aria-label="Close"><Icon name="x" /></button>
          </div>
        )}
        <div className="nb-modal__body">{children}</div>
        {footer && <div className="nb-modal__foot">{footer}</div>}
      </div>
    </div>
  );
}

// ---------- Status dot ----------
function StatusDot({ state, size = 8, pulse = false }) {
  const cls = `nb-dot nb-dot--${state}` + (pulse ? ' nb-dot--pulse' : '');
  return <span className={cls} style={{ width: size, height: size }} />;
}

// ---------- Buttons ----------
function Button({ kind = 'ghost', size = 'md', icon, children, ...rest }) {
  return (
    <button className={`nb-btn nb-btn--${kind} nb-btn--${size}`} {...rest}>
      {icon && <Icon name={icon} size={14} />}
      {children}
    </button>
  );
}

// ---------- Kbd ----------
function Kbd({ children }) { return <span className="nb-kbd">{children}</span>; }

// ---------- Section header (collapsible) ----------
function Section({ title, defaultOpen = true, right, children }) {
  const [open, setOpen] = React.useState(defaultOpen);
  return (
    <div className="nb-section">
      <button className="nb-section__head" onClick={() => setOpen(o => !o)}>
        <Icon name={open ? 'chev-d' : 'chev-r'} size={14} />
        <span className="nb-section__title">{title}</span>
        <span className="nb-section__right" onClick={e => e.stopPropagation()}>{right}</span>
      </button>
      {open && <div className="nb-section__body">{children}</div>}
    </div>
  );
}

// ---------- Time formatting ----------
function timeAgo(ms) {
  const diff = Date.now() - ms;
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.floor(h / 24);
  return `${d} d ago`;
}
function timeAgoMin(min) {
  if (min < 1) return 'just now';
  if (min < 60) return `${min}m`;
  const h = Math.floor(min / 60); if (h < 24) return `${h}h`;
  return `${Math.floor(h/24)}d`;
}

Object.assign(window, {
  ToastProvider, useToast, useHotkeys, useSequenceHotkeys, Icon, Wordmark,
  Modal, StatusDot, Button, Kbd, Section, timeAgo, timeAgoMin,
});
