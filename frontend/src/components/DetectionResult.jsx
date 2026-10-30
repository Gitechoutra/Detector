import { money, timeOnly } from '../utils/format';
import { OutcomeBadge, RiskScore } from './ui';

const RULE_STATUS = {
  TRIGGERED: ['Triggered', 'b-red'],
  NOT_TRIGGERED: ['Not triggered', 'b-slate'],
  MITIGATED: ['Cleared by verification', 'b-green'],
  DISABLED: ['Disabled', 'b-slate'],
};
const TIMELINE_ICON = { activity: '🕵️', submit: '📤', engine: '⚙️', decision: '⚖️', confirm: '🙋', alert: '🚨', money: '💰' };
const ANSWER = { YES: ['YES, IT WAS ME', 'b-green'], NO: ['NO, NOT ME', 'b-red'] };

/** What the owner was asked and how they answered. */
export function ConfirmationPanel({ txn }) {
  const c = txn.confirmation;
  if (!c) return null;
  const owner = (txn.sender_name || txn.sender?.name || 'The owner').split(' ')[0];
  return (
    <div className="card card-pad">
      <div className="row-between wrap">
        <h3>🙋 {owner}’s confirmation</h3>
        {c.response ? <span className={`badge ${ANSWER[c.response][1]}`}>{ANSWER[c.response][0]}</span>
          : c.status === 'EXPIRED' ? <span className="badge b-slate">No answer – expired</span>
            : c.status === 'CLOSED' ? <span className="badge b-slate">Closed by analyst</span>
              : <span className="badge b-amber badge-dot">Waiting for {owner}…</span>}
      </div>
      <p className="small muted mt-8">
        Asked: “Was this {money(txn.amount)} transaction to {txn.receiver_name || txn.receiver?.name} initiated by you?”
        {c.responded_at ? ` · answered at ${timeOnly(c.responded_at)}` : c.expires_at ? ` · expires at ${timeOnly(c.expires_at)}` : ''}
      </p>
    </div>
  );
}

/** The attacker values typed in the Frauder console – SIMULATED, never verified. */
export function SimulatedDetails({ details }) {
  if (!details) return null;
  const device = details.use_registered_device ? 'Victim’s registered device (remote-access scam)'
    : `${details.device_type} · ID ${details.device_id}`;
  return (
    <div className="sim-panel">
      <div className="row-between wrap">
        <h3>Attacker details entered by hand</h3>
        <span className="badge b-purple">SIMULATED – not verified</span>
      </div>
      <dl className="kv mt-8">
        <dt>City</dt><dd>{details.city}</dd>
        {details.target_location && <><dt>Location</dt><dd>{details.target_location}</dd></>}
        <dt>Device</dt><dd>{device}</dd>
        <dt>IP address</dt><dd className="mono">{details.ip_address}</dd>
        {details.scenario_name && <><dt>Scenario</dt><dd>{details.scenario_name}</dd></>}
        {details.demo_time && <><dt>Demo clock</dt><dd>{details.demo_time}</dd></>}
      </dl>
    </div>
  );
}
const DECISION_NOTICE = { COMPLETED: 'notice-success', UNDER_REVIEW: 'notice-warn', BLOCKED: 'notice-danger' };

