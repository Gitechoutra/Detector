import { useEffect, useState } from 'react';
import { Link, Navigate, useParams } from 'react-router-dom';
import { PageTabs } from '../../components/TabbedPage';
import TxnDetailModal from '../../components/TxnDetailModal';
import { Avatar, Empty, ErrorNote, Field, Loading, OutcomeBadge, PageHead, Pagination, RiskScore, RuleChips, StatusBadge } from '../../components/ui';
import { useApi } from '../../hooks';
import { dateTime, money, METHOD_LABEL } from '../../utils/format';

/** Activity tabs; each dashboard card opens one. `extra` adds a column that explains the outcome. */
export const ACTIVITY_VIEWS = {
  all: { short: 'All', title: 'All transactions', icon: '🧾', text: 'Every payment you sent, and every payment credited to you.' },
  successful: { short: 'Successful', title: 'Successful transactions', icon: '✓', text: 'Payments that completed: money left one account and reached the other.' },
  pending: { short: 'Pending', title: 'Pending transactions', icon: '⏳', text: 'Payments still being processed or waiting for verification. Nothing has been debited yet.', extra: 'pending' },
  failed: { short: 'Failed', title: 'Failed transactions', icon: '✕', text: 'Payments that did not go through – declined, cancelled or expired – and why.', extra: 'reason' },
  blocked: { short: 'Blocked', title: 'Blocked transactions', icon: '⛔', text: 'Payments stopped by fraud detection, with the fraud indicators and the reason. No money moved.', extra: 'fraud' },
  awaiting: { short: 'Awaiting answer', title: 'Awaiting your answer', icon: '🔐', text: 'Flagged payments waiting for you to confirm whether you made them.', extra: 'pending' },
  sent: { short: 'Sent', title: 'Money sent', icon: '↗', text: 'Completed payments you sent.' },
  received: { short: 'Received', title: 'Money received', icon: '↙', text: 'Payments credited to your account.' },
};

const SORTS = [['newest', 'Newest first'], ['oldest', 'Oldest first'], ['amount_desc', 'Amount: high to low'], ['amount_asc', 'Amount: low to high']];
const BLANK = { q: '', date_from: '', date_to: '', direction: '', sort: 'newest' };

