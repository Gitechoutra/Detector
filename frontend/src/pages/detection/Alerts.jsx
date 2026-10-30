import { useState } from 'react';
import { Link } from 'react-router-dom';
import { errorMessage, patch } from '../../api/client';
import { useToast } from '../../components/Toast';
import { Empty, ErrorNote, Field, Loading, Modal, PageHead, Pagination, RiskScore, RuleChips, StatusBadge } from '../../components/ui';
import { useApi } from '../../hooks';
import { dateTime, money, timeAgo } from '../../utils/format';

const TYPE_LABEL = { TRANSACTION_REVIEW: 'Review', TRANSACTION_BLOCKED: 'Blocked txn', SECURITY: 'Security' };

export default function Alerts() {
  const toast = useToast();
  const [filters, setFilters] = useState({ status: '', severity: '', alert_type: '', source: '', page: 1 });
  const { data, error, loading, reload } = useApi('/alerts', filters, { interval: 3000 });
  const [open, setOpen] = useState(null);
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setFilters((f) => ({ ...f, [k]: e.target.value, page: 1 }));

  const act = async (action, extra = {}) => {
    setBusy(true);
    try {
      const res = await patch(`/alerts/${open.id}`, { action, notes: notes || null, ...extra });
      setOpen(res.data);
      setNotes('');
      toast('Alert updated.', 'success');
      reload(true);
    } catch (e) {
      toast(errorMessage(e), 'error');
    } finally {
      setBusy(false);
    }
  };

  const c = data?.counts || {};
  return (
    <>
      <PageHead title="Alerts & cases" subtitle="Assign, investigate, annotate and close alerts as confirmed fraud or false positive.">
        <span className="badge b-red">{c.OPEN || 0} open</span>
        <span className="badge b-amber">{c.INVESTIGATING || 0} investigating</span>
        <span className="badge b-green">{c.RESOLVED || 0} resolved</span>
      </PageHead>
      <div className="card">
        <div className="filters">
          <select className="input input-sm" value={filters.status} onChange={set('status')}>
            <option value="">Any status</option><option value="OPEN">Open</option><option value="INVESTIGATING">Investigating</option><option value="RESOLVED">Resolved</option>
          </select>
          <select className="input input-sm" value={filters.severity} onChange={set('severity')}>
            <option value="">Any severity</option><option value="HIGH">High</option><option value="MEDIUM">Medium</option>
          </select>
          <select className="input input-sm" value={filters.alert_type} onChange={set('alert_type')}>
            <option value="">Any type</option><option value="TRANSACTION_REVIEW">Transaction review</option>
            <option value="TRANSACTION_BLOCKED">Transaction blocked</option><option value="SECURITY">Security</option>
          </select>
          <select className="input input-sm" value={filters.source} onChange={set('source')}>
            <option value="">Manual + simulated</option><option value="manual">Manual</option><option value="simulated">Simulated</option>
          </select>
        </div>
        <ErrorNote error={error} />
        {loading && !data ? <Loading /> : !data?.items.length ? <Empty icon="✅" title="No alerts match" /> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Raised</th><th>Severity</th><th>Type</th><th>Alert</th><th>Score</th><th>Rules</th><th>Status</th><th>Assignee</th></tr></thead>
              <tbody>
                {data.items.map((a) => (
                  <tr key={a.id} className="clickable" onClick={() => setOpen(a)}>
                    <td className="small nowrap">{timeAgo(a.created_at)}</td>
                    <td><StatusBadge status={a.severity} /></td>
                    <td className="small">{TYPE_LABEL[a.alert_type]}{a.is_simulated && <div><span className="badge b-purple">sim</span></div>}</td>
                    <td className="small"><strong>{a.title}</strong><div className="muted">{a.txn_ref}</div></td>
                    <td><RiskScore score={a.risk_score} /></td>
                    <td><RuleChips rules={a.rules} /></td>
                    <td><StatusBadge status={a.status} />{a.resolution && <div className="mt-8"><StatusBadge status={a.resolution} /></div>}</td>
                    <td className="small">{a.assigned_to || <span className="muted">—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pagination meta={data?.meta} onPage={(page) => setFilters((f) => ({ ...f, page }))} />
      </div>

      {open && (
        <Modal large title={`Alert #${open.id}`} onClose={() => { setOpen(null); setNotes(''); }}>
          <div className="stack">
            <div className="row wrap"><StatusBadge status={open.severity} /><StatusBadge status={open.status} />{open.resolution && <StatusBadge status={open.resolution} />}</div>
            <div><h2>{open.title}</h2><p className="muted small mt-8">{open.message}</p></div>
            <dl className="kv">
              <dt>Raised</dt><dd>{dateTime(open.created_at)}</dd>
              <dt>Customer</dt><dd>{open.user || '—'}</dd>
              {open.transaction_id && <><dt>Transaction</dt><dd><Link to={`/detection/transactions/${open.transaction_id}`}>{open.txn_ref}</Link> · {money(open.amount)} · <StatusBadge status={open.txn_status} /></dd></>}
              <dt>Assigned to</dt><dd>{open.assigned_to || 'Unassigned'}</dd>
            </dl>
            {open.analyst_notes && <div className="card card-pad small" style={{ whiteSpace: 'pre-wrap', background: '#FAFBFC' }}>{open.analyst_notes}</div>}
            <Field label="Add a note">
              <textarea className="input" rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Investigation notes…" />
            </Field>
            <div className="row wrap">
              {open.status !== 'RESOLVED' ? (
                <>
                  {open.status === 'OPEN' && <button className="btn btn-ghost" disabled={busy} onClick={() => act('assign')}>Assign to me</button>}
                  <button className="btn btn-ghost" disabled={busy || !notes} onClick={() => act('note')}>Save note</button>
                  <button className="btn btn-danger" disabled={busy} onClick={() => act('resolve', { resolution: 'CONFIRMED_FRAUD' })}>Confirmed fraud</button>
                  <button className="btn btn-success" disabled={busy} onClick={() => act('resolve', { resolution: 'FALSE_POSITIVE' })}>False positive</button>
                </>
              ) : <button className="btn btn-ghost" disabled={busy} onClick={() => act('reopen')}>Reopen</button>}
            </div>
            {open.txn_status === 'UNDER_REVIEW' && (
              <p className="muted small">“Confirmed fraud” also declines the held payment. To release a genuine payment, use Approve on the <Link to={`/detection/transactions/${open.transaction_id}`}>investigation page</Link> (it re-runs every rule first).</p>
            )}
          </div>
        </Modal>
      )}
    </>
  );
}
