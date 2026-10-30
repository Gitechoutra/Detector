import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { errorMessage, post } from '../../api/client';
import { ConfirmationPanel, SimulatedDetails } from '../../components/DetectionResult';
import { useToast } from '../../components/Toast';
import { Empty, ErrorNote, Field, Loading, Modal, OutcomeBadge, RiskScore, RuleChips, StatusBadge } from '../../components/ui';
import { useApi } from '../../hooks';
import { dateTime, money, METHOD_LABEL } from '../../utils/format';

const TYPE_LABEL = { INITIAL: 'Real-time decision', RE_EVALUATION: 'Re-evaluation after customer verification', ANALYST: 'Re-evaluation before analyst decision' };

export default function Investigation() {
  const { id } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const { data: t, error, reload } = useApi(`/detection/transactions/${id}`, null, { interval: 5000 });
  const [decision, setDecision] = useState(null);
  const [notes, setNotes] = useState('');
  const [busy, setBusy] = useState(false);
  const [watch, setWatch] = useState(null);

  if (!t) return error ? <ErrorNote error={error} /> : <Loading />;

  const decide = async () => {
    setBusy(true);
    try {
      const res = await post(`/detection/transactions/${t.id}/decision`, { action: decision, notes });
      toast(res.message, 'success');
      setDecision(null);
      setNotes('');
    } catch (e) {
      toast(errorMessage(e), 'error');
      setDecision(null);
    } finally {
      setBusy(false);
      reload(true);
    }
  };

  const addWatch = async () => {
    setBusy(true);
    try {
      await post('/detection/watchlist', watch);
      toast(`${watch.entity_value} added to the watchlist.`, 'success');
      setWatch(null);
      reload(true);
    } catch (e) {
      toast(errorMessage(e), 'error');
    } finally {
      setBusy(false);
    }
  };

  const watched = new Set(t.watchlist_matches.filter((w) => w.is_active).map((w) => w.entity_value));
  const watchOptions = [
    ['UPI', t.receiver_profile.upi_id, 'Receiver UPI'],
    ['ACCOUNT', t.receiver_profile.account_number, 'Receiver account'],
    ['DEVICE', t.device_fingerprint, 'Sender device'],
    ['IP', t.ip_address, 'Sender IP'],
  ].filter(([, v]) => v);

  return (
    <>
      <div className="row-between wrap" style={{ marginBottom: 16 }}>
        <div>
          <button className="link-btn small" onClick={() => navigate(-1)}>← Back</button>
          <h1 className="mt-8">Investigation · <span className="mono">{t.txn_ref}</span></h1>
          <p className="muted">{dateTime(t.txn_time)} · {METHOD_LABEL[t.payment_method]} · {t.city || 'unknown city'} {t.is_simulated && <span className="badge b-purple">Simulated: {t.scenario_code}</span>}</p>
        </div>
        {t.status === 'UNDER_REVIEW' && (
          <div className="row">
            <button className="btn btn-danger" onClick={() => setDecision('REJECT')}>✕ Reject</button>
            <button className="btn btn-success" onClick={() => setDecision('APPROVE')}>✓ Approve & release</button>
          </div>
        )}
      </div>

      <div className="grid grid-4">
        <div className="card card-pad"><div className="stat-label">Amount</div><div className="stat-value">{money(t.amount)}</div></div>
        <div className="card card-pad"><div className="stat-label">Risk score</div><div className="mt-8"><RiskScore score={t.risk_score} /></div></div>
        <div className="card card-pad"><div className="stat-label">Status</div><div className="mt-8"><OutcomeBadge label={t.outcome_label} /></div>
          {t.review_stage && <div className="small muted mt-8">{t.review_stage === 'AWAITING_CUSTOMER' ? 'Waiting for the account owner’s answer' : 'Waiting for analyst decision'}</div>}</div>
        <div className="card card-pad"><div className="stat-label">Decision latency</div><div className="stat-value">{t.latency_ms != null ? `${t.latency_ms} ms` : '—'}</div></div>
      </div>
      {t.final_reason && t.final_reason !== t.risk_explanation && <div className={`notice mt-16 ${t.status === 'COMPLETED' ? 'notice-success' : t.status === 'UNDER_REVIEW' ? 'notice-warn' : 'notice-danger'}`}>⚖️ <strong>{t.final_reason}</strong></div>}
      {t.risk_explanation && <div className={`notice mt-16 ${t.decision === 'BLOCKED' ? 'notice-danger' : 'notice-warn'}`}>🧾 {t.risk_explanation}</div>}
      {t.decline_reason && t.decline_reason !== t.risk_explanation && t.decline_reason !== t.final_reason && <div className="notice notice-danger mt-16">{t.decline_reason}</div>}
      {(t.confirmation || t.simulated_details) && (
        <div className="grid grid-2 mt-16">
          <ConfirmationPanel txn={t} />
          <SimulatedDetails details={t.simulated_details} />
        </div>
      )}
      {t.is_simulated && <div className="small muted mt-8">Money {t.money_moved ? 'was transferred' : 'was not moved'} – this payment used the real demo account balances.</div>}

      <div className="grid grid-main mt-16">
        <div className="stack">
          <div className="card">
            <div className="card-head"><h2>Why – rule evidence</h2><span className="muted small">{t.assessments.length} assessment(s)</span></div>
            <div className="card-body stack">
              {t.assessments.map((a) => (
                <div key={a.id}>
                  <div className="row-between wrap">
                    <strong>{TYPE_LABEL[a.assessment_type]}</strong>
                    <div className="row"><RiskScore score={a.risk_score} /><StatusBadge status={a.decision} /></div>
                  </div>
                  <div className="muted small">{dateTime(a.created_at)} · {a.rules_triggered} of {a.rules_evaluated} rules fired · {a.latency_ms} ms{a.notes ? ` · ${a.notes}` : ''}</div>
                  <div className="mt-8">
                    {a.hits.length === 0 && <p className="small muted">No rules fired.</p>}
                    {a.hits.map((h) => (
                      <div className="rule-hit" key={h.code}>
                        <span className="rule-chip">{h.code}</span>
                        <div style={{ flex: 1 }}>
                          <strong className="small">{h.name}</strong>
                          <div className="small">{h.reason}</div>
                          {h.evidence && <div className="muted small mono mt-8" style={{ wordBreak: 'break-word' }}>{JSON.stringify(h.evidence)}</div>}
                        </div>
                        <span className="w">+{h.weight}</span>
                      </div>
                    ))}
                    {a.mitigations.map((m) => (
                      <div className="rule-hit" key={`m-${m.code}`} style={{ background: 'var(--success-bg)' }}>
                        <span className="rule-chip">{m.code}</span>
                        <div style={{ flex: 1 }} className="small"><strong>Mitigated</strong> – {m.reason}<div className="muted">{m.mitigated_by}</div></div>
                        <span className="small" style={{ color: 'var(--success)', fontWeight: 700 }}>+0</span>
                      </div>
                    ))}
                  </div>
                  <div className="small muted mt-8">Score = min(100, {a.hits.map((h) => h.weight).join(' + ') || '0'}) = <strong>{a.risk_score}</strong></div>
                  <div className="divider" />
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <div className="card-head"><h2>Sender’s recent transactions</h2></div>
            {t.sender_history.length === 0 ? <Empty title="No other transactions" /> : (
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>When</th><th>To</th><th>Amount</th><th>City</th><th>Score</th><th>Status</th></tr></thead>
                  <tbody>
                    {t.sender_history.map((h) => (
                      <tr key={h.id} className="clickable" onClick={() => navigate(`/detection/transactions/${h.id}`)}>
                        <td className="small nowrap">{dateTime(h.txn_time)}</td><td className="small">{h.receiver.name}</td>
                        <td className="nowrap">{money(h.amount)}</td><td className="small">{h.city}</td>
                        <td><RiskScore score={h.risk_score} /></td><td><StatusBadge status={h.status} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="card">
            <div className="card-head"><h2>Logins & security events (24 h before)</h2></div>
            <div className="table-wrap">
              <table className="table">
                <thead><tr><th>When</th><th>Event</th><th>City</th><th>IP</th></tr></thead>
                <tbody>
                  {t.logins.map((l, i) => (
                    <tr key={`l${i}`}>
                      <td className="small nowrap">{dateTime(l.created_at)}</td>
                      <td>{l.success ? <span className="badge b-green">Login ok</span> : <span className="badge b-red">Login failed</span>} {l.is_new_device && <span className="badge b-amber">new device</span>}</td>
                      <td className="small">{l.city}</td><td className="mono small">{l.ip_address}</td>
                    </tr>
                  ))}
                  {t.security_events.filter((e) => !e.event_type.startsWith('LOGIN')).map((e) => (
                    <tr key={`e${e.id}`}>
                      <td className="small nowrap">{dateTime(e.created_at)}</td>
                      <td><StatusBadge status={e.severity} /> <span className="small">{e.event_type.replaceAll('_', ' ')}</span><div className="muted small">{e.description}</div></td>
                      <td className="small">{e.city}</td><td className="mono small">{e.ip_address}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!t.logins.length && !t.security_events.length && <Empty title="No login activity recorded" />}
            </div>
          </div>
        </div>

        <div className="stack">
          <div className="card card-pad">
            <h3>Sender</h3>
            <dl className="kv mt-8">
              <dt>Name</dt><dd>{t.sender_profile.full_name}</dd>
              <dt>Email</dt><dd>{t.sender_profile.email}</dd>
              <dt>Account</dt><dd className="mono">{t.sender_profile.account_number}</dd>
              <dt>Home city</dt><dd>{t.sender_profile.home_city}</dd>
              <dt>Balance</dt><dd>{money(t.sender_profile.balance)}</dd>
              <dt>Status</dt><dd><StatusBadge status={t.sender_profile.status === 'ACTIVE' ? 'RESOLVED' : 'LOCKED'} label={t.sender_profile.status} /></dd>
            </dl>
          </div>
          <div className="card card-pad">
            <h3>Receiver</h3>
            <dl className="kv mt-8">
              <dt>Name</dt><dd>{t.receiver_profile.name}</dd>
              <dt>UPI</dt><dd className="mono">{t.receiver_profile.upi_id}</dd>
              <dt>Account</dt><dd className="mono">{t.receiver_profile.account_number}</dd>
            </dl>
          </div>
          <div className="card card-pad">
            <h3>Device & network</h3>
            <dl className="kv mt-8">
              <dt>Device</dt><dd>{t.device?.device_name || 'Unknown'} {t.device && (t.device.is_trusted ? <span className="badge b-green">trusted</span> : <span className="badge b-amber">untrusted</span>)}</dd>
              <dt>First seen</dt><dd>{dateTime(t.device?.first_seen_at)}</dd>
              <dt>IP address</dt><dd className="mono">{t.ip_address}</dd>
            </dl>
          </div>
          <div className="card card-pad">
            <h3>Watchlist</h3>
            {t.watchlist_matches.length > 0 && (
              <ul className="small" style={{ paddingLeft: 18 }}>
                {t.watchlist_matches.map((w) => <li key={w.id}><strong>{w.entity_type}</strong> {w.entity_value} {!w.is_active && '(inactive)'} – {w.reason}</li>)}
              </ul>
            )}
            <div className="stack mt-8" style={{ gap: 8 }}>
              {watchOptions.map(([type, value, label]) => (
                <div key={type} className="row-between small">
                  <span><span className="muted">{label}:</span> <span className="mono">{value.length > 22 ? value.slice(0, 20) + '…' : value}</span></span>
                  {watched.has(value) ? <span className="badge b-red">listed</span>
                    : <button className="btn btn-ghost btn-sm" onClick={() => setWatch({ entity_type: type, entity_value: value, reason: `Added during investigation of ${t.txn_ref}` })}>+ Watchlist</button>}
                </div>
              ))}
            </div>
          </div>
          <div className="card card-pad">
            <h3>Alerts</h3>
            {t.alerts.length === 0 ? <p className="muted small mt-8">No alert (approved transaction).</p> : t.alerts.map((a) => (
              <div key={a.id} className="mt-8">
                <div className="row"><StatusBadge status={a.severity} /><StatusBadge status={a.status} />{a.resolution && <StatusBadge status={a.resolution} />}</div>
                <div className="small mt-8">{a.title}</div>
                {a.analyst_notes && <pre className="small muted" style={{ whiteSpace: 'pre-wrap', margin: '6px 0 0', fontFamily: 'inherit' }}>{a.analyst_notes}</pre>}
              </div>
            ))}
            <Link to="/detection/alerts" className="small">Open alert queue →</Link>
          </div>
        </div>
      </div>

      {decision && (
        <Modal title={decision === 'APPROVE' ? 'Approve and release payment?' : 'Reject payment?'} onClose={() => setDecision(null)} footer={<>
          <button className="btn btn-ghost" onClick={() => setDecision(null)}>Cancel</button>
          <button className={`btn ${decision === 'APPROVE' ? 'btn-success' : 'btn-danger'}`} disabled={busy} onClick={decide}>{busy ? 'Working…' : decision === 'APPROVE' ? 'Approve' : 'Reject'}</button>
        </>}>
          <p className="small">{decision === 'APPROVE'
            ? 'All rules are re-evaluated first. If the payment now scores in the Blocked band it is blocked instead and cannot be approved. Otherwise money moves to the receiver and the alert is closed as a false positive.'
            : 'The payment is declined (no money moves) and its alert is closed as confirmed fraud.'}</p>
          <Field label="Analyst notes (recorded in the audit trail)">
            <textarea className="input" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="e.g. Called customer, confirmed genuine" />
          </Field>
        </Modal>
      )}
      {watch && (
        <Modal title="Add to watchlist" onClose={() => setWatch(null)} footer={<>
          <button className="btn btn-ghost" onClick={() => setWatch(null)}>Cancel</button>
          <button className="btn btn-primary" disabled={busy || !watch.reason} onClick={addWatch}>Add</button>
        </>}>
          <p className="small"><strong>{watch.entity_type}</strong> <span className="mono">{watch.entity_value}</span></p>
          <p className="muted small mt-8">Future transactions involving it will fire R6 (weight 50).</p>
          <div className="mt-16"><Field label="Reason"><input className="input" value={watch.reason} onChange={(e) => setWatch({ ...watch, reason: e.target.value })} /></Field></div>
        </Modal>
      )}
    </>
  );
}
