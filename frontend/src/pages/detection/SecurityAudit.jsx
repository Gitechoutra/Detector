import { useState } from 'react';
import { errorMessage, get } from '../../api/client';
import { useToast } from '../../components/Toast';
import { Empty, ErrorNote, Loading, PageHead, Pagination, StatusBadge } from '../../components/ui';
import { useApi } from '../../hooks';
import { dateTime } from '../../utils/format';

const TABS = [['events', 'Security events'], ['logins', 'Login attempts'], ['audit', 'Audit trail']];

function Events() {
  const [f, setF] = useState({ severity: '', event_type: '', source: '', page: 1 });
  const { data, error } = useApi('/security/events', f, { interval: 4000 });
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value, page: 1 }));
  return (
    <>
      <div className="filters">
        <select className="input input-sm" value={f.severity} onChange={set('severity')}><option value="">Any severity</option><option>HIGH</option><option>MEDIUM</option><option>LOW</option></select>
        <select className="input input-sm" value={f.event_type} onChange={set('event_type')}>
          <option value="">Any event</option>
          {['LOGIN_FAILED', 'ACCOUNT_LOCKED', 'NEW_DEVICE_LOGIN', 'UNUSUAL_LOCATION_LOGIN', 'LOGIN_SUCCESS', 'OTP_FAILED', 'STEP_UP_VERIFIED'].map((t) => <option key={t} value={t}>{t.replaceAll('_', ' ')}</option>)}
        </select>
        <select className="input input-sm" value={f.source} onChange={set('source')}><option value="">Manual + simulated</option><option value="manual">Manual</option><option value="simulated">Simulated</option></select>
      </div>
      <ErrorNote error={error} />
      {!data ? <Loading /> : !data.items.length ? <Empty title="No security events" /> : (
        <div className="table-wrap"><table className="table">
          <thead><tr><th>When</th><th>Severity</th><th>Event</th><th>User</th><th>Detail</th><th>City</th><th>IP</th></tr></thead>
          <tbody>{data.items.map((e) => (
            <tr key={e.id}>
              <td className="small nowrap">{dateTime(e.created_at)}</td><td><StatusBadge status={e.severity} /></td>
              <td className="small">{e.event_type.replaceAll('_', ' ')}{e.is_simulated && <div><span className="badge b-purple">sim</span></div>}</td>
              <td className="small">{e.user}</td><td className="small muted">{e.description}</td><td className="small">{e.city}</td><td className="mono small">{e.ip_address}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
      <Pagination meta={data?.meta} onPage={(page) => setF((x) => ({ ...x, page }))} />
    </>
  );
}

function Logins() {
  const [f, setF] = useState({ success: '', source: '', page: 1 });
  const { data, error } = useApi('/security/login-attempts', f, { interval: 4000 });
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value, page: 1 }));
  return (
    <>
      <div className="filters">
        <select className="input input-sm" value={f.success} onChange={set('success')}><option value="">All attempts</option><option value="1">Successful</option><option value="0">Failed</option></select>
        <select className="input input-sm" value={f.source} onChange={set('source')}><option value="">Manual + simulated</option><option value="manual">Manual</option><option value="simulated">Simulated</option></select>
      </div>
      <ErrorNote error={error} />
      {!data ? <Loading /> : !data.items.length ? <Empty title="No login attempts" /> : (
        <div className="table-wrap"><table className="table">
          <thead><tr><th>When</th><th>Account</th><th>Result</th><th>City</th><th>IP</th><th>Device</th></tr></thead>
          <tbody>{data.items.map((l) => (
            <tr key={l.id}>
              <td className="small nowrap">{dateTime(l.created_at)}</td>
              <td className="small">{l.user || <span className="muted">{l.email}</span>}{l.is_simulated && <span className="badge b-purple" style={{ marginLeft: 6 }}>sim</span>}</td>
              <td>{l.success ? <span className="badge b-green">Success</span> : <span className="badge b-red">{(l.failure_reason || 'Failed').replaceAll('_', ' ').toLowerCase()}</span>}</td>
              <td className="small">{l.city}</td><td className="mono small">{l.ip_address}</td>
              <td>{l.is_new_device ? <span className="badge b-amber">New device</span> : <span className="muted small">—</span>}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
      <Pagination meta={data?.meta} onPage={(page) => setF((x) => ({ ...x, page }))} />
    </>
  );
}

function Audit() {
  const toast = useToast();
  const [page, setPage] = useState(1);
  const { data, error } = useApi('/security/audit-logs', { page });
  const [chain, setChain] = useState(null);
  const verify = async () => {
    try {
      setChain(await get('/security/audit/verify'));
    } catch (e) {
      toast(errorMessage(e), 'error');
    }
  };
  return (
    <>
      <div className="filters">
        <button className="btn btn-primary btn-sm" onClick={verify}>🔗 Verify hash chain</button>
        {chain && (chain.valid
          ? <span className="badge b-green">✓ Intact – {chain.checked} entries verified</span>
          : <span className="badge b-red">✕ Broken at entry #{chain.broken_at_id}</span>)}
        <span className="muted small">Each entry stores SHA-256(previous hash + content). DB triggers reject UPDATE/DELETE.</span>
      </div>
      <ErrorNote error={error} />
      {!data ? <Loading /> : !data.items.length ? <Empty title="No audit entries" /> : (
        <div className="table-wrap"><table className="table">
          <thead><tr><th>#</th><th>When</th><th>Actor</th><th>Action</th><th>Entity</th><th>Details</th><th>Hash</th></tr></thead>
          <tbody>{data.items.map((a) => (
            <tr key={a.id}>
              <td className="small">{a.id}</td><td className="small nowrap">{dateTime(a.created_at)}</td>
              <td className="small">{a.actor}<div className="muted">{a.actor_role}</div></td>
              <td><span className="badge b-purple">{a.action}</span></td>
              <td className="small">{a.entity_type} {a.entity_id}</td>
              <td className="mono small" style={{ maxWidth: 320, wordBreak: 'break-word' }}>{JSON.stringify(a.details)}</td>
              <td className="mono small muted" title={a.row_hash}>{a.row_hash.slice(0, 10)}…</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
      <Pagination meta={data?.meta} onPage={setPage} />
    </>
  );
}

export default function SecurityAudit() {
  const [tab, setTab] = useState('events');
  return (
    <>
      <PageHead title="Security & audit" subtitle="Login monitoring, security events and the tamper-evident audit trail." />
      <div className="segmented" style={{ marginBottom: 16 }}>
        {TABS.map(([k, l]) => <button key={k} className={tab === k ? 'active' : ''} onClick={() => setTab(k)}>{l}</button>)}
      </div>
      <div className="card">
        {tab === 'events' && <Events />}
        {tab === 'logins' && <Logins />}
        {tab === 'audit' && <Audit />}
      </div>
    </>
  );
}
