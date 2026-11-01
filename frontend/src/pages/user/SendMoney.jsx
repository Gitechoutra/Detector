import jsQR from 'jsqr';
import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { errorMessage, get, post } from '../../api/client';
import { useToast } from '../../components/Toast';
import SecurityConfirmation from '../../components/SecurityConfirmation';
import { Field, PageHead, RiskScore, StatusBadge } from '../../components/ui';
import { useApi } from '../../hooks';
import { money } from '../../utils/format';

const METHODS = [['UPI', '⚡ UPI'], ['QR', '🔳 QR Code'], ['BANK_TRANSFER', '🏦 Bank Transfer']];
const newKey = () => (window.crypto?.randomUUID ? window.crypto.randomUUID() : String(Date.now() + Math.random()));

async function decodeQrImage(file) {
  const bitmap = await createImageBitmap(file);
  const canvas = document.createElement('canvas');
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(bitmap, 0, 0);
  const { data, width, height } = ctx.getImageData(0, 0, canvas.width, canvas.height);
  return jsQR(data, width, height)?.data || null;
}

export default function SendMoney() {
  const toast = useToast();
  const { data: dash, reload } = useApi('/user/dashboard');
  const [locations, setLocations] = useState([]);
  const [method, setMethod] = useState('UPI');
  const [form, setForm] = useState({ upi_id: '', qr_payload: '', account_number: '', ifsc: '', amount: '', remarks: '', location_id: '' });
  const [payee, setPayee] = useState(null);
  const [checking, setChecking] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);
  const [idemKey, setIdemKey] = useState(newKey);

  useEffect(() => {
    get('/meta/locations').then(setLocations).catch(() => {});
  }, []);

  const set = (k) => (e) => {
    setForm((f) => ({ ...f, [k]: e.target.value }));
    if (['upi_id', 'qr_payload', 'account_number', 'ifsc'].includes(k)) setPayee(null);
  };

  const receiverBody = useMemo(() => ({
    payment_method: method,
    ...(method === 'UPI' && { upi_id: form.upi_id.trim() }),
    ...(method === 'QR' && { qr_payload: form.qr_payload.trim() }),
    ...(method === 'BANK_TRANSFER' && { account_number: form.account_number.trim(), ifsc: form.ifsc.trim() }),
  }), [method, form]);

  const lookup = async () => {
    setChecking(true);
    setError('');
    try {
      const res = await post('/user/receivers/lookup', receiverBody);
      setPayee(res.data);
    } catch (e) {
      setPayee(null);
      setError(errorMessage(e));
    } finally {
      setChecking(false);
    }
  };

  const onQrFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const payload = await decodeQrImage(file);
      if (!payload) throw new Error('No QR code found in this image.');
      setForm((f) => ({ ...f, qr_payload: payload }));
      setPayee(null);
      toast('QR code scanned.', 'success');
    } catch (err) {
      setError(err.message);
    }
  };

  const send = async (e) => {
    e.preventDefault();
    setSending(true);
    setError('');
    try {
      const res = await post('/transactions/send',
        { ...receiverBody, amount: form.amount, remarks: form.remarks || null, location_id: form.location_id || null },
        { headers: { 'Idempotency-Key': idemKey } });
      setResult({ ...res.data, message: res.message });
      const tone = { COMPLETED: 'success', UNDER_REVIEW: 'warning', BLOCKED: 'error' }[res.data.status] || 'info';
      // A flagged payment asks for the owner's answer on this page and the dashboard.
      toast(res.message, tone);
      reload(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSending(false);
    }
  };

  const reset = () => {
    setResult(null);
    setPayee(null);
    setIdemKey(newKey());
    setForm((f) => ({ ...f, amount: '', remarks: '' }));
  };

  const canLookup = (method === 'UPI' && form.upi_id) || (method === 'QR' && form.qr_payload) ||
    (method === 'BANK_TRANSFER' && form.account_number && form.ifsc);

  return (
    <>
      <PageHead title="Send money" subtitle="Every payment is checked by the fraud detection system before any money moves." />
      <div className="grid grid-main">
        <div className="card card-pad">
          {result ? (
            <ResultPanel result={result} onAgain={reset} onAnswered={async () => {
              reload(true);
              try { setResult({ ...(await get(`/user/transactions/${result.id}`)), message: null }); } catch { /* keep the last result */ }
            }} />
          ) : (
            <form className="form-grid" onSubmit={send}>
              <div className="segmented" role="tablist">
                {METHODS.map(([m, label]) => (
                  <button type="button" key={m} className={method === m ? 'active' : ''} onClick={() => { setMethod(m); setPayee(null); setError(''); }}>{label}</button>
                ))}
              </div>

              {method === 'UPI' && (
                <Field label="Receiver UPI ID" hint="Try priya@fsbank, amit@fsbank, or quickcash@fsbank (watch-listed).">
                  <input className="input" value={form.upi_id} onChange={set('upi_id')} placeholder="name@fsbank" required />
                </Field>
              )}
              {method === 'QR' && (
                <>
                  <Field label="Scan QR code image" hint="Upload a screenshot of the receiver's QR (Receiver → My QR & UPI → Download).">
                    <input className="input" type="file" accept="image/*" onChange={onQrFile} />
                  </Field>
                  <Field label="…or paste QR data">
                    <input className="input mono" value={form.qr_payload} onChange={set('qr_payload')} placeholder="upi://pay?pa=…" required />
                  </Field>
                </>
              )}
              {method === 'BANK_TRANSFER' && (
                <div className="grid grid-2">
                  <Field label="Account number"><input className="input mono" value={form.account_number} onChange={set('account_number')} required /></Field>
                  <Field label="IFSC"><input className="input mono" value={form.ifsc} onChange={set('ifsc')} placeholder="FSBK0000103" required /></Field>
                </div>
              )}

              <div className="row">
                <button type="button" className="btn btn-ghost btn-sm" disabled={!canLookup || checking} onClick={lookup}>
                  {checking ? 'Checking…' : 'Verify receiver'}
                </button>
                {payee && <span className="badge b-green">✓ {payee.name} · {payee.account_number}</span>}
              </div>

              <Field label="Amount (₹)">
                <input className="input input-amount" type="number" min="1" step="0.01" value={form.amount} onChange={set('amount')} placeholder="0.00" required />
              </Field>
              <div className="grid grid-2">
                <Field label="Remarks (optional)"><input className="input" maxLength={140} value={form.remarks} onChange={set('remarks')} placeholder="Rent, dinner…" /></Field>
                <Field label="Your location (simulated)" hint="Changing city quickly can trigger R3 Impossible travel.">
                  <select className="input" value={form.location_id} onChange={set('location_id')}>
                    <option value="">Current login location</option>
                    {locations.map((l) => <option key={l.id} value={l.id}>{l.city}</option>)}
                  </select>
                </Field>
              </div>

              {error && <div className="notice notice-danger">⚠ {error}</div>}
              <button className="btn btn-primary btn-lg" disabled={sending}>
                {sending ? 'Checking for fraud…' : `Send ${form.amount ? money(form.amount) : 'money'}`}
              </button>
            </form>
          )}
        </div>

        <div className="stack">
          <div className="card card-pad balance-card">
            <div className="muted small">Available balance</div>
            <div className="balance-amount">{dash ? money(dash.account.balance) : '…'}</div>
            <div className="muted small">{dash?.account.upi_id}</div>
          </div>
          <div className="card card-pad">
            <h3>How your payment is checked</h3>
            <ol className="small muted" style={{ paddingLeft: 18, margin: '8px 0 0', display: 'grid', gap: 6 }}>
              <li>Saved and checked against 9 SQL fraud rules in one database transaction.</li>
              <li>Risk score = sum of the weights of the rules that fire (max 100).</li>
              <li>Low risk score (below 40) → sent instantly.</li>
              <li>High risk score (70 or more) → blocked instantly; no money leaves your account.</li>
              <li>In between → held, and you are asked <strong>“Did you initiate this transaction?”</strong> YES sends it, NO blocks it.</li>
            </ol>
          </div>
        </div>
      </div>
    </>
  );
}

