import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Empty, ErrorNote, Loading, PageHead, Pagination, RiskScore, StatusBadge } from '../../components/ui';
import { useApi } from '../../hooks';
import { dateTime, money, METHOD_LABEL } from '../../utils/format';

export const CASE_VIEWS = [
  ['pending', 'Pending', 'Temporarily blocked, not yet reviewed'],
  ['under_investigation', 'Under investigation', 'A detective is reviewing'],
  ['permanently_blocked', 'Permanently blocked', 'Fraud confirmed'],
  ['approved', 'Approved', 'Verified legitimate, access restored'],
  ['resolved', 'Resolved', 'All completed investigations'],
  ['all', 'All cases', ''],
];
const SORTS = [['newest', 'Newest detection'], ['oldest', 'Oldest detection'], ['risk', 'Highest risk'], ['amount', 'Largest amount']];

/** Temporary Account Blocks / Fraud Investigation Queue. */
export default function InvestigationQueue() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  // ?view= (from an overview card) wins over the tab remembered from the last visit.
  const [tab, setTab] = useState(() => {
    const asked = params.get('view');
    if (CASE_VIEWS.some(([key]) => key === asked)) return asked;
    try { return sessionStorage.getItem('fs-case-tab') || 'pending'; } catch { return 'pending'; }
  });
  const [search, setSearch] = useState('');
  const [q, setQ] = useState('');
  const [sort, setSort] = useState('newest');
  const [page, setPage] = useState(1);

  useEffect(() => {
    try { sessionStorage.setItem('fs-case-tab', tab); } catch { /* storage unavailable */ }
  }, [tab]);
  useEffect(() => {
    const timer = setTimeout(() => { setQ(search.trim()); setPage(1); }, 350);
    return () => clearTimeout(timer);
  }, [search]);

  const isTrail = tab === 'trail';
  const cases = useApi('/detection/investigations', { view: tab, q: q || undefined, sort, page }, { interval: 5000, enabled: !isTrail });
  const trail = useApi('/detection/investigations/history', { page }, { enabled: isTrail });
  const counts = cases.data?.counts;
  const pick = (next) => { setTab(next); setPage(1); };

  return (
    <>
      <PageHead title="Investigations"
                subtitle="Temporary account blocks and the fraud investigation queue. Open a case, review it, then approve the account or block it permanently." />

      <div className="case-tabs" role="tablist">
        {CASE_VIEWS.map(([key, label, hint]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key} title={hint}
                  className={`case-tab tone-${key}${tab === key ? ' on' : ''}`} onClick={() => pick(key)}>
            <span>{label}</span><strong>{counts ? counts[key] : '–'}</strong>
          </button>
        ))}
        <button type="button" role="tab" aria-selected={isTrail} className={`case-tab${isTrail ? ' on' : ''}`} onClick={() => pick('trail')}>
          <span>Audit trail</span><strong>📜</strong>
        </button>
      </div>

      {isTrail ? <AuditTrail state={trail} onPage={setPage} onOpen={(id) => navigate(`/detection/investigations/${id}`)} /> : (
        <div className="card mt-16">
          <div className="filters">
            <input className="input input-sm" style={{ flex: 1, minWidth: 220 }} value={search} maxLength={60}
                   onChange={(e) => setSearch(e.target.value)} placeholder="Search case, customer, account, UPI ID or transaction ID" />
            <select className="input input-sm" value={sort} onChange={(e) => { setSort(e.target.value); setPage(1); }}>
              {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          {cases.error ? <div className="card-body"><ErrorNote error={cases.error} /></div>
            : cases.loading && !cases.data ? <Loading />
              : !cases.data.items.length ? (
                <Empty icon="🗂️" title={q ? 'No case matches this search' : 'No cases here'}>
                  {q ? 'Try another name, account or transaction ID.' : 'Restricted accounts appear here automatically when the fraud engine stops a payment.'}
                </Empty>
              ) : (
                <div className="table-wrap">
                  <table className="table case-table">
                    <thead>
                      <tr>
                        <th>Case · detected</th><th>Customer · account</th><th>Transaction</th><th className="right">Amount</th>
                        <th>Detection reason & indicators</th><th>Overall risk</th><th>Account</th><th>Investigation</th>
                      </tr>
                    </thead>
                    <tbody>
                      {cases.data.items.map((c) => (
                        <tr key={c.id} className="clickable" onClick={() => navigate(`/detection/investigations/${c.id}`)}>
                          <td className="small"><strong className="mono">{c.case_ref}</strong><div className="muted nowrap">{dateTime(c.opened_at)}</div></td>
                          <td className="small"><strong>{c.customer.name}</strong><div className="muted mono">{c.account.masked_number} · {c.account.upi_id}</div></td>
                          <td className="small"><span className="mono">{c.transaction.txn_ref || '—'}</span>
                            <div className="muted nowrap">{c.transaction.txn_time ? dateTime(c.transaction.txn_time) : ''} · {METHOD_LABEL[c.transaction.payment_method] || '—'}</div></td>
                          <td className="right nowrap" style={{ fontWeight: 700 }}>{money(c.transaction.amount)}</td>
                          <td className="small" style={{ maxWidth: 320 }}>
                            <div className="case-reason">{c.detection_reason}</div>
                            <div className="row wrap" style={{ gap: 4, marginTop: 4 }}>
                              {c.risk_factors.map((f) => <span key={f.code} className="rule-chip" title={`${f.name}: ${f.reason}`}>{f.code} +{f.weight}</span>)}
                            </div>
                          </td>
                          <td><RiskScore score={c.risk_score} /></td>
                          <td><StatusBadge status={c.account.status} /></td>
                          <td><StatusBadge status={c.status} /><div className="muted small">{c.case_type === 'RECEIVER_REPORTED' ? 'Reported receiver' : 'High-risk sender'}</div></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
          <Pagination meta={cases.data?.meta} onPage={setPage} />
        </div>
      )}
    </>
  );
}

const ACTION_LABEL = {
  CASE_OPENED: 'Case opened', REVIEW_STARTED: 'Investigation started', APPROVE: 'Approved – access restored',
  PERMANENT_BLOCK: 'Permanently blocked', CLOSED_BY_PERMANENT_BLOCK: 'Closed by a permanent block',
  CLOSED_BY_RESET: 'Closed – Frauder attempt reset',
};

export function actionLabel(action) {
  return ACTION_LABEL[action] || action.replaceAll('_', ' ').toLowerCase();
}

function AuditTrail({ state, onPage, onOpen }) {
  const { data, error, loading } = state;
  return (
    <div className="card mt-16">
      <div className="card-head"><h2>📜 Investigation audit trail</h2><span className="small muted">Append-only – entries can never be edited or deleted</span></div>
      {error ? <div className="card-body"><ErrorNote error={error} /></div> : loading && !data ? <Loading />
        : !data.items.length ? <Empty icon="📜" title="No investigation actions yet" /> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>When</th><th>Case</th><th>Detective</th><th>Action</th><th>Account status</th><th>Case status</th><th>Reason</th></tr></thead>
              <tbody>
                {data.items.map((a) => (
                  <tr key={a.id} className="clickable" onClick={() => onOpen(a.case_id)}>
                    <td className="small nowrap">{dateTime(a.created_at)}</td>
                    <td className="mono small">{a.case_ref}</td>
                    <td className="small">{a.detective}<div className="muted">ID {a.detective_id ?? '—'} · account #{a.account_id}</div></td>
                    <td className="small"><strong>{actionLabel(a.action)}</strong></td>
                    <td className="small nowrap">{a.previous_account_status ? `${a.previous_account_status} → ` : ''}{a.new_account_status}</td>
                    <td className="small nowrap">{a.previous_case_status ? `${a.previous_case_status} → ` : ''}{a.new_case_status}</td>
                    <td className="small">{a.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      <Pagination meta={data?.meta} onPage={onPage} />
    </div>
  );
}
