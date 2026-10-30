import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Empty, ErrorNote, Loading, OutcomeBadge, PageHead, RiskScore, RuleChips, StatCard, StatusBadge } from '../../components/ui';
import { useApi } from '../../hooks';
import { money, moneyShort, num, timeAgo, timeOnly } from '../../utils/format';

const pct = (v) => (v == null ? '—' : `${(v * 100).toFixed(1)}%`);
const bucketColor = (i) => (i >= 7 ? '#F87171' : i >= 4 ? '#FBBF24' : '#4ADE80');
const AXIS = { fontSize: 12, fill: '#64748B' };

export default function Overview() {
  const navigate = useNavigate();
  const [filters, setFilters] = useState({ date_from: '', date_to: '', source: '' });
  const { data, error } = useApi('/analytics/summary', filters, { interval: 5000 });
  const live = useApi('/detection/live', { limit: 8 }, { interval: 3000 });
  const confirmations = useApi('/detection/confirmations', null, { interval: 4000 });
  const set = (k) => (e) => setFilters((f) => ({ ...f, [k]: e.target.value }));

  const suspicious = (live.data?.transactions || []).filter((t) => t.decision && t.decision !== 'APPROVED');

  return (
    <>
      <PageHead title="Detection overview" subtitle="Every manual and simulated transaction, scored in real time.">
        <input type="date" className="input input-sm" value={filters.date_from} onChange={set('date_from')} aria-label="From date" />
        <input type="date" className="input input-sm" value={filters.date_to} onChange={set('date_to')} aria-label="To date" />
        <select className="input input-sm" value={filters.source} onChange={set('source')}>
          <option value="">Manual + simulated</option><option value="manual">Manual only</option><option value="simulated">Simulated only</option>
        </select>
        <span className="row small muted"><span className="live-dot" /> Live</span>
      </PageHead>
      <ErrorNote error={error} />
      {!data ? <Loading /> : (
        <>
          <div className="grid grid-4">
            <StatCard icon="⇄" tone="blue" label="Total transactions" value={num(data.totals.total)} sub={moneyShort(data.totals.volume) + ' volume'} />
            <StatCard icon="✓" tone="green" label="Approved" value={num(data.totals.approved)} />
            <StatCard icon="⏸" tone="amber" label="Under review" value={num(data.totals.under_review)} sub={`${live.data?.awaiting_analyst ?? 0} awaiting analyst`} />
            <StatCard icon="⛔" tone="red" label="Blocked" value={num(data.totals.blocked)} sub={moneyShort(data.totals.blocked_amount) + ' stopped'} />
            <StatCard icon="🎯" tone="purple" label="Fraud attempts detected" value={num(data.totals.flagged)} sub="Initial decision Review or Blocked" />
            <StatCard icon="🚨" tone="red" label="Total alerts" value={num(data.totals.alerts)} sub={`${data.totals.open_alerts} open · ${data.totals.high_alerts} high`} />
            <StatCard icon="⏱" tone="blue" label="Decision latency (p95)" value={data.latency.p95_ms != null ? `${data.latency.p95_ms} ms` : '—'} sub={data.latency.p50_ms != null ? `median ${data.latency.p50_ms} ms · target ≤ 500 ms` : 'no data yet'} />
            <StatCard icon="✔" tone="green" label="Confirmed fraud" value={num(data.totals.confirmed_fraud)} sub="Resolved by analysts" />
          </div>

          <ConfirmationsCard data={confirmations.data} onOpen={(id) => navigate(`/detection/transactions/${id}`)} />

          <div className="grid grid-main mt-16">
            <div className="card">
              <div className="card-head"><h2>Transactions per day</h2><span className="muted small">all vs flagged</span></div>
              <div className="card-body" style={{ height: 260 }}>
                {data.daily.length === 0 ? <Empty title="No transactions yet" /> : (
                  <ResponsiveContainer>
                    <AreaChart data={data.daily}>
                      <CartesianGrid stroke="#E2E8F0" vertical={false} />
                      <XAxis dataKey="day" tick={AXIS} tickFormatter={(d) => d.slice(5)} />
                      <YAxis tick={AXIS} allowDecimals={false} width={36} />
                      <Tooltip />
                      <Legend />
                      <Area type="monotone" dataKey="total" name="All" stroke="#3B82F6" fill="#DBEAFE" />
                      <Area type="monotone" dataKey="flagged" name="Flagged" stroke="#E11D48" fill="#FFE4E6" />
                    </AreaChart>
                  </ResponsiveContainer>
                )}
              </div>
            </div>
            <div className="card">
              <div className="card-head"><h2>Risk score distribution</h2></div>
              <div className="card-body" style={{ height: 260 }}>
                <ResponsiveContainer>
                  <BarChart data={data.risk_distribution}>
                    <CartesianGrid stroke="#E2E8F0" vertical={false} />
                    <XAxis dataKey="range" tick={{ ...AXIS, fontSize: 10 }} interval={0} angle={-30} textAnchor="end" height={44} />
                    <YAxis tick={AXIS} allowDecimals={false} width={30} />
                    <Tooltip />
                    <Bar dataKey="count" name="Transactions" radius={[4, 4, 0, 0]}>
                      {data.risk_distribution.map((_, i) => <Cell key={i} fill={bucketColor(i)} />)}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
          </div>

          <div className="grid grid-main mt-16">
            <div className="card">
              <div className="card-head"><h2>Recent suspicious activity</h2><Link to="/detection/monitor" className="small">Live monitor →</Link></div>
              {suspicious.length === 0 ? <Empty icon="🛡️" title="Nothing suspicious in the latest transactions" /> : (
                <div className="table-wrap">
                  <table className="table">
                    <thead><tr><th>Ref</th><th>Sender → Receiver</th><th>Amount</th><th>Score</th><th>Rules</th><th>Status</th></tr></thead>
                    <tbody>
                      {suspicious.map((t) => (
                        <tr key={t.id} className={`clickable row-${t.decision}`} onClick={() => navigate(`/detection/transactions/${t.id}`)}>
                          <td className="mono small">{t.txn_ref}<div className="muted">{timeAgo(t.txn_time)}</div></td>
                          <td className="small">{t.sender.name} → {t.receiver.name}{t.is_simulated && <span className="badge b-purple" style={{ marginLeft: 6 }}>sim</span>}</td>
                          <td className="nowrap">{money(t.amount)}</td>
                          <td><RiskScore score={t.risk_score} /></td>
                          <td><RuleChips rules={t.rules} /></td>
                          <td><StatusBadge status={t.status} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
            <div className="card">
              <div className="card-head"><h2>Most triggered rules</h2></div>
              <div className="card-body" style={{ height: 280 }}>
                {data.top_rules.length === 0 ? <Empty title="No rules have fired yet" /> : (
                  <ResponsiveContainer>
                    <BarChart data={data.top_rules} layout="vertical" margin={{ left: 4 }}>
                      <CartesianGrid stroke="#E2E8F0" horizontal={false} />
                      <XAxis type="number" tick={AXIS} allowDecimals={false} />
                      <YAxis type="category" dataKey="code" tick={AXIS} width={34} />
                      <Tooltip formatter={(v, n, p) => [v, p.payload.name]} />
                      <Bar dataKey="hits" fill="#8B5CF6" radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </div>
            </div>
          </div>

          <div className="grid grid-3 mt-16">
            <div className="card">
              <div className="card-head"><h2>Detection quality</h2><span className="muted small">simulated, labelled</span></div>
              <div className="card-body">
                {data.detection_quality.labelled === 0 ? <p className="muted small">Run Frauder scenarios to measure precision and recall.</p> : (
                  <>
                    <dl className="kv">
                      <dt>Precision</dt><dd>{pct(data.detection_quality.precision)}</dd>
                      <dt>Recall</dt><dd>{pct(data.detection_quality.recall)} <span className="muted small">(target ≥ 90%)</span></dd>
                      <dt>F1-score</dt><dd>{pct(data.detection_quality.f1)}</dd>
                      <dt>False-positive rate</dt><dd>{pct(data.detection_quality.false_positive_rate)} <span className="muted small">(target ≤ 5%)</span></dd>
                    </dl>
                    <p className="muted small mt-8">TP {data.detection_quality.tp} · FP {data.detection_quality.fp} · FN {data.detection_quality.fn} · TN {data.detection_quality.tn}</p>
                  </>
                )}
              </div>
            </div>
            <div className="card">
              <div className="card-head"><h2>By payment channel</h2></div>
              <div className="card-body" style={{ height: 200 }}>
                <ResponsiveContainer>
                  <BarChart data={data.by_method}>
                    <XAxis dataKey="label" tick={AXIS} />
                    <YAxis tick={AXIS} allowDecimals={false} width={30} />
                    <Tooltip /><Legend />
                    <Bar dataKey="total" name="All" fill="#93C5FD" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="flagged" name="Flagged" fill="#FCA5A5" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>
            <div className="card">
              <div className="card-head"><h2>By city</h2></div>
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>City</th><th className="right">Txns</th><th className="right">Flagged</th></tr></thead>
                  <tbody>
                    {data.by_city.map((c) => (
                      <tr key={c.label}><td>{c.label}</td><td className="right">{c.total}</td><td className="right" style={{ color: c.flagged ? 'var(--danger)' : undefined }}>{c.flagged}</td></tr>
                    ))}
                  </tbody>
                </table>
                {data.by_city.length === 0 && <Empty title="No data" />}
              </div>
            </div>
          </div>
        </>
      )}
    </>
  );
}

const ANSWER = { YES: ['YES – authorized', 'b-green'], NO: ['NO – denied', 'b-red'] };

function ConfirmationsCard({ data, onOpen }) {
  if (!data) return null;
  const rows = [...data.pending, ...data.recent];
  return (
    <div className="card mt-16">
      <div className="card-head">
        <h2>🔐 Suspicious transactions – owner confirmations</h2>
        <span className="small muted">{data.counts.pending} waiting · {data.counts.yes} YES · {data.counts.no} NO · {data.counts.expired} expired</span>
      </div>
      {rows.length === 0 ? <Empty icon="🙋" title="No confirmations yet">When any fraud rule fires, the payment is held and its owner is asked whether they initiated it.</Empty> : (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Ref</th><th>Owner → Receiver</th><th>Amount</th><th>Score</th><th>Rules</th><th>Owner’s answer</th><th>Final status</th></tr></thead>
            <tbody>
              {rows.slice(0, 10).map((t) => (
                <tr key={t.id} className="clickable" onClick={() => onOpen(t.id)}>
                  <td className="mono small">{t.txn_ref}<div className="muted">{timeAgo(t.txn_time)}</div></td>
                  <td className="small">{t.sender.name} → {t.receiver.name}{t.is_simulated && <span className="badge b-purple" style={{ marginLeft: 6 }}>Frauder</span>}</td>
                  <td className="nowrap">{money(t.amount)}</td>
                  <td><RiskScore score={t.risk_score} /></td>
                  <td><RuleChips rules={t.rules} /></td>
                  <td className="small">{t.confirmation.response
                    ? <span className={`badge ${ANSWER[t.confirmation.response][1]}`}>{ANSWER[t.confirmation.response][0]} · {timeOnly(t.confirmation.responded_at)}</span>
                    : t.confirmation.status === 'EXPIRED' ? <span className="badge b-slate">No answer</span>
                      : t.confirmation.status === 'CLOSED' ? <span className="badge b-slate">Closed</span>
                        : <span className="badge b-amber badge-dot">Waiting · until {timeOnly(t.confirmation.expires_at)}</span>}</td>
                  <td><OutcomeBadge label={t.outcome_label} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
