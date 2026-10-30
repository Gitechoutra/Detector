import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { get } from '../../api/client';
import { Empty, ErrorNote, Loading, PageHead, Pagination, RiskScore, RuleChips, StatusBadge } from '../../components/ui';
import { useApi } from '../../hooks';
import { money, METHOD_LABEL, timeOnly } from '../../utils/format';

const EMPTY = { date_from: '', date_to: '', status: '', risk_level: '', user_id: '', source: '', q: '', page: 1 };

export default function Monitor() {
  const navigate = useNavigate();
  const [filters, setFilters] = useState(EMPTY);
  const [users, setUsers] = useState([]);
  const [paused, setPaused] = useState(false);
  const { data, error, loading } = useApi('/detection/transactions', filters, { interval: paused ? 0 : 2000 });
  const live = useApi('/detection/live', { limit: 1 }, { interval: paused ? 0 : 2000 });
  const seen = useRef(null);
  const [fresh, setFresh] = useState(new Set());
  const [updatedAt, setUpdatedAt] = useState(null);

  useEffect(() => {
    get('/detection/users').then(setUsers).catch(() => {});
  }, []);

  // A filter change is not "new activity": forget what was seen so nothing flashes.
  useEffect(() => {
    seen.current = null;
  }, [filters]);

  // Highlight rows that appeared since the previous poll.
  useEffect(() => {
    if (!data) return;
    const ids = data.items.map((t) => t.id);
    if (seen.current) setFresh(new Set(ids.filter((id) => !seen.current.has(id))));
    seen.current = new Set([...(seen.current || []), ...ids]);
    setUpdatedAt(new Date());
  }, [data]);

  const set = (k) => (e) => setFilters((f) => ({ ...f, [k]: e.target.value, page: 1 }));
  const active = Object.entries(filters).some(([k, v]) => k !== 'page' && v);

  return (
    <>
      <PageHead title="Live transaction monitor" subtitle="Refreshes every 2 seconds. Colour bar = decision; click a row to investigate.">
        <span className="row small muted">
          {paused ? '⏸ Paused' : <><span className="live-dot" /> Live</>}
          {updatedAt && ` · ${updatedAt.toLocaleTimeString('en-IN')}`}
        </span>
        <span className="badge b-red">{live.data?.open_alerts ?? 0} open alerts</span>
        <span className="badge b-amber">{live.data?.awaiting_analyst ?? 0} awaiting analyst</span>
        <button className="btn btn-ghost btn-sm" onClick={() => setPaused(!paused)}>{paused ? '▶ Resume' : '⏸ Pause'}</button>
      </PageHead>

      <div className="card">
        <div className="filters">
          <input className="input input-sm" placeholder="Search ref…" value={filters.q} onChange={set('q')} style={{ width: 150 }} />
          <input type="date" className="input input-sm" value={filters.date_from} onChange={set('date_from')} aria-label="From" />
          <input type="date" className="input input-sm" value={filters.date_to} onChange={set('date_to')} aria-label="To" />
          <select className="input input-sm" value={filters.status} onChange={set('status')}>
            <option value="">Any status</option><option value="COMPLETED">Approved</option><option value="UNDER_REVIEW">Under review</option>
            <option value="BLOCKED">Blocked</option><option value="DECLINED">Declined</option><option value="CANCELLED">Cancelled</option>
          </select>
          <select className="input input-sm" value={filters.risk_level} onChange={set('risk_level')}>
            <option value="">Any risk level</option><option value="APPROVED">Low (0–39)</option>
            <option value="REVIEW">Medium (40–69)</option><option value="BLOCKED">High (70–100)</option>
          </select>
          <select className="input input-sm" value={filters.user_id} onChange={set('user_id')}>
            <option value="">All senders</option>
            {users.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
          </select>
          <select className="input input-sm" value={filters.source} onChange={set('source')}>
            <option value="">Manual + simulated</option><option value="manual">Manual</option><option value="simulated">Simulated</option>
          </select>
          {active && <button className="link-btn small" onClick={() => setFilters(EMPTY)}>Clear filters</button>}
        </div>
        <ErrorNote error={error} />
        {loading && !data ? <Loading /> : !data?.items.length ? <Empty icon="📡" title="No transactions match" >Send a payment as the User or run a Frauder scenario.</Empty> : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Time</th><th>Ref</th><th>Sender</th><th>Receiver</th><th>Amount</th><th>Channel</th><th>City</th><th>Score</th><th>Rules fired</th><th>Status</th></tr>
              </thead>
              <tbody>
                {data.items.map((t) => (
                  <tr key={t.id} className={`clickable row-${t.decision} ${fresh.has(t.id) ? 'row-new' : ''}`}
                      onClick={() => navigate(`/detection/transactions/${t.id}`)}>
                    <td className="mono small nowrap">{timeOnly(t.txn_time)}</td>
                    <td className="mono small">{t.txn_ref}{t.is_simulated && <div><span className="badge b-purple">sim</span></div>}</td>
                    <td className="small">{t.sender.name}</td>
                    <td className="small">{t.receiver.name}</td>
                    <td className="nowrap" style={{ fontWeight: 600 }}>{money(t.amount)}</td>
                    <td className="small">{METHOD_LABEL[t.payment_method]}</td>
                    <td className="small">{t.city || '—'}</td>
                    <td><RiskScore score={t.risk_score} /></td>
                    <td><RuleChips rules={t.rules} /></td>
                    <td><StatusBadge status={t.status} />{t.review_stage === 'AWAITING_ANALYST' && <div className="small" style={{ color: 'var(--warning)' }}>needs analyst</div>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pagination meta={data?.meta} onPage={(page) => setFilters((f) => ({ ...f, page }))} />
      </div>
    </>
  );
}
