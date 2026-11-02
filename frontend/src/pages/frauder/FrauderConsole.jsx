import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { errorMessage, get, post } from '../../api/client';
import DetectionResult from '../../components/DetectionResult';
import { useToast } from '../../components/Toast';
import { Empty, Field, Loading, Modal, OutcomeBadge, PageHead, RuleChips } from '../../components/ui';
import { money, timeOnly } from '../../utils/format';

const newKey = () => (window.crypto?.randomUUID ? window.crypto.randomUUID() : String(Date.now() + Math.random()));
// Every field starts empty: nothing is guessed, geolocated or pre-selected.
const BLANK = { victim_id: '', receiver_id: '', amount: '', scenario: '' };
const STORE = 'frauder-attack-form';

function loadForm() {
  try {
    return { ...BLANK, ...JSON.parse(sessionStorage.getItem(STORE) || '{}') };
  } catch {
    return BLANK;
  }
}

export default function FrauderConsole() {
  const toast = useToast();
  const [ctx, setCtx] = useState(null);
  const [history, setHistory] = useState([]);
  const [form, setForm] = useState(loadForm);
  const [busy, setBusy] = useState('');
  const [result, setResult] = useState(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const keyRef = useRef(newKey());
  const resultRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const [c, h] = await Promise.all([get('/frauder/context'), get('/frauder/attempts')]);
      setCtx(c);
      setHistory(h);
    } catch (e) {
      toast(errorMessage(e), 'error');
    }
  }, [toast]);

  useEffect(() => { load(); }, [load]);

  // Only the presenter's own typing is remembered (for this browser tab).
  useEffect(() => {
    try { sessionStorage.setItem(STORE, JSON.stringify(form)); } catch { /* storage unavailable */ }
  }, [form]);

  // While the attempt is processing, follow it live.
  const pendingId = result?.status === 'UNDER_REVIEW' ? result.id : null;
  useEffect(() => {
    if (!pendingId) return undefined;
    const timer = setInterval(async () => {
      try {
        const fresh = await get(`/frauder/transactions/${pendingId}`);
        setResult((prev) => {
          if (!prev || prev.id !== fresh.id) return prev;
          if (prev.outcome_label !== fresh.outcome_label) {
            toast(`Transaction ${fresh.outcome_label === 'SUCCESS' ? 'successful' : fresh.outcome_label.toLowerCase()}.`,
                  fresh.outcome_label === 'SUCCESS' ? 'warning' : 'info', fresh.outcome_label);
            load();
          }
          const balances = Object.fromEntries(Object.entries(fresh.balances).map(([side, b]) => [side, { ...b, before: prev.balances?.[side]?.before ?? b.before }]));
          return { ...fresh, balances };
        });
      } catch { /* keep the last result on screen */ }
    }, 4000);
    return () => clearInterval(timer);
  }, [pendingId, toast, load]);

  if (!ctx) return <Loading />;
  const victim = ctx.victims.find((v) => String(v.id) === form.victim_id);
  const receiver = ctx.receivers.find((r) => String(r.id) === form.receiver_id);
  const set = (k) => (e) => {
    const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
    setForm((f) => ({ ...f, [k]: value }));
  };
  const missing = () => {
    const need = [['victim_id', 'target user account'], ['receiver_id', 'receiver account'], ['amount', 'transaction amount']];
    const gaps = need.filter(([k]) => !String(form[k]).trim()).map(([, label]) => label);
    if (!gaps.length && !(Number(form.amount) > 0)) gaps.push('an amount above ₹0');
    if (gaps.length) toast(`Please enter: ${gaps.join(', ')}.`, 'error', 'Missing details');
    return gaps.length > 0;
  };

  const run = async (label, fn) => {
    setBusy(label);
    try {
      await fn();
    } catch (e) {
      toast(errorMessage(e), 'error');
    } finally {
      setBusy('');
      load();
    }
  };

  const submit = (e) => {
    e.preventDefault();
    if (missing()) return;
    run('transfer', async () => {
      const body = { victim_id: form.victim_id, receiver_id: form.receiver_id, amount: form.amount, scenario: form.scenario || null };
      const res = await post('/frauder/transfer', body, { headers: { 'Idempotency-Key': keyRef.current } });
      keyRef.current = newKey();
      setResult(res.data);
      setForm(BLANK);     // each attempt starts from an empty form
      const tone = { COMPLETED: 'warning', UNDER_REVIEW: 'info', BLOCKED: 'success' }[res.data.status];
      toast(res.message, tone, 'Fraud detection result');
      setTimeout(() => resultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 50);
    });
  };

  const clearForm = () => {
    setForm(BLANK);
    toast('Form cleared.', 'info');
  };

  const reset = () => run('reset', async () => {
    const res = await post('/frauder/reset', { confirm: 'RESET' });
    setResult(null);
    setConfirmReset(false);
    toast(res.message, 'success');
  });

  return (
    <>
      <PageHead title="Frauder console" subtitle="Attempt a transfer from a target account. The 9 SQL fraud rules analyze it, and the outcome appears here: Success or Cancelled.">
        <Link to="/frauder/records" className="btn btn-ghost">Fraud detection records</Link>
        <Link to="/frauder/history" className="btn btn-ghost">Attempt history</Link>
        <button className="btn btn-danger-soft" onClick={() => setConfirmReset(true)}>↺ Reset fraud attempts</button>
      </PageHead>

      <div className="notice notice-info">
        🔒 Controlled impersonation of designated accounts only. You never see a password and cannot change balances,
        profiles or rules. Each attempt is made from the target account's own home city and registered device.
      </div>

      <div className="grid grid-main mt-24">
        <form className="card" onSubmit={submit} noValidate>
          <div className="card-head">
            <h2>Attack details</h2>
            <button type="button" className="btn btn-ghost btn-sm" onClick={clearForm}>Clear form</button>
          </div>
          <div className="card-body stack">
            <div className="grid grid-2" style={{ gap: 12 }}>
              <Field label="Target user account">
                <select className="input" value={form.victim_id} onChange={set('victim_id')}>
                  <option value="">— Select a demo account —</option>
                  {ctx.victims.map((v) => <option key={v.id} value={v.id}>{v.name} · {v.upi_id}</option>)}
                </select>
              </Field>
              <Field label="Receiver account">
                <select className="input" value={form.receiver_id} onChange={set('receiver_id')}>
                  <option value="">— Select a demo receiver —</option>
                  {ctx.receivers.map((r) => (
                    <option key={r.id} value={r.id} disabled={r.blocked}>
                      {r.name} · {r.upi_id}{r.blocked ? ' ⛔ blocked' : r.watchlisted ? ' ⚠ flagged' : ''}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Transaction amount (₹)">
                <input className="input" type="number" min="1" step="0.01" value={form.amount} onChange={set('amount')} placeholder="e.g. 80000" />
              </Field>
              <Field label="Fraud scenario">
                <select className="input" value={form.scenario} onChange={set('scenario')}>
                  <option value="">— Select the fraud type —</option>
                  {ctx.scenarios.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
                </select>
              </Field>
            </div>
            {receiver?.watchlisted && <div className="small" style={{ color: 'var(--danger)' }}>⚠ {receiver.name} is flagged on the watchlist.</div>}

            <button className="btn btn-danger btn-lg" disabled={!!busy}>
              {busy === 'transfer' ? 'Fraud engine checking…'
                : `Attempt Transaction${form.amount ? ` · ${money(form.amount)}` : ''}${victim ? ` from ${victim.name.split(' ')[0]}’s account` : ''}`}
            </button>
            <p className="small muted">
              The attempt shows as Processing until it completes, then as Success (money transferred) or Cancelled (no money moved).
            </p>
          </div>
        </form>

        <div className="card" ref={resultRef}>
          <div className="card-head">
            <h2>Fraud detection result</h2>
            {pendingId && <span className="row small muted"><span className="live-dot" /> processing</span>}
          </div>
          <div className="card-body">
            {result ? <DetectionResult result={result} />
              : <Empty icon="🛡️" title="No attempt yet">Attempt a transaction and the engine’s decision appears here: every rule, the risk score, the reason, the owner’s answer and whether money moved.</Empty>}
          </div>
        </div>
      </div>

      {/* Recent attempts */}
      <div className="card mt-24">
        <div className="card-head"><h2>Recent fraud attempts</h2><Link to="/frauder/history" className="small">View all →</Link></div>
        {history.length === 0 ? <Empty title="No attempts yet" /> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Time</th><th>Target</th><th>Action</th><th>City · IP</th><th>Risk factors</th><th>Outcome</th></tr></thead>
              <tbody>
                {history.slice(0, 8).map((a, i) => (
                  <tr key={i} className={a.transaction_id ? 'clickable' : ''}
                      onClick={() => a.transaction_id && get(`/frauder/transactions/${a.transaction_id}`).then(setResult).then(() => resultRef.current?.scrollIntoView({ behavior: 'smooth' }))}>
                    <td className="small mono">{timeOnly(a.at)}</td>
                    <td className="small">{a.victim}</td>
                    <td className="small"><strong>{a.summary}</strong></td>
                    <td className="small muted">{a.detail}</td>
                    <td>{a.rules ? <RuleChips rules={a.rules} /> : <span className="muted small">—</span>}</td>
                    <td>{a.type === 'TRANSFER' ? <OutcomeBadge label={a.outcome_label} />
                      : <span className={`badge ${a.outcome === 'SUCCESS' ? 'b-amber' : 'b-slate'}`}>{a.outcome === 'SUCCESS' ? 'Logged in' : 'Failed'}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {confirmReset && (
        <Modal title="Reset fraud attempts?" onClose={() => setConfirmReset(false)} footer={<>
          <button className="btn btn-ghost" onClick={() => setConfirmReset(false)}>Cancel</button>
          <button className="btn btn-danger" disabled={busy === 'reset'} onClick={reset}>Reset</button>
        </>}>
          <p>Every Frauder transfer is reversed (approved ones give the money back) and removed, together with the attacker logins, devices, OTP attempts, confirmations and alerts. Accounts locked by your attempts are unlocked.</p>
          <p className="muted small mt-8">Genuine payments made by the User are kept. Receiver accounts blocked because of your attempts are unblocked; blocks from genuine customer reports stay.</p>
        </Modal>
      )}
    </>
  );
}
