import { useState } from 'react';
import { del, errorMessage, patch, post } from '../../api/client';
import { useToast } from '../../components/Toast';
import { Empty, ErrorNote, Field, Loading, Modal, PageHead, RiskScore, RuleChips, Toggle } from '../../components/ui';
import { useApi } from '../../hooks';
import { dateTime, money } from '../../utils/format';

const TYPES = [['UPI', 'UPI ID'], ['ACCOUNT', 'Account number'], ['DEVICE', 'Device fingerprint'], ['IP', 'IP address']];

export default function Watchlist() {
  const toast = useToast();
  const [type, setType] = useState('');
  const { data, error, reload } = useApi('/detection/watchlist', { entity_type: type || undefined });
  const [form, setForm] = useState({ entity_type: 'UPI', entity_value: '', reason: '' });
  const [busy, setBusy] = useState(false);

  const add = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      await post('/detection/watchlist', form);
      toast('Added to the watchlist. R6 now fires for it.', 'success');
      setForm({ ...form, entity_value: '', reason: '' });
      reload(true);
    } catch (err) {
      toast(errorMessage(err), 'error');
    } finally {
      setBusy(false);
    }
  };

  const run = async (fn, msg) => {
    try {
      await fn();
      toast(msg, 'success');
      reload(true);
    } catch (e) {
      toast(errorMessage(e), 'error');
    }
  };

  return (
    <>
      <PageHead title="Watchlist" subtitle="Blacklisted accounts, UPI IDs, devices and IP addresses. Any match fires rule R6." />
      <div className="grid grid-main">
        <div className="card">
          <div className="filters">
            <select className="input input-sm" value={type} onChange={(e) => setType(e.target.value)}>
              <option value="">All types</option>
              {TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <ErrorNote error={error} />
          {!data ? <Loading /> : !data.length ? <Empty title="Watchlist is empty" /> : (
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>Type</th><th>Value</th><th>Reason</th><th>Source</th><th>Added</th><th>Active</th><th /></tr></thead>
                <tbody>
                  {data.map((w) => (
                    <tr key={w.id}>
                      <td><span className="badge b-purple">{w.entity_type}</span></td>
                      <td className="mono small" style={{ wordBreak: 'break-all' }}>{w.entity_value}</td>
                      <td className="small">{w.reason}</td>
                      <td><span className={`badge ${w.source === 'AUTO' ? 'b-red' : w.source === 'SEED' ? 'b-slate' : 'b-blue'}`}>{w.source}</span></td>
                      <td className="small nowrap">{dateTime(w.created_at)}</td>
                      <td><Toggle checked={w.is_active} label="Active" onChange={(v) => run(() => patch(`/detection/watchlist/${w.id}`, { is_active: v }), v ? 'Activated.' : 'Deactivated.')} /></td>
                      <td>{w.source !== 'SEED' && <button className="btn btn-danger-soft btn-sm" onClick={() => run(() => del(`/detection/watchlist/${w.id}`), 'Removed.')}>Remove</button>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        <div className="card card-pad">
          <h2>Add entry</h2>
          <form className="form-grid mt-16" onSubmit={add}>
            <Field label="Type">
              <select className="input" value={form.entity_type} onChange={(e) => setForm({ ...form, entity_type: e.target.value })}>
                {TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </Field>
            <Field label="Value"><input className="input mono" value={form.entity_value} onChange={(e) => setForm({ ...form, entity_value: e.target.value })} required /></Field>
            <Field label="Reason"><input className="input" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} required placeholder="e.g. Reported mule account" /></Field>
            <button className="btn btn-primary" disabled={busy}>Add to watchlist</button>
          </form>
          <p className="muted small mt-16">AUTO entries are added by the engine: the attacker’s untrusted device and public IP after an account-takeover block, and the receiver’s UPI ID and account number when an account owner answers NO.</p>
        </div>
      </div>
      <BlockedReceivers onChange={() => reload(true)} />
    </>
  );
}

/** Receiver accounts blocked after an owner's NO. The block lives in the database
 *  (account status BLOCKED); lifting it needs a reason and is audited. */
function BlockedReceivers({ onChange }) {
  const toast = useToast();
  const { data, error, reload } = useApi('/detection/receiver-blocks');
  const [lifting, setLifting] = useState(null);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  const lift = async () => {
    if (reason.trim().length < 5) {
      toast('Give a reason of at least 5 characters.', 'error');
      return;
    }
    setBusy(true);
    try {
      const res = await post(`/detection/receiver-blocks/${lifting.id}/lift`, { reason: reason.trim() });
      toast(res.message, 'success');
      setLifting(null);
      setReason('');
      reload(true);
      onChange?.();
    } catch (err) {
      toast(errorMessage(err), 'error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card mt-16">
      <div className="card-head">
        <h2>⛔ Blocked receiver accounts</h2>
        <span className="small muted">Blocked when the payer’s account owner answered NO</span>
      </div>
      <ErrorNote error={error} />
      {!data ? <Loading /> : data.length === 0 ? <Empty icon="✅" title="No blocked receivers" /> : (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Blocked at</th><th>Receiver</th><th>Transaction</th><th>Score</th><th>Risk factors</th><th>Reason</th><th>Status</th><th /></tr></thead>
            <tbody>
              {data.map((b) => (
                <tr key={b.id}>
                  <td className="small nowrap">{dateTime(b.blocked_at)}</td>
                  <td className="small"><strong>{b.receiver.name}</strong><div className="muted mono">{b.receiver.upi_id}</div></td>
                  <td className="small"><span className="mono">{b.transaction?.txn_ref}</span><div className="muted">{money(b.transaction?.amount)} from {b.transaction?.sender}</div></td>
                  <td><RiskScore score={b.risk_score} /></td>
                  <td><RuleChips rules={b.risk_factors} /></td>
                  <td className="small">{b.reason}</td>
                  <td>{b.status === 'ACTIVE' ? <span className="badge b-red">Blocked</span>
                    : <span className="badge b-slate" title={`${b.lifted_by}: ${b.lift_reason}`}>Lifted {dateTime(b.lifted_at)}</span>}</td>
                  <td>{b.status === 'ACTIVE' && <button className="btn btn-ghost btn-sm" onClick={() => setLifting(b)}>Lift block</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {lifting && (
        <Modal title={`Lift the block on ${lifting.receiver.name}?`} onClose={() => setLifting(null)} footer={<>
          <button className="btn btn-ghost" onClick={() => setLifting(null)}>Cancel</button>
          <button className="btn btn-primary" disabled={busy || reason.trim().length < 5} onClick={lift}>Lift block</button>
        </>}>
          <p className="small">The account can receive money again once no other block on it is active, and its watchlist flags are deactivated. This is recorded in the audit trail.</p>
          <Field label="Reason (required)">
            <input className="input" value={reason} maxLength={255} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Merchant verified by phone" />
          </Field>
        </Modal>
      )}
    </div>
  );
}
