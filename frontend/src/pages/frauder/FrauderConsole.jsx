import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { errorMessage, get, post } from '../../api/client';
import DetectionResult from '../../components/DetectionResult';
import { useToast } from '../../components/Toast';
import { Empty, Field, Loading, Modal, OutcomeBadge, PageHead, RuleChips } from '../../components/ui';
import { money, timeOnly } from '../../utils/format';

const newKey = () => (window.crypto?.randomUUID ? window.crypto.randomUUID() : String(Date.now() + Math.random()));
// Every field starts empty: nothing is guessed, geolocated or pre-selected.
const BLANK = {
  victim_id: '', receiver_id: '', amount: '', scenario: '',
  city: '', target_location: '', device_type: '', device_id: '', use_registered_device: false, ip_address: '',
  use_clock: false, demo_time: '',
};
const STORE = 'frauder-attack-form';
const IPV4 = /^(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)(\.(25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)){3}$/;
const looksLikeIp = (v) => IPV4.test(v) || (v.includes(':') && /^[0-9a-fA-F:.]+$/.test(v));

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
  const [guide, setGuide] = useState([]);
  const [history, setHistory] = useState([]);
  const [form, setForm] = useState(loadForm);
  const [busy, setBusy] = useState('');
  const [result, setResult] = useState(null);
  const [confirmReset, setConfirmReset] = useState(false);
  const keyRef = useRef(newKey());
  const resultRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const [c, g, h] = await Promise.all([get('/frauder/context'), get('/frauder/rule-guide'), get('/frauder/attempts')]);
      setCtx(c);
      setGuide(g);
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

  // While the owner has not answered, follow the attempt live.
  const pendingId = result?.status === 'UNDER_REVIEW' ? result.id : null;
  useEffect(() => {
    if (!pendingId) return undefined;
    const timer = setInterval(async () => {
      try {
        const fresh = await get(`/frauder/transactions/${pendingId}`);
        setResult((prev) => {
          if (!prev || prev.id !== fresh.id) return prev;
          if (prev.outcome_label !== fresh.outcome_label) {
            toast(fresh.final_reason || fresh.outcome_label, fresh.status === 'COMPLETED' ? 'warning' : 'info', fresh.outcome_label);
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
  const hint = guide.find((g) => g.code === form.scenario);
  const set = (k) => (e) => {
    const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
    setForm((f) => ({ ...f, [k]: value }));
  };
  const ipState = !form.ip_address ? null : looksLikeIp(form.ip_address.trim());

  const attackerFields = () => ({
    victim_id: form.victim_id, city: form.city.trim(), target_location: form.target_location.trim(),
    device_type: form.device_type.trim(), device_id: form.device_id.trim(), ip_address: form.ip_address.trim(),
    scenario: form.scenario || null,
  });

  const missing = (forTransfer) => {
    const need = [['victim_id', 'target user account'], ['city', 'target city'], ['ip_address', 'IP address']];
    if (!(forTransfer && form.use_registered_device)) need.push(['device_type', 'device type'], ['device_id', 'device ID']);
    if (forTransfer) need.push(['receiver_id', 'receiver account'], ['amount', 'transaction amount']);
    if (forTransfer && form.use_clock) need.push(['demo_time', 'demo clock time']);
    const gaps = need.filter(([k]) => !String(form[k]).trim()).map(([, label]) => label);
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

  const attemptLogin = (outcome) => {
    if (missing(false)) return;
    run(outcome, async () => {
      const res = await post('/frauder/login-attempt', { ...attackerFields(), outcome });
      toast(res.message, res.data.success ? 'warning' : 'info');
    });
  };

  const attemptOtp = () => {
    if (!form.victim_id) { toast('Select the target user account first.', 'error'); return; }
    run('otp', async () => {
      const res = await post('/frauder/otp-attempt', { victim_id: form.victim_id, ip_address: form.ip_address.trim() });
      toast(res.message, 'info');
    });
  };

  const submit = (e) => {
    e.preventDefault();
    if (missing(true)) return;
    run('transfer', async () => {
      const body = {
        ...attackerFields(), receiver_id: form.receiver_id, amount: form.amount,
        use_registered_device: form.use_registered_device, demo_time: form.use_clock ? form.demo_time : null,
      };
      if (form.use_registered_device) { delete body.device_type; delete body.device_id; }
      const res = await post('/frauder/transfer', body, { headers: { 'Idempotency-Key': keyRef.current } });
      keyRef.current = newKey();
      setResult(res.data);
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
      <PageHead title="Frauder console" subtitle="You type every attacker detail yourself. The SQL fraud engine decides, and then the account owner is asked “Was this you?”.">
        <Link to="/frauder/history" className="btn btn-ghost">Attempt history</Link>
        <button className="btn btn-danger-soft" onClick={() => setConfirmReset(true)}>↺ Reset fraud attempts</button>
      </PageHead>

      <div className="notice notice-info">
        🔒 Controlled impersonation of designated demo accounts only. You never see a password and cannot change balances,
        profiles or rules. City, location, device and IP are <strong>simulated values you enter</strong> – they feed the fraud rules
        but are never treated as a verified identity or location.
      </div>

      {/* Victims – information only */}
      <h2 className="mt-24">Demo accounts you may target</h2>
      <div className="grid grid-3 mt-8">
        {ctx.victims.map((v) => (
          <button key={v.id} type="button" onClick={() => setForm((f) => ({ ...f, victim_id: String(v.id) }))}
                  className="card card-pad" style={{ textAlign: 'left', cursor: 'pointer', font: 'inherit',
                    borderColor: String(v.id) === form.victim_id ? 'var(--accent)' : undefined,
                    background: String(v.id) === form.victim_id ? 'var(--accent-soft)' : undefined }}>
            <div className="row-between">
              <strong>{v.name}</strong>
              {v.status === 'LOCKED' ? <span className="badge b-red">Locked</span> : <span className="badge b-green">Active</span>}
            </div>
            <div className="small muted">{v.upi_id} · home {v.home_city}{v.is_dormant_demo && ' · dormant demo'}</div>
            <div className="stat-value" style={{ fontSize: 20 }}>{money(v.balance)}</div>
            <div className="small muted">
              {v.payments_90d} payment(s) in 90 days{v.average_90d != null && `, avg ${money(v.average_90d)}`} · idle {v.idle_days} d
              {v.failed_login_count > 0 && ` · ${v.failed_login_count} failed login(s)`}
            </div>
          </button>
        ))}
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
                  {ctx.receivers.map((r) => <option key={r.id} value={r.id}>{r.name} · {r.upi_id}{r.watchlisted ? ' ⚠ watch-listed' : ''}</option>)}
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
            {hint && <div className="notice notice-warn small">💡 <span><strong>{hint.code}:</strong> {hint.hint}</span></div>}
            {receiver?.watchlisted && <div className="small" style={{ color: 'var(--danger)' }}>⚠ {receiver.name} is on the watchlist.</div>}

            <div className="sim-panel stack" style={{ gap: 12 }}>
              <div className="row-between wrap">
                <strong>Simulated attacker details</strong>
                <span className="badge b-purple">SIMULATED – typed by you</span>
              </div>
              <div className="grid grid-2" style={{ gap: 12 }}>
                <Field label="Target city" hint="Type or pick – used by R3 (impossible travel).">
                  <input className="input" list="frauder-cities" value={form.city} onChange={set('city')} placeholder="e.g. Delhi" />
                </Field>
                <Field label="Target location" hint="Free text, shown to the account owner.">
                  <input className="input" maxLength={120} value={form.target_location} onChange={set('target_location')} placeholder="e.g. Connaught Place" />
                </Field>
                <Field label="Device type">
                  <input className="input" list="frauder-device-types" maxLength={60} value={form.device_type} onChange={set('device_type')}
                         placeholder="e.g. Android phone" disabled={form.use_registered_device} />
                </Field>
                <Field label="Device ID" hint={victim?.attacker_devices.length ? `Used before on this account: ${victim.attacker_devices.map((d) => d.device_id).join(', ')}` : 'A new ID = an unknown device (R4, R9).'}>
                  <input className="input mono" maxLength={40} value={form.device_id} onChange={set('device_id')}
                         placeholder="e.g. ATK-PHONE-01" disabled={form.use_registered_device} />
                </Field>
                <Field label="IP address" hint={ipState === false ? '⚠ Not a valid IP address' : ipState ? '✓ Valid format' : 'IPv4 or IPv6, e.g. 49.36.12.8'}>
                  <input className="input mono" value={form.ip_address} onChange={set('ip_address')} placeholder="e.g. 49.36.12.8"
                         style={ipState === false ? { borderColor: 'var(--danger)' } : undefined} />
                </Field>
                <div className="stack" style={{ gap: 8, paddingTop: 22 }}>
                  <label className="row small"><input type="checkbox" checked={form.use_registered_device} onChange={set('use_registered_device')} />
                    Use the victim’s registered device (remote-access scam, transfers only)</label>
                  <label className="row small"><input type="checkbox" checked={form.use_clock} onChange={set('use_clock')} /> Use demo clock (R5)</label>
                  {form.use_clock && <input className="input input-sm" type="time" value={form.demo_time} onChange={set('demo_time')} />}
                </div>
              </div>
              <datalist id="frauder-cities">{ctx.cities.map((c) => <option key={c} value={c} />)}</datalist>
              <datalist id="frauder-device-types">{ctx.device_types.map((d) => <option key={d} value={d} />)}</datalist>
            </div>

            <div>
              <div className="small muted" style={{ marginBottom: 6 }}>Login activity on the target account (uses the city, device and IP above):</div>
              <div className="row wrap">
                <button type="button" className="btn btn-ghost" disabled={!!busy} onClick={() => attemptLogin('WRONG_PASSWORD')}>✗ Wrong password</button>
                <button type="button" className="btn btn-ghost" disabled={!!busy} onClick={() => attemptLogin('STOLEN_PASSWORD')}>🔑 Log in with stolen password</button>
                <button type="button" className="btn btn-ghost" disabled={!!busy} onClick={attemptOtp}>Wrong OTP</button>
              </div>
            </div>

            <button className="btn btn-danger btn-lg" disabled={!!busy}>
              {busy === 'transfer' ? 'Fraud engine checking…'
                : `Attempt Transaction${form.amount ? ` · ${money(form.amount)}` : ''}${victim ? ` from ${victim.name.split(' ')[0]}’s account` : ''}`}
            </button>
            <p className="small muted">
              If the engine scores Review, the owner gets “Was this transaction initiated by you?” – log in as them to answer.
              Unanswered requests expire after {ctx.policy.confirmation_expiry_minutes} min ({ctx.policy.expiry_action === 'HOLD' ? 'sent to the fraud team' : 'blocked'}).
              {ctx.policy.hard_block_rules.length > 0 && ` Hard-block rules a YES cannot override: ${ctx.policy.hard_block_rules.join(', ')}.`}
            </p>
          </div>
        </form>

        <div className="card" ref={resultRef}>
          <div className="card-head">
            <h2>Fraud detection result</h2>
            {pendingId && <span className="row small muted"><span className="live-dot" /> waiting for the owner</span>}
          </div>
          <div className="card-body">
            {result ? <DetectionResult result={result} />
              : <Empty icon="🛡️" title="No attempt yet">Attempt a transaction and the engine’s decision appears here: every rule, the risk score, the reason, the owner’s answer and whether money moved.</Empty>}
          </div>
        </div>
      </div>

      {/* Rule guidance – text only */}
      <h2 className="mt-24">Test the 9 Fraud Detection Rules</h2>
      <p className="muted small mt-8">What to type for each rule, using the live thresholds. Nothing is filled in for you, and the backend still decides. On its own a rule may stay below the review threshold (40) – combine signals to reach Review or Block.</p>
      <div className="grid grid-3 mt-16">
        {guide.map((g) => (
          <div key={g.code} className="card scenario-card">
            <div className="row-between">
              <div className="row"><span className="rule-chip">{g.code}</span><strong>{g.title}</strong></div>
              <span className="small muted">weight {g.weight}{!g.active && ' · disabled'}</span>
            </div>
            <p className="small">{g.hint}</p>
            {g.hard_block && <span className="badge b-red" style={{ alignSelf: 'flex-start' }}>Hard block – a YES cannot override</span>}
          </div>
        ))}
      </div>

      {/* Recent attempts */}
      <div className="card mt-24">
        <div className="card-head"><h2>Recent fraud attempts</h2><Link to="/frauder/history" className="small">View all →</Link></div>
        {history.length === 0 ? <Empty title="No attempts yet" /> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Time</th><th>Victim</th><th>Action</th><th>Simulated details</th><th>Rules</th><th>Owner’s answer</th><th>Outcome</th></tr></thead>
              <tbody>
                {history.slice(0, 8).map((a, i) => (
                  <tr key={i} className={a.transaction_id ? 'clickable' : ''}
                      onClick={() => a.transaction_id && get(`/frauder/transactions/${a.transaction_id}`).then(setResult).then(() => resultRef.current?.scrollIntoView({ behavior: 'smooth' }))}>
                    <td className="small mono">{timeOnly(a.at)}</td>
                    <td className="small">{a.victim}</td>
                    <td className="small"><strong>{a.summary}</strong>{a.scenario && <div className="muted">{a.scenario}</div>}</td>
                    <td className="small muted">{a.detail}</td>
                    <td>{a.rules ? <RuleChips rules={a.rules} /> : <span className="muted small">—</span>}</td>
                    <td className="small">{a.confirmation ? (a.confirmation.response || (a.confirmation.status === 'EXPIRED' ? 'no answer' : 'waiting…')) : '—'}</td>
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
          <p className="muted small mt-8">Genuine payments made by the User are kept. Your typed attack details stay in the form.</p>
        </Modal>
      )}
    </>
  );
}
