import { useEffect, useState } from 'react';
import { errorMessage, put } from '../../api/client';
import { useToast } from '../../components/Toast';
import { ErrorNote, Loading, PageHead, Toggle } from '../../components/ui';
import { useApi } from '../../hooks';

const label = (key) => key.replaceAll('_', ' ');

function RuleCard({ rule, perf, onSaved }) {
  const toast = useToast();
  const [weight, setWeight] = useState(rule.weight);
  const [params, setParams] = useState(rule.params);
  const [busy, setBusy] = useState(false);
  useEffect(() => { setWeight(rule.weight); setParams(rule.params); }, [rule]);
  const dirty = Number(weight) !== rule.weight || JSON.stringify(params) !== JSON.stringify(rule.params);

  const save = async (body, msg) => {
    setBusy(true);
    try {
      await put(`/detection/rules/${rule.code}`, body);
      toast(msg || `${rule.code} saved.`, 'success');
      onSaved();
    } catch (e) {
      toast(errorMessage(e), 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card" style={{ opacity: rule.is_active ? 1 : 0.65 }}>
      <div className="card-head">
        <div className="row"><span className="rule-chip">{rule.code}</span><h3>{rule.name}</h3></div>
        <Toggle checked={rule.is_active} disabled={busy} label="Active"
                onChange={(v) => save({ is_active: v }, `${rule.code} ${v ? 'enabled' : 'disabled'}.`)} />
      </div>
      <div className="card-body stack" style={{ gap: 12 }}>
        <p className="small muted">{rule.description}</p>
        <div className="small"><span className="muted">SQL technique:</span> {rule.sql_technique}</div>
        <div className="grid grid-2" style={{ gap: 10 }}>
          <div className="field">
            <label>Weight (0–100)</label>
            <input className="input" type="number" min="0" max="100" value={weight} onChange={(e) => setWeight(e.target.value)} />
          </div>
          {Object.entries(params).map(([k, v]) => (
            <div className="field" key={k}>
              <label style={{ textTransform: 'capitalize' }}>{label(k)}</label>
              <input className="input" type="number" min="0" step="any" value={v}
                     onChange={(e) => setParams({ ...params, [k]: e.target.value === '' ? '' : Number(e.target.value) })} />
            </div>
          ))}
        </div>
        <div className="row-between wrap">
          <span className="small muted">
            {perf ? <>Hits {perf.hits} · confirmed {perf.confirmed_fraud} · false +ve {perf.false_positive} · precision {perf.precision == null ? '—' : `${Math.round(perf.precision * 100)}%`}</> : '—'}
          </span>
          <div className="row">
            <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => save({ restore_defaults: true }, `${rule.code} restored to defaults.`)}>Defaults</button>
            <button className="btn btn-primary btn-sm" disabled={busy || !dirty} onClick={() => save({ weight: Number(weight), params })}>Save</button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Bands({ bands, onSaved }) {
  const toast = useToast();
  const review = bands.find((b) => b.code === 'REVIEW');
  const blocked = bands.find((b) => b.code === 'BLOCKED');
  const [reviewMin, setReviewMin] = useState(review.min_score);
  const [blockedMin, setBlockedMin] = useState(blocked.min_score);
  useEffect(() => { setReviewMin(review.min_score); setBlockedMin(blocked.min_score); }, [review.min_score, blocked.min_score]);

  const save = async () => {
    try {
      await put('/detection/risk-categories', { review_min: Number(reviewMin), blocked_min: Number(blockedMin) });
      toast('Score bands updated.', 'success');
      onSaved();
    } catch (e) {
      toast(errorMessage(e), 'error');
    }
  };
  const r = Number(reviewMin) || 0;
  const b = Number(blockedMin) || 0;
  return (
    <div className="card card-pad">
      <div className="row-between wrap">
        <div>
          <h2>Risk score bands</h2>
          <p className="muted small">Risk = min(100, Σ weights of fired rules) → decision.</p>
        </div>
        <div className="row wrap">
          <label className="small">Review from <input className="input input-sm" type="number" style={{ width: 70 }} value={reviewMin} onChange={(e) => setReviewMin(e.target.value)} /></label>
          <label className="small">Blocked from <input className="input input-sm" type="number" style={{ width: 70 }} value={blockedMin} onChange={(e) => setBlockedMin(e.target.value)} /></label>
          <button className="btn btn-primary btn-sm" onClick={save}>Save bands</button>
        </div>
      </div>
      <div className="row mt-16" style={{ gap: 0, height: 30, borderRadius: 8, overflow: 'hidden', fontSize: 12, fontWeight: 600 }}>
        <div style={{ width: `${r}%`, background: 'var(--success-bg)', color: 'var(--success)', display: 'grid', placeItems: 'center' }}>Approved 0–{r - 1}</div>
        <div style={{ width: `${Math.max(0, b - r)}%`, background: 'var(--warning-bg)', color: 'var(--warning)', display: 'grid', placeItems: 'center' }}>Review {r}–{b - 1}</div>
        <div style={{ flex: 1, background: 'var(--danger-bg)', color: 'var(--danger)', display: 'grid', placeItems: 'center' }}>Blocked {b}–100</div>
      </div>
    </div>
  );
}

export default function Rules() {
  const rules = useApi('/detection/rules');
  const bands = useApi('/detection/risk-categories');
  const summary = useApi('/analytics/summary');
  const perf = Object.fromEntries((summary.data?.rule_performance || []).map((p) => [p.code, p]));
  const reload = () => { rules.reload(true); summary.reload(true); };

  return (
    <>
      <PageHead title="Fraud rules" subtitle="Thresholds and weights are stored in the fraud_rules table – changes apply to the next transaction, no code change. Every change is audited." />
      <ErrorNote error={rules.error} />
      {bands.data && <Bands bands={bands.data} onSaved={() => bands.reload(true)} />}
      {!rules.data ? <Loading /> : (
        <div className="grid grid-3 mt-16">
          {rules.data.map((r) => <RuleCard key={r.code} rule={r} perf={perf[r.code]} onSaved={reload} />)}
        </div>
      )}
    </>
  );
}
