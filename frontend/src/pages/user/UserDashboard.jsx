import { useState } from 'react';
import { Link } from 'react-router-dom';
import TxnDetailModal from '../../components/TxnDetailModal';
import TxnTable from '../../components/TxnTable';
import SecurityConfirmation from '../../components/SecurityConfirmation';
import { ErrorNote, Loading, PageHead, StatCard, StatusBadge } from '../../components/ui';
import { useApi } from '../../hooks';
import { money, timeAgo } from '../../utils/format';

export default function UserDashboard() {
  const { data, error, reload } = useApi('/user/dashboard', null, { interval: 6000 });
  const [selected, setSelected] = useState(null);

  if (!data) return error ? <ErrorNote error={error} /> : <Loading />;
  const { account, stats, recent, pending_reviews: pending, pending_confirmations: confirmations, security_alerts: security } = data;
  const withTeam = pending.filter((t) => t.review_stage === 'AWAITING_ANALYST');

  return (
    <>
      <PageHead title={`Hello, ${data.user.full_name.split(' ')[0]} 👋`} subtitle="Send and receive money – every payment is checked by the fraud engine.">
        <Link to="/user/qr" className="btn btn-ghost">🔳 Receive · My QR</Link>
        <Link to="/user/send" className="btn btn-primary">💸 Send money</Link>
      </PageHead>

      <SecurityConfirmation items={confirmations} onChange={() => reload(true)} />

      <div className="grid grid-main">
        <div className="card card-pad balance-card">
          <div className="muted small">Available balance</div>
          <div className="balance-amount">{money(account.balance)}</div>
          <div className="muted small">A/c {account.account_number} · IFSC {account.ifsc} · {account.upi_id}</div>
        </div>
        <div className="card card-pad">
          <h3>Security status</h3>
          {security.length === 0
            ? <p className="muted small mt-8">✅ No recent security warnings on your account.</p>
            : <ul className="small" style={{ paddingLeft: 18, margin: '8px 0 0' }}>
                {security.slice(0, 3).map((e) => <li key={e.id}><strong>{e.event_type.replaceAll('_', ' ').toLowerCase()}</strong> – {e.description} <span className="muted">({timeAgo(e.created_at)})</span></li>)}
              </ul>}
          <Link to="/user/security" className="small">View security activity →</Link>
        </div>
      </div>

      <div className="grid grid-4 mt-16">
        <StatCard icon="↗" tone="blue" label="Money sent" value={money(stats.total_sent)} sub={`${stats.completed} successful payment${stats.completed === 1 ? '' : 's'}`} />
        <StatCard icon="↙" tone="green" label="Money received" value={money(stats.total_received)} sub={`${stats.received} credited payment${stats.received === 1 ? '' : 's'}`} />
        <StatCard icon="🔐" tone="amber" label="Awaiting your answer" value={confirmations.length} sub="Held, not debited" />
        <StatCard icon="⛔" tone="red" label="Blocked" value={stats.blocked} sub="Denied or stopped – no money moved" />
      </div>
      <p className="muted small mt-8">⌛ {stats.expired + stats.declined} expired or declined (never authorized). Incoming money appears only once it passes the fraud checks and is credited.</p>

      {withTeam.length > 0 && (
        <div className="card mt-16">
          <div className="card-head" style={{ background: 'var(--warning-bg)' }}>
            <h2>⏳ With our fraud team</h2>
            <span className="small muted">Not answered in time and passed to an analyst – nothing has been debited</span>
          </div>
          <div className="list">
            {withTeam.map((t) => (
              <div className="list-item" key={t.id} style={{ flexWrap: 'wrap' }}>
                <div style={{ flex: 1, minWidth: 240 }}>
                  <strong>{money(t.amount)} to {t.receiver.name}</strong>
                  <div className="small muted">{t.txn_ref} · {t.final_reason || t.risk_explanation}</div>
                </div>
                <StatusBadge status="UNDER_REVIEW" label="With fraud team" />
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="card mt-16">
        <div className="card-head">
          <h2>Recent activity</h2>
          <Link to="/user/transactions" className="small">View all →</Link>
        </div>
        <TxnTable items={recent} onSelect={setSelected} emptyText="No payments yet – send one, or share your QR to get paid." />
      </div>

      {selected && (
        <TxnDetailModal txn={selected} viewer={selected.direction === 'IN' ? 'receiver' : 'sender'}
                        onClose={() => setSelected(null)} onChange={() => reload(true)} />
      )}
    </>
  );
}
