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
        <Link to="/user/qr" className="btn btn-ghost">Receive</Link>
        <Link to="/user/send" className="btn btn-primary">Send money</Link>
      </PageHead>

      <SecurityConfirmation items={confirmations} onChange={() => reload(true)} />

      {data.restriction?.status === 'TEMPORARILY_BLOCKED' && (
        <div className="notice notice-danger" style={{ marginBottom: 16 }}>
          <strong>⚠ Suspicious activity detected – your account is temporarily restricted.</strong> Payments from your
          account are disabled while our fraud team investigates (case {data.restriction.case_ref}). You can still
          receive money. We will notify you as soon as the investigation is complete.
        </div>
      )}
      {data.restriction?.status === 'PERMANENTLY_BLOCKED' && (
        <div className="notice notice-danger" style={{ marginBottom: 16 }}>
          <strong>⛔ Your account has been permanently blocked</strong> after a fraud investigation
          {data.restriction.case_ref && ` (case ${data.restriction.case_ref})`}. No payments can be made to or from it.
          Please contact the bank.
        </div>
      )}
      {account.status === 'BLOCKED' && (
        <div className="notice notice-danger" style={{ marginBottom: 16 }}>
          <strong>⛔ Your account is blocked from receiving payments.</strong> A payment to you was reported as not
          initiated by the payer's account owner. You can still send money; our fraud team will review the block.
        </div>
      )}

      <div className="grid grid-main">
        <Link to="/user/activity/all" className="card card-pad balance-card card-link" title="View all transactions">
          <div className="muted small">Available balance</div>
          <div className="balance-amount">{money(account.balance)}</div>
          <div className="muted small">A/c {account.account_number} · IFSC {account.ifsc} · {account.upi_id}</div>
        </Link>
        <Link to="/user/security" className="card card-pad card-link" title="View security activity">
          <h3>Security status</h3>
          {security.length === 0
            ? <p className="muted small mt-8">✅ No recent security warnings on your account.</p>
            : <ul className="small" style={{ paddingLeft: 18, margin: '8px 0 0' }}>
                {security.slice(0, 3).map((e) => <li key={e.id}><strong>{e.event_type.replaceAll('_', ' ').toLowerCase()}</strong> – {e.description} <span className="muted">({timeAgo(e.created_at)})</span></li>)}
              </ul>}
          <span className="small" style={{ color: 'var(--accent)', fontWeight: 600 }}>View security activity →</span>
        </Link>
      </div>

      <div className="grid grid-4 mt-16">
        <StatCard to="/user/activity/all" icon="🧾" tone="blue" label="Total transactions" value={stats.total} sub="Sent and received" />
        <StatCard to="/user/activity/successful" icon="✓" tone="green" label="Successful" value={stats.successful} sub="Completed payments" />
        <StatCard to="/user/activity/pending" icon="⏳" tone="amber" label="Pending" value={stats.pending} sub="Processing or awaiting verification" />
        <StatCard to="/user/activity/failed" icon="✕" tone="slate" label="Failed" value={stats.failed} sub="Declined, cancelled or expired" />
      </div>
      <div className="grid grid-4 mt-16">
        <StatCard to="/user/activity/blocked" icon="⛔" tone="red" label="Blocked" value={stats.blocked} sub="Stopped by fraud checks – no money moved" />
        <StatCard to="/user/activity/sent" icon="↗" tone="blue" label="Money sent" value={money(stats.total_sent)} sub={`${stats.completed} successful payment${stats.completed === 1 ? '' : 's'}`} />
        <StatCard to="/user/activity/received" icon="↙" tone="green" label="Money received" value={money(stats.total_received)} sub={`${stats.received} credited payment${stats.received === 1 ? '' : 's'}`} />
        <StatCard to="/user/activity/awaiting" icon="🔐" tone="amber" label="Awaiting your answer" value={confirmations.length} sub="Held, not debited" />
      </div>
      <p className="muted small mt-8">Select a card to see its transactions. Incoming money appears only once it passes the fraud checks and is credited.</p>

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
          <Link to="/user/activity/all" className="small">View all →</Link>
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