/** The full, backend-generated explanation of one fraud decision. */
export default function DetectionResult({ result }) {
  const fired = result.rule_trace.filter((t) => t.status === 'TRIGGERED');
  const formula = fired.length ? fired.map((t) => t.weight).join(' + ') : '0';
  return (
    <div className="stack">
      <div className={`notice ${DECISION_NOTICE[result.status] || 'notice-info'}`} style={{ display: 'block', padding: 16 }}>
        <div className="row-between wrap">
          <strong style={{ fontSize: 16 }}>
            {result.status === 'COMPLETED' ? '✅ Successful – money transferred'
              : result.status === 'UNDER_REVIEW' ? (result.review_stage === 'AWAITING_CUSTOMER'
                ? `⏸ Waiting for ${result.sender_name.split(' ')[0]}’s answer – no money moved`
                : '⏸ With the fraud team – no money moved')
                : result.status === 'BLOCKED' ? '⛔ Blocked – no money moved' : result.status}
          </strong>
          <OutcomeBadge label={result.outcome_label} />
        </div>
        {result.final_reason && result.final_reason !== result.risk_explanation && <p className="mt-8"><strong>{result.final_reason}</strong></p>}
        {result.risk_explanation && <p className="mt-8">{result.risk_explanation}</p>}
        {result.replayed && <p className="small mt-8">Duplicate submission – this is the original attempt.</p>}
      </div>

      <dl className="kv">
        <dt>Transaction</dt><dd><span className="mono">{result.txn_ref}</span> · {money(result.amount)}</dd>
        <dt>Sender → Receiver</dt><dd>{result.sender_name} → {result.receiver_name}</dd>
        <dt>Device</dt><dd>{result.device ? `${result.device.device_name} (${result.device.is_trusted ? 'trusted' : 'unknown'})` : '—'}</dd>
        <dt>Location · time</dt><dd>{result.city} · {timeOnly(result.txn_time)}</dd>
        <dt>IP address</dt><dd className="mono">{result.ip_address || '—'}</dd>
        <dt>Risk score</dt>
        <dd><div className="row"><RiskScore score={result.risk_score} /><span className="mono small muted">min(100, {formula}) = {result.risk_score}</span></div></dd>
      </dl>

      <ConfirmationPanel txn={result} />
      <SimulatedDetails details={result.simulated_details} />

      <div>
        <h3>All nine SQL rules{result.rules_evaluated != null && <span className="muted small"> · evaluated in {result.evaluation_ms} ms</span>}</h3>
        <div className="table-wrap mt-8">
          <table className="table">
            <thead><tr><th>Rule</th><th>Result</th><th>Measured</th><th>Threshold</th><th className="right">Weight</th></tr></thead>
            <tbody>
              {result.rule_trace.map((t) => (
                <tr key={t.code} style={t.status === 'TRIGGERED' ? { background: '#FFF7F7' } : undefined}>
                  <td className="small"><span className="rule-chip">{t.code}</span> {t.name}</td>
                  <td><span className={`badge ${RULE_STATUS[t.status][1]}`}>{RULE_STATUS[t.status][0]}</span></td>
                  <td className="small">{t.observed || '—'}{t.reason && <div className="muted">{t.reason}</div>}</td>
                  <td className="small muted">{t.threshold || '—'}</td>
                  <td className="right small" style={{ fontWeight: 700, color: t.status === 'TRIGGERED' ? 'var(--danger)' : 'var(--muted)' }}>
                    {t.status === 'TRIGGERED' ? `+${t.weight}` : t.weight}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid grid-2">
        {['sender', 'receiver'].map((side) => {
          const b = result.balances?.[side];
          if (!b) return null;
          const changed = b.before != null && b.before !== b.after;
          return (
            <div key={side} className="card card-pad">
              <div className="stat-label">{side === 'sender' ? 'Victim (sender)' : 'Receiver'} · {b.name}</div>
              <div className="stat-value" style={{ fontSize: 18 }}>{money(b.after)}</div>
              <div className="small muted">{b.before == null ? 'current balance' : changed ? `was ${money(b.before)}` : 'unchanged'}</div>
            </div>
          );
        })}
      </div>

      <div>
        <h3>Activity timeline</h3>
        <div className="timeline mt-8">
          {result.timeline.map((item, i) => (
            <div className="timeline-item" key={i}>
              <div className="row small"><span>{TIMELINE_ICON[item.kind]}</span><strong>{item.label}</strong><span className="muted mono">{timeOnly(item.at)}</span></div>
              <div className="small muted">{item.detail}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
