import { useState } from 'react';
import { Link } from 'react-router-dom';
import TxnDetailModal from '../../components/TxnDetailModal';
import TxnTable from '../../components/TxnTable';
import { ErrorNote, Loading, PageHead, StatCard } from '../../components/ui';
import { useApi } from '../../hooks';
import { money } from '../../utils/format';

export default function ReceiverDashboard() {
  const { data, error } = useApi('/receiver/dashboard', null, { interval: 4000 });
  const [selected, setSelected] = useState(null);
  if (!data) return error ? <ErrorNote error={error} /> : <Loading />;
  const { account, stats, recent } = data;

  return (
    <>
      <PageHead title={`Welcome, ${data.user.full_name.split(' ')[0]}`} subtitle="Money you receive is credited only after it passes the fraud checks.">
        <Link to="/receiver/qr" className="btn btn-primary">🔳 Show my QR</Link>
      </PageHead>

      <div className="grid grid-main">
        <div className="card card-pad balance-card">
          <div className="muted small">Account balance</div>
          <div className="balance-amount">{money(account.balance)}</div>
          <div className="muted small">A/c {account.account_number} · IFSC {account.ifsc} · {account.upi_id}</div>
        </div>
        <div className="grid grid-2">
          <StatCard icon="₹" tone="green" label="Total received" value={money(stats.total_received)} />
          <StatCard icon="✓" tone="green" label="Credited payments" value={stats.credited} />
        </div>
      </div>
      <p className="muted small mt-8">🛡️ A payment appears here only after it passes the fraud checks and is credited. Payments still being checked, or blocked, are never shown as received money.</p>

      <div className="card mt-16">
        <div className="card-head">
          <div className="row"><h2>Incoming payments</h2><span className="live-dot" title="Live" /></div>
          <Link to="/receiver/payments" className="small">View all →</Link>
        </div>
        <TxnTable items={recent} perspective="receiver" onSelect={setSelected} emptyText="No incoming payments yet." />
      </div>
      {selected && <TxnDetailModal txn={selected} viewer="receiver" onClose={() => setSelected(null)} />}
    </>
  );
}
