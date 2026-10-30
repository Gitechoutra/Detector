import { dateTime, money, METHOD_LABEL } from '../utils/format';
import { Modal, OutcomeBadge, RiskScore, StatusBadge } from './ui';

export default function TxnDetailModal({ txn, viewer = 'sender', onClose, onVerify, onReport }) {
  const counterpart = viewer === 'sender' ? txn.receiver : txn.sender;
  const canAct = viewer === 'sender' && txn.status === 'UNDER_REVIEW' && txn.review_stage === 'AWAITING_CUSTOMER';
  const saidYes = txn.confirmation?.response === 'YES';
  return (
    <Modal title={`Payment ${txn.txn_ref}`} onClose={onClose} footer={canAct ? (saidYes
      ? <button className="btn btn-primary" onClick={onVerify}>Enter OTP to finish</button>
      : <>
        <button className="btn btn-danger" onClick={onReport}>✕ NO, NOT ME</button>
        <button className="btn btn-success" onClick={onVerify}>✓ YES, IT WAS ME</button>
      </>) : null}>
      <div className="stack">
        <div className="row-between">
          <div style={{ fontSize: 26, fontWeight: 700 }}>{money(txn.amount)}</div>
          <div className="row">{txn.confirmation && viewer === 'sender' && <OutcomeBadge label={txn.outcome_label} />}<StatusBadge status={txn.status} /></div>
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
            <dd>{txn.confirmation.response ? `${txn.confirmation.response === 'YES' ? 'YES, it was me' : 'NO, not me'} · ${dateTime(txn.confirmation.responded_at)}`
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
            <h3>Checks that fired</h3>
            <ul className="small" style={{ paddingLeft: 18, margin: '6px 0 0' }}>
              {txn.rules.map((r) => <li key={r.code}><strong>{r.code}</strong> – {r.reason}</li>)}
            </ul>
          </div>
        )}
        {canAct && <p className="small muted">If you made this payment, answer YES and verify it with an OTP and your password – every fraud rule is checked again before any money moves. If you didn’t, answer NO and it is blocked immediately.</p>}
        {txn.status === 'UNDER_REVIEW' && txn.review_stage === 'AWAITING_ANALYST' && (
          <div className="notice notice-warn">⏳ Verified and waiting for a fraud analyst’s decision. Not debited.</div>
        )}
        {txn.decline_reason && txn.decline_reason !== txn.risk_explanation && txn.decline_reason !== txn.final_reason && <div className="notice notice-danger">{txn.decline_reason}</div>}
      </div>
    </Modal>
  );
}
