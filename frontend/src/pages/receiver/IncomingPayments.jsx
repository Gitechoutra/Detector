import { useState } from 'react';
import TxnDetailModal from '../../components/TxnDetailModal';
import TxnTable from '../../components/TxnTable';
import { ErrorNote, Loading, PageHead, Pagination } from '../../components/ui';
import { useApi } from '../../hooks';

export default function IncomingPayments() {
  const [filters, setFilters] = useState({ page: 1 });
  const { data, error, loading } = useApi('/receiver/payments', filters, { interval: 5000 });
  const [selected, setSelected] = useState(null);

  return (
    <>
      <PageHead title="Money received" subtitle="Payments credited to your account. Payments still being checked, or blocked, never appear here." />
      <div className="card">
        <ErrorNote error={error} />
        {loading && !data ? <Loading /> : <TxnTable items={data?.items} perspective="receiver" onSelect={setSelected} emptyText="No payments match." />}
        <Pagination meta={data?.meta} onPage={(page) => setFilters((f) => ({ ...f, page }))} />
      </div>
      {selected && <TxnDetailModal txn={selected} viewer="receiver" onClose={() => setSelected(null)} />}
    </>
  );
}
