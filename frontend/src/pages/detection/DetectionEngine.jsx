import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { errorMessage, get, post } from '../../api/client';
import { useToast } from '../../components/Toast';
import { Empty, ErrorNote, Field, Loading, PageHead, RiskScore, RuleChips, StatCard, StatusBadge } from '../../components/ui';
import { useApi } from '../../hooks';
import { dateTime, money, timeAgo } from '../../utils/format';

const PERIODS = [['', 'All history'], ['30', 'Last 30 days'], ['90', 'Last 90 days'], ['365', 'Last 12 months']];
const BAND = { APPROVED: ['Low (0–39)', 'b-green'], REVIEW: ['Medium (40–69)', 'b-amber'], BLOCKED: ['High (70–100)', 'b-red'] };

/** Runs the nine SQL rules over the stored transactions of the predefined
 *  dummy accounts and shows what they find. A scan never changes a payment. */
export default function DetectionEngine() {
  const toast = useToast();
  const navigate = useNavigate();
  const { data, error, loading, reload } = useApi('/detection/engine');
  const [form, setForm] = useState({ account_id: '', days: '', include_simulated: true });
  const [run, setRun] = useState(null);
  const [busy, setBusy] = useState(false);
  const [flaggedOnly, setFlaggedOnly] = useState(true);

  const start = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await post('/detection/engine/run', {
        account_id: form.account_id || null, days: form.days || null, include_simulated: form.include_simulated,
      });
      setRun(res.data);
      toast(res.message, res.data.txns_flagged ? 'warning' : 'success', 'Detection run complete');
      reload(true);
    } catch (err) {
      toast(errorMessage(err), 'error');
    } finally {
      setBusy(false);
    }
  };

  const open = async (id) => {
    try {
      setRun(await get(`/detection/engine/runs/${id}`));
    } catch (err) {
      toast(errorMessage(err), 'error');
    }
  };

  if (!data) return error ? <ErrorNote error={error} /> : <Loading />;
  const rows = run ? run.results.filter((r) => !flaggedOnly || r.rules.length) : [];
  const maxRule = run ? Math.max(1, ...run.summary.by_rule.map((r) => r.count)) : 1;

  return (
    <>
      <PageHead title="Detection Engine"
                subtitle="Run the nine SQL fraud rules over the predefined dummy accounts’ transactions and review what they find. Scans never change a payment.">
      </PageHead>

      <div className="grid grid-main">
        <form className="card card-pad stack" onSubmit={start}>
          <h3>Run detection</h3>
          <div className="grid grid-2">
            <Field label="Accounts">
              <select className="input" value={form.account_id} onChange={(e) => setForm({ ...form, account_id: e.target.value })}>
                <option value="">All dummy accounts</option>
                {data.accounts.map((a) => <option key={a.account_id} value={a.account_id}>{a.name} · {a.upi_id}</option>)}
              </select>
            </Field>
            <Field label="Period">
              <select className="input" value={form.days} onChange={(e) => setForm({ ...form, days: e.target.value })}>
                {PERIODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </Field>
          </div>
          <label className="row small">
            <input type="checkbox" checked={form.include_simulated}
                   onChange={(e) => setForm({ ...form, include_simulated: e.target.checked })} />
            Include Frauder attempts
          </label>
          <button className="btn btn-primary btn-lg" disabled={busy}>{busy ? 'Running the nine rules…' : '▶ Run detection'}</button>
          <p className="small muted">
            Each payment is checked at its own time, exactly as the live engine would, inside a database savepoint that is
            rolled back. Up to {data.max_scan} of the most recent payments are scanned per run. R4 (new device) and R8
            (dormancy) read the account’s current state, so for older payments they show what the rule says today.
          </p>
        </form>

        <div className="card">
          <div className="card-head"><h2>Recent runs</h2></div>
          {loading && !data.runs ? <Loading /> : data.runs.length === 0
            ? <Empty icon="🧪" title="No runs yet">Run detection to scan the dummy accounts.</Empty>
            : (
              <div className="list">
                {data.runs.map((r) => (
                  <button key={r.id} type="button" className={`list-item clickable${run?.id === r.id ? ' unread' : ''}`}
                          style={{ width: '100%', textAlign: 'left', background: 'none', border: 0 }} onClick={() => open(r.id)}>
                    <div style={{ flex: 1 }}>
                      <strong>Run #{r.id}</strong> · {r.scope?.account}{r.scope?.days ? ` · last ${r.scope.days} days` : ''}
                      <div className="small muted">{r.txns_scanned} scanned · {r.txns_flagged} flagged · {r.run_by} · {timeAgo(r.created_at)}</div>
                    </div>
                    <span className={`badge ${r.txns_flagged ? 'b-amber' : 'b-green'}`}>{r.txns_flagged}</span>
                  </button>
                ))}
              </div>
            )}
        </div>
      </div>

      {!run ? (
        <div className="card mt-16"><Empty icon="🛡️" title="No results to show">Run detection, or open a recent run.</Empty></div>
      ) : (
        <>
          <div className="row-between wrap mt-24">
            <h2>Run #{run.id} · {run.scope?.account}{run.scope?.days ? ` · last ${run.scope.days} days` : ''}</h2>
            <span className="small muted">{dateTime(run.created_at)} · {run.run_by} · {run.duration_ms} ms
              {run.scope?.limited_to && ` · newest ${run.scope.limited_to} of ${run.scope.matched}`}</span>
          </div>

          <div className="grid grid-4 mt-16">
            <StatCard icon="🔍" tone="blue" label="Transactions scanned" value={run.txns_scanned} sub={run.scope?.include_simulated ? 'incl. Frauder attempts' : 'genuine only'} />
            <StatCard icon="🚩" tone="amber" label="Flagged by a rule" value={run.txns_flagged} sub={money(run.summary.amount_flagged)} />
            <StatCard icon="⛔" tone="red" label="High risk (70+)" value={run.summary.by_band.BLOCKED} sub={`${run.summary.by_band.REVIEW} medium · ${run.summary.by_band.APPROVED} low`} />
            <StatCard icon="↻" tone="purple" label="Differs from stored result" value={run.summary.changed_vs_stored} sub="Rules or weights changed since" />
          </div>

          <div className="grid grid-2 mt-16">
            <div className="card card-pad">
              <h3>Rule hits</h3>
              <div className="stack mt-8" style={{ gap: 8 }}>
                {run.summary.by_rule.map((r) => (
                  <div key={r.code} className="row small" style={{ gap: 10 }}>
                    <span className="rule-chip">{r.code}</span>
                    <span style={{ width: 190 }}>{r.name}</span>
                    <span className="score-bar" style={{ flex: 1, height: 8 }}>
                      <span style={{ width: `${(r.count / maxRule) * 100}%`, background: r.count ? 'var(--danger)' : 'transparent' }} />
                    </span>
                    <strong style={{ width: 24, textAlign: 'right' }}>{r.count}</strong>
                  </div>
                ))}
              </div>
            </div>
            <div className="card">
              <div className="card-head"><h3>By account</h3></div>
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>Sender</th><th className="right">Scanned</th><th className="right">Flagged</th><th>Highest score</th><th className="right">Flagged amount</th></tr></thead>
                  <tbody>
                    {run.summary.by_account.map((a) => (
                      <tr key={a.name}>
                        <td>{a.name}</td><td className="right">{a.scanned}</td><td className="right">{a.flagged}</td>
                        <td><RiskScore score={a.max_score} /></td><td className="right nowrap">{money(a.amount_flagged)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <div className="card mt-16">
            <div className="card-head">
              <h2>Detection results</h2>
              <label className="row small"><input type="checkbox" checked={flaggedOnly} onChange={(e) => setFlaggedOnly(e.target.checked)} /> Flagged only</label>
            </div>
            {rows.length === 0 ? <Empty icon="✅" title={flaggedOnly ? 'No rule fired' : 'Nothing scanned'}>{flaggedOnly && 'Every scanned transaction passed all nine rules.'}</Empty> : (
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>Ref · time</th><th>Sender → Receiver</th><th className="right">Amount</th><th>Score</th><th>Band</th><th>Rules fired</th><th>Status</th></tr></thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.id} className="clickable" onClick={() => navigate(`/detection/transactions/${r.id}`)}>
                        <td className="mono small">{r.txn_ref}<div className="muted">{dateTime(r.txn_time)}{r.city && ` · ${r.city}`}</div></td>
                        <td className="small">
                          {r.sender} → {r.receiver}
                          {r.is_simulated && <span className="badge b-purple" style={{ marginLeft: 6 }}>Frauder</span>}
                          {r.seeded_history && <span className="badge b-slate" style={{ marginLeft: 6 }}>Sample history</span>}
                        </td>
                        <td className="right nowrap">{money(r.amount)}</td>
                        <td><RiskScore score={r.score} />{r.changed && <div className="small muted">stored {r.stored_score}</div>}</td>
                        <td><span className={`badge ${BAND[r.band][1]}`}>{BAND[r.band][0]}</span></td>
                        <td className="small"><RuleChips rules={r.rules} />
                          {r.rules.map((h) => <div key={h.code} className="muted">{h.code}: {h.reason}</div>)}</td>
                        <td><StatusBadge status={r.status} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </>
  );
}
