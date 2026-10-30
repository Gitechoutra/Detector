import { dateTime, money, METHOD_LABEL } from '../utils/format';
import { Avatar, Empty, OutcomeBadge, RiskScore, StatusBadge } from './ui';

/** Customer-facing list (User and Receiver portals). */
export default function TxnTable({ items, onSelect, perspective = 'user', emptyText }) {
  if (!items?.length) return <Empty title={emptyText || 'No transactions yet'} />;
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>{perspective === 'receiver' ? 'From' : 'Party'}</th><th>Amount</th><th>Method</th>
            <th>Date</th><th>Risk</th><th>Status</th>
          </tr>
        </thead>
        <tbody>
          {items.map((t) => {
            const incoming = perspective === 'receiver' || t.direction === 'IN';
            const party = incoming ? t.sender : t.receiver;
            return (
              <tr key={t.id} className="clickable" onClick={() => onSelect?.(t)}>
                <td>
                  <div className="row">
                    <Avatar name={party.name} tone={incoming ? 'green' : 'blue'} />
                    <div>
                      <div style={{ fontWeight: 600 }}>{party.name}{t.is_simulated && <span className="badge b-purple" style={{ marginLeft: 6 }}>Frauder</span>}</div>
                      <div className="muted small">{incoming ? 'Received from' : 'Sent to'} · {party.upi_id}</div>
                    </div>
                  </div>
                </td>
                <td className="nowrap" style={{ fontWeight: 700, color: incoming && t.status === 'COMPLETED' ? 'var(--success)' : undefined }}>
                  {incoming ? '+' : '−'}{money(t.amount)}
                </td>
                <td>{METHOD_LABEL[t.payment_method]}</td>
                <td className="nowrap muted">{dateTime(t.txn_time)}</td>
                <td><RiskScore score={t.risk_score} /></td>
                <td>
                  {perspective === 'user' && !incoming && t.confirmation ? <OutcomeBadge label={t.outcome_label} /> : <StatusBadge status={t.display_status || t.status} />}
                  {t.status === 'UNDER_REVIEW' && t.review_stage === 'AWAITING_CUSTOMER' && perspective === 'user' && !incoming &&
                    <div className="small" style={{ color: 'var(--warning)', fontWeight: 600 }}>Action needed – was this you?</div>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
