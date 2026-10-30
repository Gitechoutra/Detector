import { useState } from 'react';
import { errorMessage, post } from '../api/client';
import { dateTime, money, timeOnly } from '../utils/format';
import { useToast } from './Toast';
import { RuleChips } from './ui';
import VerifyPaymentModal from './VerifyPaymentModal';

const minutesLeft = (iso) => Math.max(0, Math.ceil((new Date(iso) - Date.now()) / 60000));

/** "Security Alert: Was this transaction initiated by you?" – one card per held
 *  payment. The answer is checked on the server (owner, expiry, duplicates);
 *  YES leads to OTP + password and a full re-check, NO blocks immediately. */
export default function SecurityConfirmation({ items, onChange }) {
  const toast = useToast();
  const [busy, setBusy] = useState(null);
  const [verifying, setVerifying] = useState(null);

  const answer = async (txn, response) => {
    setBusy(`${txn.id}-${response}`);
    try {
      const res = await post(`/transactions/${txn.id}/confirmation`, { response });
      if (response === 'NO') toast(res.message, 'success', 'Payment blocked');
      else setVerifying({ txn: res.data.transaction, challenge: res.data.verification });
    } catch (e) {
      toast(errorMessage(e), 'error');
    } finally {
      setBusy(null);
      onChange?.();
    }
  };

  if (!items?.length) return null;
  return (
    <div className="stack" style={{ marginBottom: 16 }}>
      {items.map((t) => {
        const saidYes = t.confirmation?.response === 'YES';
        const left = t.confirmation?.expires_at ? minutesLeft(t.confirmation.expires_at) : null;
        return (
          <div className="security-alert" key={t.id} role="alert">
            <div className="security-alert-head">
              <div className="security-alert-icon">🔐</div>
              <div style={{ flex: 1 }}>
                <div className="row-between wrap">
                  <h2>Security Alert: Was this transaction initiated by you?</h2>
                  {t.is_simulated && <span className="badge b-purple">Frauder attempt (demo)</span>}
                </div>
                <p className="small muted mt-8">
                  This payment is on hold and nothing has been debited.
                  {left != null && <> Answer by <span className="expiry-chip">{timeOnly(t.confirmation.expires_at)} ({left} min left)</span> – unanswered payments are never approved.</>}
                </p>
              </div>
            </div>

            <dl className="kv mt-16">
              <dt>Amount</dt><dd className="security-alert-amount">{money(t.amount)}</dd>
              <dt>Receiver</dt><dd>{t.receiver.name} · <span className="mono">{t.receiver.upi_id}</span></dd>
              <dt>Transaction ID</dt><dd className="mono">{t.txn_ref}</dd>
              <dt>Date & time</dt><dd>{dateTime(t.txn_time)}</dd>
              <dt>Device</dt><dd>{t.device_name || 'Not available'}{t.ip_address && <span className="muted"> · IP <span className="mono">{t.ip_address}</span></span>}</dd>
              <dt>Location</dt><dd>{[t.target_location, t.city].filter(Boolean).join(', ') || 'Not available'}</dd>
              <dt>Why flagged</dt><dd>{t.risk_explanation} <span style={{ marginLeft: 4 }}><RuleChips rules={t.rules} /></span></dd>
            </dl>

            {saidYes ? (
              <div className="notice notice-info mt-16 row-between wrap">
                <span>You answered <strong>YES</strong>. Enter the OTP and your password to finish – every fraud rule is then checked again.</span>
                <button className="btn btn-primary btn-sm" onClick={() => setVerifying({ txn: t })}>Enter OTP</button>
              </div>
            ) : (
              <>
                <div className="security-alert-actions">
                  <button className="btn btn-success" disabled={!!busy} onClick={() => answer(t, 'YES')}>
                    {busy === `${t.id}-YES` ? 'Sending OTP…' : '✓ YES, IT WAS ME'}
                  </button>
                  <button className="btn btn-danger" disabled={!!busy} onClick={() => answer(t, 'NO')}>
                    {busy === `${t.id}-NO` ? 'Blocking…' : '✕ NO, NOT ME'}
                  </button>
                </div>
                <p className="small muted mt-8">YES does not approve the payment by itself: you verify with an OTP and your password, then the fraud engine re-checks it. NO blocks it immediately and alerts our fraud team.</p>
              </>
            )}
          </div>
        );
      })}
      {verifying && (
        <VerifyPaymentModal txn={verifying.txn} initialChallenge={verifying.challenge}
                            onClose={() => { setVerifying(null); onChange?.(); }} onDone={onChange} />
      )}
    </div>
  );
}
