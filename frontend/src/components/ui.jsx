import { useEffect } from 'react';
import { initials } from '../utils/format';

const STATUS = {
  COMPLETED: ['Successful', 'b-green'],
  APPROVED: ['Approved', 'b-green'],
  UNDER_REVIEW: ['Under Review', 'b-amber'],
  REVIEW: ['Review', 'b-amber'],
  BLOCKED: ['Blocked', 'b-red'],
  DECLINED: ['Declined', 'b-red'],
  CANCELLED: ['Cancelled', 'b-slate'],
  EXPIRED: ['Expired', 'b-slate'],
  USER_CONFIRMATION_PENDING: ['Confirmation pending', 'b-amber'],
  PROCESSING: ['Processing', 'b-blue'],
  LOCKED: ['Account locked', 'b-red'],
  OPEN: ['Open', 'b-red'],
  INVESTIGATING: ['Investigating', 'b-amber'],
  RESOLVED: ['Resolved', 'b-green'],
  CONFIRMED_FRAUD: ['Confirmed fraud', 'b-red'],
  FALSE_POSITIVE: ['False positive', 'b-green'],
  HIGH: ['High', 'b-red'],
  MEDIUM: ['Medium', 'b-amber'],
  LOW: ['Low', 'b-slate'],
  RUNNING: ['Running', 'b-green'],
  STOPPED: ['Stopped', 'b-slate'],
  FAILED: ['Failed', 'b-red'],
};

export function StatusBadge({ status, label }) {
  const [text, cls] = STATUS[status] || [status?.replaceAll('_', ' ') || '—', 'b-slate'];
  return <span className={`badge badge-dot ${cls}`}>{label || text}</span>;
}

/** The shared final-outcome label, e.g. "USER DENIED – PAYMENT BLOCKED" (same text on all four dashboards). */
export function OutcomeBadge({ label }) {
  if (!label) return null;
  const cls = label.includes('SUCCESSFUL') ? 'b-green'
    : label.includes('BLOCKED') || label === 'DECLINED' ? 'b-red'
      : label === 'CANCELLED' || label.startsWith('EXPIRED') ? 'b-slate' : 'b-amber';
  return <span className={`badge badge-dot ${cls}`}>{label}</span>;
}

export function scoreColor(score) {
  if (score == null) return '#CBD5E1';
  if (score >= 70) return '#EF4444';
  if (score >= 40) return '#F59E0B';
  return '#22C55E';
}

export function RiskScore({ score }) {
  if (score == null) return <span className="muted">—</span>;
  return (
    <span className="score" title={`Risk score ${score}/100`}>
      <span className="score-num" style={{ color: scoreColor(score) }}>{score}</span>
      <span className="score-bar"><span style={{ width: `${score}%`, background: scoreColor(score) }} /></span>
    </span>
  );
}

export function RuleChips({ rules }) {
  if (!rules?.length) return <span className="muted small">none</span>;
  return rules.map((r) => {
    const code = typeof r === 'string' ? r : r.code;
    const title = typeof r === 'string' ? code : `${r.name || code}: ${r.reason || ''}`;
    return <span key={code} className="rule-chip" title={title}>{code}</span>;
  });
}

export function StatCard({ icon, label, value, sub, tone = 'blue' }) {
  return (
    <div className="card stat">
      <div className={`stat-icon tone-${tone}`}>{icon}</div>
      <div style={{ minWidth: 0 }}>
        <div className="stat-label">{label}</div>
        <div className="stat-value">{value}</div>
        {sub && <div className="stat-sub">{sub}</div>}
      </div>
    </div>
  );
}

export function Avatar({ name, tone = 'blue' }) {
  return <div className={`avatar tone-${tone}`}>{initials(name)}</div>;
}

export function Loading({ text = 'Loading…' }) {
  return <div className="loading"><div className="spinner" />{text}</div>;
}

export function Empty({ icon = '📭', title, children }) {
  return (
    <div className="empty">
      <div className="empty-icon">{icon}</div>
      <div style={{ fontWeight: 600, color: 'var(--text)' }}>{title}</div>
      {children && <div className="small mt-8">{children}</div>}
    </div>
  );
}

export function ErrorNote({ error }) {
  if (!error) return null;
  return <div className="notice notice-danger">⚠ {error}</div>;
}

export function PageHead({ title, subtitle, children }) {
  return (
    <div className="page-head">
      <div>
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {children && <div className="row wrap">{children}</div>}
    </div>
  );
}

export function Pagination({ meta, onPage }) {
  if (!meta || meta.pages <= 1) return null;
  return (
    <div className="pagination">
      <span className="muted small">Page {meta.page} of {meta.pages} · {meta.total} records</span>
      <div className="row">
        <button className="btn btn-ghost btn-sm" disabled={meta.page <= 1} onClick={() => onPage(meta.page - 1)}>← Prev</button>
        <button className="btn btn-ghost btn-sm" disabled={meta.page >= meta.pages} onClick={() => onPage(meta.page + 1)}>Next →</button>
      </div>
    </div>
  );
}

export function Modal({ title, onClose, children, footer, large }) {
  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${large ? 'modal-lg' : ''}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

export function Toggle({ checked, onChange, disabled, label }) {
  return (
    <label className="toggle" title={label}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} aria-label={label} />
      <span />
    </label>
  );
}

export function Field({ label, hint, children }) {
  return (
    <div className="field">
      {label && <label>{label}</label>}
      {children}
      {hint && <span className="hint">{hint}</span>}
    </div>
  );
}
