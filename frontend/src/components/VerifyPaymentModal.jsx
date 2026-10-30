import { useEffect, useRef, useState } from 'react';
import { errorMessage, post } from '../api/client';
import { money } from '../utils/format';
import { useToast } from './Toast';
import { Field, Modal, RiskScore, RuleChips } from './ui';

/** Step-up verification for a payment held for review: simulated SMS OTP +
 *  password, then the backend re-runs every fraud rule before releasing.
 *  Requesting the OTP counts as the owner's YES; `initialChallenge` is passed
 *  when the YES button already requested it. */
export default function VerifyPaymentModal({ txn, initialChallenge, onClose, onDone }) {
  const toast = useToast();
  const [challenge, setChallenge] = useState(initialChallenge || null);
  const [otp, setOtp] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);

  const requestOtp = async () => {
    setBusy(true);
    setError('');
    try {
      const res = await post(`/transactions/${txn.id}/verification/start`);
      setChallenge(res.data);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  const requested = useRef(false);
  useEffect(() => {
    // Ref guard: StrictMode runs effects twice in dev, which would issue two OTPs.
    if (requested.current || initialChallenge) return;
    requested.current = true;
    requestOtp();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const confirm = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const res = await post(`/transactions/${txn.id}/verification/confirm`, { otp, password });
      setResult(res.data);
      toast(res.message, res.data.outcome === 'released' ? 'success' : 'warning');
      onDone?.();
    } catch (err) {
      setError(errorMessage(err));
      if (err.response?.data?.error?.code === 'VERIFICATION_FAILED') onDone?.();
    } finally {
      setBusy(false);
    }
  };

  const OUTCOME = {
    released: ['notice-success', 'Payment released', 'Your identity was verified and a fresh fraud check passed. The money has been sent.'],
    escalated: ['notice-warn', 'Sent to the fraud team', 'Verification succeeded, but the payment still carries risk unrelated to your identity. A fraud analyst will review it; nothing has been debited.'],
    blocked: ['notice-danger', 'Payment blocked', 'The fresh fraud check blocked this payment. No money has left your account.'],
    declined: ['notice-danger', 'Payment declined', 'The payment could not be completed.'],
  };

  return (
    <Modal title="Confirm it was you" onClose={onClose}>
      <div className="stack">
        <div className="notice notice-warn">
          <span>⏸</span>
          <div>
            <strong>{money(txn.amount)} to {txn.receiver.name}</strong> is on hold.
            <div className="small mt-8">Flagged by <RuleChips rules={txn.rules} />. Verifying proves it is you – it does not skip the fraud checks: every rule is re-evaluated afterwards.</div>
          </div>
        </div>

        {result ? (
          <div className={`notice ${OUTCOME[result.outcome][0]}`} style={{ display: 'block' }}>
            <strong>{OUTCOME[result.outcome][1]}</strong>
            <p className="small mt-8">{result.transaction?.final_reason || OUTCOME[result.outcome][2]}</p>
            <div className="row mt-8 small">New risk score <RiskScore score={result.risk_score} /></div>
            {result.mitigations?.length > 0 && (
              <p className="small mt-8">Cleared by verification: <RuleChips rules={result.mitigations} /></p>
            )}
            {result.hits?.length > 0 && <p className="small mt-8">Still applies: <RuleChips rules={result.hits} /></p>}
            <button className="btn btn-primary btn-sm mt-16" onClick={onClose}>Done</button>
          </div>
        ) : (
          <form className="form-grid" onSubmit={confirm}>
            {challenge && (
              <div>
                <div className="small muted" style={{ marginBottom: 6 }}>📱 Simulated SMS to your registered mobile</div>
                <div className="sms">{challenge.simulated_sms}</div>
              </div>
            )}
            <Field label="OTP">
              <input className="input mono" inputMode="numeric" maxLength={6} value={otp}
                     onChange={(e) => setOtp(e.target.value.replace(/\D/g, ''))} placeholder="6-digit OTP" required />
            </Field>
            <Field label="Login password" hint="Second factor: re-enter your password.">
              <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </Field>
            {error && <div className="notice notice-danger">⚠ {error}</div>}
            <div className="row-between">
              <button type="button" className="link-btn small" onClick={requestOtp} disabled={busy}>Resend OTP</button>
              <button className="btn btn-primary" disabled={busy || otp.length !== 6 || !password}>
                {busy ? 'Verifying…' : 'Verify & re-check'}
              </button>
            </div>
          </form>
        )}
      </div>
    </Modal>
  );
}
