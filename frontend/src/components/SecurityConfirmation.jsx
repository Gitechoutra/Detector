import { useState } from 'react';
import { errorMessage, post } from '../api/client';
import { dateTime, money, timeOnly } from '../utils/format';
import { useToast } from './Toast';
import { RiskScore } from './ui';

const minutesLeft = (iso) => Math.max(0, Math.ceil((new Date(iso) - Date.now()) / 60000));

/** Answers one held payment. The server checks owner, expiry and duplicates;
 *  YES authorizes (after re-validating balance and accounts), NO blocks. */
export function useConfirmationAnswer(onChange) {
  const toast = useToast();
  const [busy, setBusy] = useState(null);
  const answer = async (txn, response) => {
    setBusy(`${txn.id}-${response}`);
    try {
      const res = await post(`/transactions/${txn.id}/confirmation`, { response });
      const ok = res.data.outcome === 'authorized' || response === 'NO';
      toast(res.message, ok ? 'success' : 'error',
            response === 'NO' ? 'Payment blocked' : ok ? 'Payment successful' : 'Payment not processed');
    } catch (e) {
      toast(errorMessage(e), 'error');
    } finally {
      setBusy(null);
      onChange?.();
    }
  };
  return { answer, busy };
}

/** "Security Verification Required" – one card per payment flagged by any fraud rule. */
export default function SecurityConfirmation({ items, onChange }) {
  const { answer, busy } = useConfirmationAnswer(onChange);

  if (!items?.length) return null;
  return (
    <div className="stack" style={{ marginBottom: 16 }}>
      {items.map((t) => {
        const left = t.confirmation?.expires_at ? minutesLeft(t.confirmation.expires_at) : null;
        return (
          <div className="security-alert" key={t.id} role="alert">
            <div className="security-alert-head">
              <div className="security-alert-icon">🔐</div>
              <div style={{ flex: 1 }}>
                <div className="row-between wrap">
                  <h2>Security Verification Required</h2>
                  {t.is_simulated && <span className="badge b-purple">Frauder attempt (demo)</span>}
                </div>
                <p className="mt-8">A transaction is being attempted from your account. Please confirm whether you initiated this transaction.</p>
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
              <dt>Risk score</dt><dd><RiskScore score={t.risk_score} /> <span className="small muted">/ 100</span></dd>
              <dt>Why flagged</dt><dd>{t.risk_explanation}</dd>
            </dl>

            <div className="mt-16">
              <div className="small muted" style={{ marginBottom: 6 }}>Triggered fraud rules</div>
              <ul className="rule-reasons">
                {t.rules.map((r) => (
                  <li key={r.code}><span className="badge b-amber">{r.code}</span> <strong>{r.name}</strong> – {r.reason}</li>
                ))}
              </ul>
            </div>

            <div className="security-alert-actions">
              <button className="btn btn-success" disabled={!!busy} onClick={() => answer(t, 'YES')}>
                {busy === `${t.id}-YES` ? 'Authorizing…' : '✓ YES, I INITIATED THIS TRANSACTION'}
              </button>
              <button className="btn btn-danger" disabled={!!busy} onClick={() => answer(t, 'NO')}>
                {busy === `${t.id}-NO` ? 'Blocking…' : '✕ NO, I DID NOT INITIATE THIS TRANSACTION'}
              </button>
            </div>
            <p className="small muted mt-8">YES authorizes the payment: after a final balance and account check, the money is transferred. NO blocks it immediately, no money moves, and our fraud team is alerted.</p>
          </div>
        );
      })}
    </div>
  );
}
