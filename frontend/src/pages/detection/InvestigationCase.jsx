import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { errorMessage, post } from '../../api/client';
import { useToast } from '../../components/Toast';
import { ErrorNote, Field, Loading, Modal, OutcomeBadge, StatusBadge, scoreColor } from '../../components/ui';
import { useApi } from '../../hooks';
import { dateTime, money, METHOD_LABEL } from '../../utils/format';
import { actionLabel } from './InvestigationQueue';

const DECISION = {
  PERMANENT_BLOCK: { title: 'Permanently block this account?', button: 'Permanently block', tone: 'btn-danger',
    text: 'The account will be PERMANENTLY_BLOCKED: no payments to or from it, ever. Other open cases on it are closed. The customer is notified. This decision cannot be changed later.' },
  APPROVE: { title: 'Approve this account and restore access?', button: 'Approve & restore access', tone: 'btn-success',
    text: 'The temporary restriction is removed and the account becomes ACTIVE again (unless another case on it is still open). The stopped payment stays stopped. The customer is notified.' },
};

/** One investigation: everything needed to understand the flag, and the final decision. */
export default function InvestigationCase() {
  const { id } = useParams();
  const toast = useToast();
  const { data: c, error, reload, setData } = useApi(`/detection/investigations/${id}`);
  const [deciding, setDeciding] = useState(null);
  const [reason, setReason] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);

  if (!c) return error ? <><BackLink /><ErrorNote error={error} /></> : <Loading />;
  const txn = c.transaction_detail;

  const start = async () => {
    setBusy(true);
    try {
      const res = await post(`/detection/investigations/${c.id}/start`);
      setData(res.data);
      toast(res.message, 'info');
    } catch (err) {
      toast(errorMessage(err), 'error');
      reload(true);
    } finally {
      setBusy(false);
    }
  };

  const decide = async () => {
    setBusy(true);
    try {
      const res = await post(`/detection/investigations/${c.id}/decision`, { decision: deciding, reason: reason.trim(), confirm: confirmed });
      setData(res.data);
      setDeciding(null);
      setReason('');
      setConfirmed(false);
      toast(res.message, 'success', 'Decision recorded');
    } catch (err) {
      toast(errorMessage(err), 'error');
      reload(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <BackLink />
      <div className="case-header card card-pad">
        <div>
          <div className="row wrap" style={{ gap: 10 }}>
            <h1 className="mono" style={{ margin: 0 }}>{c.case_ref}</h1>
            <StatusBadge status={c.status} />
            <span className="badge b-slate">{c.case_type_label}</span>
          </div>
          <p className="muted small mt-8">Detected {dateTime(c.opened_at)}{c.assigned_to && ` · investigator ${c.assigned_to}`}</p>
        </div>
        <RiskGauge score={c.risk_score} />
      </div>

      <div className="grid grid-2 mt-16">
        <div className="card card-pad">
          <h3>💳 Transaction</h3>
          {txn ? (
            <dl className="kv mt-8">
              <dt>Transaction ID</dt><dd className="mono">{txn.txn_ref}</dd>
              <dt>Amount</dt><dd><strong>{money(txn.amount)}</strong></dd>
              <dt>Type</dt><dd>{METHOD_LABEL[txn.payment_method]}{txn.remarks && ` · “${txn.remarks}”`}</dd>
              <dt>Date & time</dt><dd>{dateTime(txn.txn_time)}</dd>
              <dt>From → to</dt><dd>{txn.sender.name} ({txn.sender.upi_id}) → {txn.receiver.name} ({txn.receiver.upi_id})</dd>
              <dt>Device · IP</dt><dd>{txn.device ? `${txn.device.device_name} (${txn.device.is_trusted ? 'trusted' : 'untrusted'})` : '—'} · <span className="mono">{txn.ip_address || '—'}</span></dd>
              <dt>Location</dt><dd>{txn.city || '—'}</dd>
              <dt>Outcome</dt><dd><OutcomeBadge label={txn.outcome_label} /> <span className="muted small">{txn.money_moved ? 'money moved' : 'no money moved'}</span></dd>
            </dl>
          ) : <p className="muted small mt-8">The transaction record was removed (Frauder reset). Snapshot: {c.transaction.txn_ref} · {money(c.transaction.amount)}</p>}
        </div>
        <div className="card card-pad">
          <h3>👤 Customer & account</h3>
          <dl className="kv mt-8">
            <dt>Customer</dt><dd><strong>{c.customer_detail.full_name}</strong> · {c.customer_detail.email}</dd>
            <dt>Phone</dt><dd>{c.customer_detail.phone || '—'}</dd>
            <dt>Home city</dt><dd>{c.customer_detail.home_city || '—'}</dd>
            <dt>Account</dt><dd className="mono">{c.account_detail.masked_number} · {c.account_detail.ifsc}</dd>
            <dt>UPI ID</dt><dd className="mono">{c.account_detail.upi_id}</dd>
            <dt>Balance</dt><dd>{money(c.account_detail.balance)}</dd>
            <dt>Account status</dt><dd><StatusBadge status={c.account_detail.status} /> <span className="muted small">was {c.account_status_at_open} when detected</span></dd>
            <dt>Opened</dt><dd>{dateTime(c.account_detail.opened_at)}</dd>
          </dl>
        </div>
      </div>

      <div className="grid grid-2 mt-16">
        <div className="card">
          <div className="card-head"><h3>📜 Case history</h3><span className="small muted">Append-only</span></div>
          <div className="timeline card-body">
            {c.actions.map((a) => (
              <div className="timeline-item" key={a.id}>
                <div className="row small"><strong>{actionLabel(a.action)}</strong><span className="muted">{dateTime(a.created_at)} · {a.detective}</span></div>
                <div className="small muted">Account {a.previous_account_status ? `${a.previous_account_status} → ` : ''}{a.new_account_status} · case {a.new_case_status}</div>
                {a.reason && <div className="small">“{a.reason}”</div>}
              </div>
            ))}
          </div>
          {c.other_cases.length > 0 && (
            <div className="card-body small">Other cases on this account: {c.other_cases.map((o) => (
              <Link key={o.id} to={`/detection/investigations/${o.id}`} style={{ marginRight: 8 }}>{o.case_ref} ({o.status.toLowerCase().replaceAll('_', ' ')})</Link>
            ))}</div>
          )}
        </div>

        <div className="card card-pad decision-panel">
          <h3>⚖️ Detective decision</h3>
          {c.is_open ? (
            <>
              <p className="small muted mt-8">The account stays restricted until a decision is recorded.</p>
              {c.status === 'TEMPORARILY_BLOCKED' && (
                <button type="button" className="btn btn-ghost mt-16" disabled={busy} onClick={start}>🔍 Start investigation</button>
              )}
              <div className="decision-actions mt-16">
                <button type="button" className="btn btn-success" disabled={busy} onClick={() => setDeciding('APPROVE')}>✓ Approve account</button>
                <button type="button" className="btn btn-danger" disabled={busy} onClick={() => setDeciding('PERMANENT_BLOCK')}>⛔ Permanently block</button>
              </div>
            </>
          ) : (
            <div className="mt-8">
              <StatusBadge status={c.status} />
              <dl className="kv mt-8">
                <dt>Decision</dt><dd>{c.decision ? c.decision.replace('_', ' ').toLowerCase() : 'closed without a decision'}</dd>
                <dt>By</dt><dd>{c.decided_by || 'System'}</dd>
                <dt>When</dt><dd>{dateTime(c.decided_at)}</dd>
                <dt>Reason</dt><dd>{c.decision_reason}</dd>
              </dl>
              <p className="small muted mt-8">Decisions are final and recorded in the audit trail.</p>
            </div>
          )}
        </div>
      </div>

      {deciding && (
        <Modal title={DECISION[deciding].title} onClose={() => !busy && setDeciding(null)} footer={<>
          <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => setDeciding(null)}>Cancel</button>
          <button type="button" className={`btn ${DECISION[deciding].tone}`} disabled={busy || reason.trim().length < 10 || !confirmed} onClick={decide}>
            {busy ? 'Saving…' : DECISION[deciding].button}
          </button>
        </>}>
          <p className="small">{DECISION[deciding].text}</p>
          <p className="small mt-8"><strong>{c.customer.name}</strong> · {c.account.masked_number} · case {c.case_ref}</p>
          <Field label="Reason (required, at least 10 characters)" hint={`${reason.trim().length}/500`}>
            <textarea className="input" rows={3} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)}
                      placeholder={deciding === 'APPROVE' ? 'e.g. Customer confirmed the payment by phone and KYC matches.' : 'e.g. Confirmed account takeover: new device, stolen login and mule receiver.'} />
          </Field>
          <label className="row small mt-8">
            <input type="checkbox" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} />
            I have reviewed this case and confirm this decision.
          </label>
        </Modal>
      )}
    </>
  );
}

function BackLink() {
  return <Link to="/detection/investigations" className="back-link">← Back to the investigation queue</Link>;
}

function RiskGauge({ score }) {
  const value = score ?? 0;
  return (
    <div className="risk-gauge" style={{ '--p': value, '--c': scoreColor(score) }} aria-label={`Overall risk score ${value} of 100`}>
      <div><strong>{value}</strong><span>/100</span></div>
      <small>{value >= 70 ? 'High risk' : value >= 40 ? 'Medium risk' : 'Low risk'}</small>
    </div>
  );
}
