import { useState } from 'react';
import { Link } from 'react-router-dom';
import { errorMessage, post } from '../../api/client';
import { useToast } from '../../components/Toast';
import TxnDetailModal from '../../components/TxnDetailModal';
import TxnTable from '../../components/TxnTable';
import SecurityConfirmation from '../../components/SecurityConfirmation';
import VerifyPaymentModal from '../../components/VerifyPaymentModal';
import { ErrorNote, Loading, PageHead, StatCard, StatusBadge } from '../../components/ui';
import { useApi } from '../../hooks';
import { money, timeAgo } from '../../utils/format';

export default function UserDashboard() {
  const toast = useToast();
  const { data, error, reload } = useApi('/user/dashboard', null, { interval: 6000 });
  const [selected, setSelected] = useState(null);
  const [verifying, setVerifying] = useState(null);

  if (!data) return error ? <ErrorNote error={error} /> : <Loading />;
  const { account, stats, recent, pending_reviews: pending, pending_confirmations: confirmations, security_alerts: security } = data;
  const withTeam = pending.filter((t) => t.review_stage === 'AWAITING_ANALYST');

  const report = async (txn) => {
    try {
      const res = await post(`/transactions/${txn.id}/confirmation`, { response: 'NO' });
      toast(res.message, 'success', 'Payment blocked');
      setSelected(null);
      reload(true);
    } catch (e) {
      toast(errorMessage(e), 'error');
    }
  };

  return (
    <>
      <PageHead title={`Hello, ${data.user.full_name.split(' ')[0]} 👋`} subtitle="Your account, payments and security at a glance.">
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
        <StatCard icon="✓" tone="green" label="Successful payments" value={stats.completed} sub={`${money(stats.total_sent)} sent`} />
        <StatCard icon="⏸" tone="amber" label="Under review" value={stats.under_review} sub="Held, not debited" />
        <StatCard icon="⛔" tone="red" label="Blocked" value={stats.blocked} sub="Stopped by fraud checks" />
        <StatCard icon="↩" tone="slate" label="Declined / cancelled" value={stats.declined} />
      </div>

      {withTeam.length > 0 && (
        <div className="card mt-16">
          <div className="card-head" style={{ background: 'var(--warning-bg)' }}>
            <h2>⏳ With our fraud team</h2>
            <span className="small muted">You confirmed these, but they still need an analyst – nothing has been debited</span>
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
        <TxnTable items={recent} onSelect={setSelected} emptyText="No payments yet – send your first one." />
      </div>

      {selected && (
        <TxnDetailModal txn={selected} viewer={selected.direction === 'IN' ? 'receiver' : 'sender'}
                        onClose={() => setSelected(null)}
                        onVerify={() => { setVerifying(selected); setSelected(null); }}
                        onReport={() => report(selected)} />
      )}
      {verifying && <VerifyPaymentModal txn={verifying} onClose={() => { setVerifying(null); reload(true); }} onDone={() => reload(true)} />}
    </>
  );
}