function ResultPanel({ result, onAgain, onAnswered }) {
  const tone = { COMPLETED: 'notice-success', UNDER_REVIEW: 'notice-warn', BLOCKED: 'notice-danger' }[result.status] || 'notice-info';
  const icon = { COMPLETED: '✅', UNDER_REVIEW: '⏸', BLOCKED: '⛔' }[result.status] || 'ℹ';
  if (result.confirmation?.status === 'PENDING') {
    return (
      <div className="stack">
        <SecurityConfirmation items={[result]} onChange={onAnswered} />
        <div className="row wrap"><Link className="btn btn-ghost" to="/user/transactions">View history</Link></div>
      </div>
    );
  }
  return (
    <div className="stack">
      {result.final_reason && result.status !== 'UNDER_REVIEW' && (
        <div className={`notice ${result.status === 'COMPLETED' ? 'notice-success' : 'notice-danger'}`}>{result.final_reason}</div>
      )}
      <div className={`notice ${tone}`} style={{ display: 'block', padding: 18 }}>
        <div className="row-between">
          <strong style={{ fontSize: 17 }}>{icon} {result.message || result.outcome_label}</strong>
          <StatusBadge status={result.display_status || result.status} />
        </div>
        <div style={{ fontSize: 26, fontWeight: 700, margin: '10px 0 4px' }}>{money(result.amount)}</div>
        <div className="small">to {result.receiver.name} ({result.receiver.upi_id}) · Ref {result.txn_ref}</div>
        {result.replayed && <div className="small mt-8">This was a duplicate submission; the original payment is shown.</div>}
        {result.risk_explanation && <div className="small mt-8" style={{ fontWeight: 500 }}>{result.risk_explanation}</div>}
      </div>
      <div className="row"><span className="muted">Risk score</span><RiskScore score={result.risk_score} /></div>
      {result.rules?.length > 0 ? (
        <div>
          <h3>Checks that flagged this payment</h3>
          <ul className="small" style={{ paddingLeft: 18, margin: '6px 0 0' }}>
            {result.rules.map((r) => <li key={r.code}><strong>{r.code}</strong> – {r.reason}</li>)}
          </ul>
        </div>
      ) : <p className="muted small">No fraud rules fired.</p>}
      <div className="row wrap">
        <button className="btn btn-ghost" onClick={onAgain}>Send another payment</button>
        <Link className="btn btn-ghost" to="/user/transactions">View history</Link>
      </div>
    </div>
  );
}
