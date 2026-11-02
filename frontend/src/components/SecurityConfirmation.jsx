import { useState } from 'react';
import { errorMessage, post } from '../api/client';
import { dateTime, money, timeOnly } from '../utils/format';
import { useToast } from './Toast';
import { RiskScore } from './ui';

const minutesLeft = (iso) => Math.max(0, Math.ceil((new Date(iso) - Date.now()) / 60000));
const OTP_PATTERN = /^\d{6}$/;

/** Answers one held payment. The server checks owner, expiry and duplicates.
 *  YES sends an OTP to the registered phone and e-mail (nothing moves yet);
 *  NO stops the payment and blocks the receiver account. */
export function useConfirmationAnswer(onChange, onOtpSent) {
  const toast = useToast();
  const [busy, setBusy] = useState(null);
  const answer = async (txn, response) => {
    setBusy(`${txn.id}-${response}`);
    try {
      const res = await post(`/transactions/${txn.id}/confirmation`, { response });
      if (response === 'NO') toast(res.message, 'success', 'Transaction stopped');
      else {
        toast(res.message, 'info', 'OTP sent');
        onOtpSent?.(res.data);
      }
    } catch (e) {
      toast(errorMessage(e), 'error');
    } finally {
      setBusy(null);
      onChange?.();
    }
  };
  return { answer, busy };
}

/** The OTP step after YES. Only a correct, unexpired code authorizes the payment. */
const otpIn = (sms) => sms?.match(/OTP (\d{6})/)?.[1] || null;

export function OtpEntry({ txn, sentTo, demoOtp, onDone }) {
  const toast = useToast();
  const [otp, setOtp] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [contacts, setContacts] = useState(sentTo);
  const [resentOtp, setResentOtp] = useState(null);
  const shownOtp = resentOtp || demoOtp || txn.demo_otp;
  const otpInfo = txn.confirmation?.otp;

  const verify = async (e) => {
    e.preventDefault();
    if (!OTP_PATTERN.test(otp)) {
      setError('Enter the 6-digit code that was sent to you.');
      return;
    }
    setBusy('verify');
    setError('');
    try {
      const res = await post(`/transactions/${txn.id}/verification/confirm`, { otp });
      const ok = res.data.outcome === 'authorized';
      toast(res.message, ok ? 'success' : 'error', ok ? 'Payment successful' : 'Payment not processed');
      onDone?.();
    } catch (err) {
      setError(errorMessage(err));
      const code = err.response?.data?.error?.code;
      if (code === 'VERIFICATION_FAILED' || code === 'CONFIRMATION_EXPIRED') onDone?.();
    } finally {
      setBusy('');
      setOtp('');
    }
  };

  const resend = async () => {
    setBusy('resend');
    setError('');
    try {
      const res = await post(`/transactions/${txn.id}/verification/start`);
      setContacts(res.data.sent_to);
      setResentOtp(otpIn(res.data.simulated_sms));
      toast(res.message, 'info', 'New OTP sent');
      onDone?.();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy('');
    }
  };

  return (
    <form className="otp-step mt-16" onSubmit={verify} noValidate>
      <div className="row-between wrap">
        <strong>🔑 Enter the OTP to authorize this payment</strong>
        {otpInfo?.expires_at && otpInfo.status === 'SENT' && (
          <span className="expiry-chip">valid until {timeOnly(otpInfo.expires_at)}</span>
        )}
      </div>
      <p className="small muted mt-8">
        You answered YES. A one-time password was sent to {contacts?.length ? contacts.join(' and ') : 'your registered phone and e-mail'}
        {' '}(simulated delivery – the code is shown below). Nothing moves until the OTP is verified.
      </p>
      {otpInfo?.status === 'EXPIRED' && <div className="notice notice-warn small mt-8">This OTP has expired. Send a new one.</div>}
      <div className="row wrap mt-8">
        <input className="input input-otp mono" inputMode="numeric" autoComplete="one-time-code" maxLength={6}
               placeholder="6-digit OTP" value={otp} aria-label="One-time password"
               onChange={(e) => { setOtp(e.target.value.replace(/\D/g, '').slice(0, 6)); setError(''); }} />
        <button className="btn btn-success" disabled={!!busy || otp.length !== 6}>
          {busy === 'verify' ? 'Verifying…' : 'Verify & authorize'}
        </button>
        <button type="button" className="btn btn-ghost" disabled={!!busy} onClick={resend}>
          {busy === 'resend' ? 'Sending…' : 'Resend OTP'}
        </button>
      </div>
      {shownOtp && (
        <div className="demo-otp mt-8">
          <span>📱 Demo OTP (simulated SMS): <strong className="mono">{shownOtp}</strong></span>
          <button type="button" className="link-btn" onClick={() => { setOtp(shownOtp); setError(''); }}>Use this code</button>
        </div>
      )}
      {otpInfo?.attempts > 0 && otpInfo.status === 'SENT' && (
        <div className="small muted mt-8">{otpInfo.max_attempts - otpInfo.attempts} attempt(s) left before the payment is blocked.</div>
      )}
      {error && <div className="notice notice-danger small mt-8">⚠ {error}</div>}
    </form>
  );
}

