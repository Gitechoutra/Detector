import { useState } from 'react';
import { get } from '../../api/client';
import DetectionResult from '../../components/DetectionResult';
import { Empty, ErrorNote, Loading, Modal, OutcomeBadge, PageHead, RiskScore, RuleChips } from '../../components/ui';
import { useApi } from '../../hooks';
import { dateTime } from '../../utils/format';

export default function FrauderHistory() {
  const { data, error } = useApi('/frauder/attempts', null, { interval: 4000 });
  const [open, setOpen] = useState(null);

  return (
    <>
      <PageHead title="Fraud attempt history" subtitle="Every login attempt, wrong OTP and transfer you made as the Frauder, with the account owner’s answer. Click a transfer to see its full detection result." />
      <div className="card">
        <ErrorNote error={error} />
        {!data ? <Loading /> : !data.length ? <Empty icon="🕵️" title="No attempts yet" /> : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>When</th><th>Victim</th><th>Action</th><th>Details</th><th>Rules</th><th>Score</th><th>Outcome</th><th>Money</th></tr></thead>
              <tbody>
                {data.map((a, i) => (
                  <tr key={i} className={a.transaction_id ? 'clickable' : ''}
                      onClick={() => a.transaction_id && get(`/frauder/transactions/${a.transaction_id}`).then(setOpen)}>
                    <td className="small nowrap">{dateTime(a.at)}</td>
                    <td className="small">{a.victim}</td>
                    <td className="small"><strong>{a.summary}</strong>{a.txn_ref && <div className="mono muted">{a.txn_ref}</div>}{a.scenario && <div className="muted">{a.scenario}</div>}</td>
                    <td className="small muted">{a.detail}</td>
                    <td>{a.rules ? <RuleChips rules={a.rules} /> : <span className="muted small">—</span>}</td>
                    <td>{a.risk_score != null ? <RiskScore score={a.risk_score} /> : <span className="muted small">—</span>}</td>
                    <td>{a.type === 'TRANSFER' ? <OutcomeBadge label={a.outcome_label} />
                      : <span className={`badge ${a.outcome === 'SUCCESS' ? 'b-amber' : 'b-slate'}`}>{a.type === 'OTP' ? 'Wrong OTP' : a.outcome === 'SUCCESS' ? 'Logged in' : 'Failed'}</span>}</td>
                    <td className="small">{a.type !== 'TRANSFER' ? '—' : a.money_moved
                      ? <span style={{ color: 'var(--warning)', fontWeight: 600 }}>Transferred</span>
                      : <span style={{ color: 'var(--success)', fontWeight: 600 }}>Prevented / held</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      {open && <Modal large title={`Detection result · ${open.txn_ref}`} onClose={() => setOpen(null)}><DetectionResult result={open} /></Modal>}
    </>
  );
}
