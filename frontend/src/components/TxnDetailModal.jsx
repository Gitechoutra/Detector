import { dateTime, money, METHOD_LABEL } from '../utils/format';
import { OtpEntry, useConfirmationAnswer } from './SecurityConfirmation';
import { Modal, OutcomeBadge, RiskScore, StatusBadge } from './ui';

export default function TxnDetailModal({ txn, viewer = 'sender', onClose, onChange }) {
  const counterpart = viewer === 'sender' ? txn.receiver : txn.sender;
  const held = viewer === 'sender' && txn.status === 'UNDER_REVIEW';
  const canAct = held && txn.confirmation?.status === 'PENDING';
  const awaitingOtp = held && txn.confirmation?.status === 'CONFIRMED';
  const { answer, busy } = useConfirmationAnswer(() => { onChange?.(); onClose(); });
  return (
    <Modal title={`Payment ${txn.txn_ref}`} onClose={onClose} footer={canAct ? <>
        <button className="btn btn-danger" disabled={!!busy} onClick={() => answer(txn, 'NO')}>✕ NO, I DID NOT INITIATE THIS</button>
        <button className="btn btn-success" disabled={!!busy} onClick={() => answer(txn, 'YES')}>✓ YES, I INITIATED THIS</button>
      </> : null}>
      <div className="stack">
        <div className="row-between">
          <div style={{ fontSize: 26, fontWeight: 700 }}>{money(txn.amount)}</div>
          <div className="row">{txn.confirmation && viewer === 'sender' && <OutcomeBadge label={txn.outcome_label} />}<StatusBadge status={txn.display_status || txn.status} /></div>
        </div>
        {txn.is_simulated && <div className="notice notice-info small">🕵️ Made by the Frauder (simulated attacker) on this demo account.</div>}
        <dl className="kv">
          <dt>{viewer === 'sender' ? 'To' : 'From'}</dt><dd>{counterpart.name} · {counterpart.upi_id}</dd>
          <dt>Method</dt><dd>{METHOD_LABEL[txn.payment_method]}</dd>
          <dt>Date</dt><dd>{dateTime(txn.txn_time)}</dd>
          {txn.city && <><dt>Location</dt><dd>{txn.city}</dd></>}
          {txn.remarks && <><dt>Remarks</dt><dd>{txn.remarks}</dd></>}
          <dt>Risk score</dt><dd><RiskScore score={txn.risk_score} /></dd>
          <dt>Money</dt><dd>{txn.money_moved ? (viewer === 'sender' ? 'Debited' : 'Credited') : 'Not moved'}</dd>
          {viewer === 'sender' && txn.confirmation && <>
            <dt>Your answer</dt>
            <dd>{txn.confirmation.response ? `${txn.confirmation.response === 'YES' ? 'YES, I initiated it' : 'NO, I did not initiate it'} · ${dateTime(txn.confirmation.responded_at)}${txn.confirmation.otp && txn.confirmation.otp.status !== 'NOT_SENT' ? ` · OTP ${txn.confirmation.otp.status.toLowerCase()}` : ''}`
              : txn.confirmation.status === 'EXPIRED' ? 'No answer – expired' : `Waiting – answer by ${dateTime(txn.confirmation.expires_at)}`}</dd>
          </>}
        </dl>
        {txn.final_reason && txn.status !== 'COMPLETED' && txn.final_reason !== txn.risk_explanation && (
          <div className={`notice ${txn.status === 'UNDER_REVIEW' ? 'notice-warn' : 'notice-danger'}`}><strong>{txn.final_reason}</strong></div>
        )}
        {txn.risk_explanation && txn.status !== 'COMPLETED' && (
          <div className={`notice ${txn.status === 'BLOCKED' ? 'notice-danger' : 'notice-warn'}`}>{txn.risk_explanation}</div>
        )}
        {txn.rules?.length > 0 && (
          <div>
            <h3>Triggered fraud rules</h3>
            <ul className="small" style={{ paddingLeft: 18, margin: '6px 0 0' }}>
              {txn.rules.map((r) => <li key={r.code}><strong>{r.code}{r.name ? ` ${r.name}` : ''}</strong> – {r.reason}</li>)}
            </ul>
          </div>
        )}
        {awaitingOtp && <OtpEntry txn={txn} onDone={() => { onChange?.(); onClose(); }} />}
        {canAct && <p className="small muted">Suspicious transaction detected. If you made this payment, answer YES and verify the OTP sent to your registered phone and e-mail. If you didn’t, answer NO: it is stopped immediately, no money moves, and the receiver account is blocked.</p>}
        {txn.status === 'UNDER_REVIEW' && txn.review_stage === 'AWAITING_ANALYST' && (
          <div className="notice notice-warn">⏳ Waiting for a fraud analyst’s decision. Not debited.</div>
        )}
        {txn.decline_reason && txn.decline_reason !== txn.risk_explanation && txn.decline_reason !== txn.final_reason && <div className="notice notice-danger">{txn.decline_reason}</div>}
      </div>
    </Modal>
  );
}
