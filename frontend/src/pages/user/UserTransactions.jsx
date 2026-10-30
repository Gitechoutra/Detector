import { useState } from 'react';
import TxnDetailModal from '../../components/TxnDetailModal';
import TxnTable from '../../components/TxnTable';
import { ErrorNote, Loading, PageHead, Pagination } from '../../components/ui';
import { useApi } from '../../hooks';

export default function UserTransactions() {
  const [filters, setFilters] = useState({ status: '', direction: '', page: 1 });
  const { data, error, loading, reload } = useApi('/user/transactions', filters, { interval: 8000 });
  const [selected, setSelected] = useState(null);
  const set = (k) => (e) => setFilters((f) => ({ ...f, [k]: e.target.value, page: 1 }));

  return (
    <>
      <PageHead title="Transaction history" subtitle="Every payment you sent or received, with its fraud-check result." />
      <div className="card">
        <div className="filters">
          <select className="input input-sm" value={filters.direction} onChange={set('direction')}>
            <option value="">Sent & received</option><option value="OUT">Sent</option><option value="IN">Received</option>
          </select>
          <select className="input input-sm" value={filters.status} onChange={set('status')}>
            <option value="">All statuses</option><option value="COMPLETED">Successful</option>
            <option value="UNDER_REVIEW">Confirmation pending</option><option value="BLOCKED">Blocked</option>
            <option value="EXPIRED">Expired</option><option value="DECLINED">Declined</option><option value="CANCELLED">Cancelled</option>
          </select>
        </div>
        <ErrorNote error={error} />
        {loading && !data ? <Loading /> : <TxnTable items={data?.items} onSelect={setSelected} />}
        <Pagination meta={data?.meta} onPage={(page) => setFilters((f) => ({ ...f, page }))} />
      </div>
      {selected && (
        <TxnDetailModal txn={selected} viewer={selected.direction === 'IN' ? 'receiver' : 'sender'} onClose={() => setSelected(null)}
                        onChange={() => reload(true)} />
      )}
    </>
  );
}
