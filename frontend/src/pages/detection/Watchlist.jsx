import { useState } from 'react';
import { del, errorMessage, patch, post } from '../../api/client';
import { useToast } from '../../components/Toast';
import { Empty, ErrorNote, Field, Loading, PageHead, Toggle } from '../../components/ui';
import { useApi } from '../../hooks';
import { dateTime } from '../../utils/format';

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
          <p className="muted small mt-16">AUTO entries are added by the engine when it blocks an account-takeover (attacker’s untrusted device and public IP).</p>
        </div>
      </div>
    </>
  );
}