/** "Suspicious transaction detected" – one card per payment flagged by any risk factor. */
export default function SecurityConfirmation({ items, onChange }) {
  const [sentTo, setSentTo] = useState({});
  const [codes, setCodes] = useState({});
  const { answer, busy } = useConfirmationAnswer(onChange, (data) => {
    setSentTo((s) => ({ ...s, [data.transaction.id]: data.otp.sent_to }));
    setCodes((c) => ({ ...c, [data.transaction.id]: otpIn(data.otp.simulated_sms) }));
  });

  if (!items?.length) return null;
  return (
    <div className="stack" style={{ marginBottom: 16 }}>
      {items.map((t) => {
        const left = t.confirmation?.expires_at ? minutesLeft(t.confirmation.expires_at) : null;
        const awaitingOtp = t.confirmation?.status === 'CONFIRMED';
        return (
          <div className="security-alert" key={t.id} role="alert">
            <div className="security-alert-head">
              <div className="security-alert-icon">🔐</div>
              <div style={{ flex: 1 }}>
                <div className="row-between wrap">
                  <h2>Suspicious transaction detected</h2>
                  {t.is_simulated && <span className="badge b-purple">Frauder attempt</span>}
                </div>
                <p className="mt-8"><strong>Did you initiate this transaction?</strong></p>
                <p className="small muted mt-8">
                  Nothing has been debited yet.
                  {left != null && <> Answer by <span className="expiry-chip">{timeOnly(t.confirmation.expires_at)} ({left} min left)</span> – if you don't answer, the payment expires and is never sent.</>}
                </p>
              </div>
            </div>

            <dl className="kv mt-16">
              <dt>Amount</dt><dd className="security-alert-amount">{money(t.amount)}</dd>
              <dt>Receiver</dt><dd>{t.receiver.name} · <span className="mono">{t.receiver.upi_id}</span></dd>
              <dt>Transaction ID</dt><dd className="mono">{t.txn_ref}</dd>
              <dt>Date & time</dt><dd>{dateTime(t.txn_time)}</dd>
              {(t.device_name || t.ip_address) && <><dt>Device</dt><dd>{t.device_name || 'Not available'}{t.ip_address && <span className="muted"> · IP <span className="mono">{t.ip_address}</span></span>}</dd></>}
              {(t.target_location || t.city) && <><dt>Location</dt><dd>{[t.target_location, t.city].filter(Boolean).join(', ')}</dd></>}
              <dt>Risk score</dt><dd><RiskScore score={t.risk_score} /> <span className="small muted">/ 100{t.risk_score >= 70 && ' · high risk'}</span></dd>
              <dt>Why flagged</dt><dd>{t.risk_explanation}</dd>
            </dl>

            {t.rules?.length > 0 && (
              <div className="mt-16">
                <div className="small muted" style={{ marginBottom: 6 }}>Risk factors detected</div>
                <ul className="rule-reasons">
                  {t.rules.map((r) => (
                    <li key={r.code}><span className="badge b-amber">{r.code}</span> <strong>{r.name}</strong> – {r.reason}</li>
                  ))}
                </ul>
              </div>
            )}

            {awaitingOtp ? (
              <OtpEntry txn={t} sentTo={sentTo[t.id]} demoOtp={t.demo_otp || codes[t.id]} onDone={onChange} />
            ) : (
              <>
                <div className="security-alert-actions">
                  <button className="btn btn-success" disabled={!!busy} onClick={() => answer(t, 'YES')}>
                    {busy === `${t.id}-YES` ? 'Sending OTP…' : '✓ YES, I INITIATED THIS TRANSACTION'}
                  </button>
                  <button className="btn btn-danger" disabled={!!busy} onClick={() => answer(t, 'NO')}>
                    {busy === `${t.id}-NO` ? 'Stopping…' : '✕ NO, I DID NOT INITIATE THIS TRANSACTION'}
                  </button>
                </div>
                <p className="small muted mt-8">YES sends an OTP to your registered phone and e-mail; the payment goes through only after the OTP is verified. NO stops it immediately, no money moves, and the receiver account is flagged and blocked.</p>
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}