export default function UserActivity() {
  const { view } = useParams();
  const meta = ACTIVITY_VIEWS[view];
  const [filters, setFilters] = useState(BLANK);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState(null);

  // Search is applied a moment after typing stops.
  useEffect(() => {
    const timer = setTimeout(() => { setFilters((f) => ({ ...f, q: search.trim() })); setPage(1); }, 350);
    return () => clearTimeout(timer);
  }, [search]);
  useEffect(() => { setFilters(BLANK); setSearch(''); setPage(1); }, [view]);

  const params = { view, page, ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)) };
  const { data, error, loading, reload } = useApi('/user/transactions', params, { interval: 8000, enabled: !!meta });
  if (!meta) return <Navigate to="/user" replace />;
  const set = (k) => (e) => { setFilters((f) => ({ ...f, [k]: e.target.value })); setPage(1); };
  const filtered = Object.entries(filters).some(([k, v]) => v && k !== 'sort');

  return (
    <>
      <Link to="/user" className="back-link">← Back to dashboard</Link>
      <PageHead title="Activity" subtitle={meta.text}>
        {data?.summary && (
          <div className="activity-summary">
            <div><span>{data.summary.count}</span> transaction{data.summary.count === 1 ? '' : 's'}</div>
            <div><span>{money(data.summary.amount)}</span> total</div>
          </div>
        )}
      </PageHead>

      <PageTabs tabs={Object.entries(ACTIVITY_VIEWS).map(([key, v]) => [`/user/activity/${key}`, v.short])} />

      <div className="card">
        <div className="filters activity-filters">
          <Field label="Search">
            <input className="input input-sm" value={search} onChange={(e) => setSearch(e.target.value)}
                   placeholder="Transaction ID, name, UPI ID or remark" maxLength={60} />
          </Field>
          <Field label="From"><input className="input input-sm" type="date" value={filters.date_from} onChange={set('date_from')} /></Field>
          <Field label="To"><input className="input input-sm" type="date" value={filters.date_to} min={filters.date_from || undefined} onChange={set('date_to')} /></Field>
          {view === 'all' && (
            <Field label="Direction">
              <select className="input input-sm" value={filters.direction} onChange={set('direction')}>
                <option value="">Sent & received</option><option value="OUT">Sent</option><option value="IN">Received</option>
              </select>
            </Field>
          )}
          <Field label="Sort">
            <select className="input input-sm" value={filters.sort} onChange={set('sort')}>
              {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </Field>
          {filtered && (
            <button type="button" className="btn btn-ghost btn-sm" style={{ alignSelf: 'flex-end' }}
                    onClick={() => { setFilters(BLANK); setSearch(''); setPage(1); }}>Clear filters</button>
          )}
        </div>

        {error ? (
          <div className="card-body"><ErrorNote error={error} />
            <button type="button" className="btn btn-ghost btn-sm mt-8" onClick={() => reload(true)}>Try again</button></div>
        ) : loading && !data ? <Loading /> : !data?.items.length ? (
          <Empty icon={meta.icon} title={filtered ? 'Nothing matches these filters' : `No ${meta.title.toLowerCase()} yet`}>
            {filtered ? 'Try a different search or date range.' : 'They will appear here as soon as there are any.'}
          </Empty>
        ) : (
          <div className={`table-wrap${loading ? ' is-refreshing' : ''}`}>
            <table className="table">
              <thead>
                <tr>
                  <th>Transaction ID</th><th>Party</th><th className="right">Amount</th><th>Date & time</th><th>Status</th>
                  {meta.extra === 'reason' && <th>Failure reason</th>}
                  {meta.extra === 'fraud' && <th>Fraud indicators & reason</th>}
                  {meta.extra === 'pending' && <th>Waiting for</th>}
                  {!meta.extra && <th>Risk</th>}
                </tr>
              </thead>
              <tbody>
                {data.items.map((t) => {
                  const incoming = t.direction === 'IN';
                  const party = incoming ? t.sender : t.receiver;
                  return (
                    <tr key={t.id} className="clickable" onClick={() => setSelected(t)}>
                      <td className="mono small">{t.txn_ref}<div className="muted">{METHOD_LABEL[t.payment_method]}</div></td>
                      <td><div className="row"><Avatar name={party.name} tone={incoming ? 'green' : 'blue'} />
                        <div><div style={{ fontWeight: 600 }}>{incoming ? '↙ ' : '↗ '}{party.name}</div><div className="muted small">{party.upi_id}</div></div></div></td>
                      <td className="right nowrap" style={{ fontWeight: 700, color: incoming ? 'var(--success)' : undefined }}>
                        {incoming ? '+' : '−'}{money(t.amount)}</td>
                      <td className="small nowrap">{dateTime(t.txn_time)}</td>
                      <td>{t.confirmation ? <OutcomeBadge label={t.outcome_label} /> : <StatusBadge status={t.display_status || t.status} />}</td>
                      {meta.extra === 'reason' && <td className="small">{t.final_reason || t.decline_reason || '—'}</td>}
                      {meta.extra === 'fraud' && (
                        <td className="small"><div className="row" style={{ gap: 6 }}><RiskScore score={t.risk_score} /><RuleChips rules={t.rules} /></div>
                          <div className="muted" style={{ marginTop: 4 }}>{t.final_reason || t.risk_explanation}</div></td>
                      )}
                      {meta.extra === 'pending' && (
                        <td className="small">{t.confirmation?.status === 'CONFIRMED' ? 'Your OTP' : t.confirmation?.status === 'PENDING'
                          ? 'Your YES / NO answer' : t.review_stage === 'AWAITING_ANALYST' ? 'Our fraud team' : 'Processing'}</td>
                      )}
                      {!meta.extra && <td><RiskScore score={t.risk_score} /></td>}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <Pagination meta={data?.meta} onPage={setPage} />
      </div>

      {selected && (
        <TxnDetailModal txn={selected} viewer={selected.direction === 'IN' ? 'receiver' : 'sender'}
                        onClose={() => setSelected(null)} onChange={() => reload(true)} />
      )}
    </>
  );
}
