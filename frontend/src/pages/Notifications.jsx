import { useState } from 'react';
import { errorMessage, post } from '../api/client';
import { useToast } from '../components/Toast';
import { useConfirmationAnswer } from '../components/SecurityConfirmation';
import { Empty, ErrorNote, Loading, PageHead, Pagination } from '../components/ui';
import { useApi } from '../hooks';
import { timeAgo } from '../utils/format';

const ICON = { SUCCESS: ['✓', 'tone-green'], WARNING: ['⚠', 'tone-amber'], DANGER: ['⛔', 'tone-red'], OTP: ['📱', 'tone-purple'], INFO: ['i', 'tone-blue'] };

export default function Notifications() {
  const toast = useToast();
  const [page, setPage] = useState(1);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const { data, error, loading, reload } = useApi('/notifications', { page, unread: unreadOnly ? 1 : undefined }, { interval: 5000 });
  const { answer, busy } = useConfirmationAnswer(() => reload(true));

  const markAll = async () => {
    try {
      await post('/notifications/read-all');
      reload(true);
    } catch (e) {
      toast(errorMessage(e), 'error');
    }
  };
  const markOne = async (n) => {
    if (n.is_read) return;
    await post(`/notifications/${n.id}/read`).catch(() => {});
    reload(true);
  };

  return (
    <>
      <PageHead title="Notifications" subtitle="Payment updates, security alerts and simulated SMS messages.">
        <label className="row small"><input type="checkbox" checked={unreadOnly} onChange={(e) => { setUnreadOnly(e.target.checked); setPage(1); }} /> Unread only</label>
        <button className="btn btn-ghost btn-sm" onClick={markAll} disabled={!data?.unread}>Mark all read</button>
      </PageHead>
      <div className="card">
        <ErrorNote error={error} />
        {loading && !data ? <Loading /> : !data?.items.length ? <Empty icon="🔔" title="You're all caught up" /> : (
          <div className="list">
            {data.items.map((n) => {
              const [icon, tone] = ICON[n.category] || ICON.INFO;
              return (
                <div key={n.id} className={`list-item ${n.is_read ? '' : 'unread'}`} onClick={() => markOne(n)} style={{ cursor: n.is_read ? 'default' : 'pointer' }}>
                  <div className={`stat-icon ${tone}`} style={{ width: 34, height: 34, fontSize: 15 }}>{icon}</div>
                  <div style={{ flex: 1 }}>
                    <div className="row-between"><strong>{n.title}</strong><span className="muted small nowrap">{timeAgo(n.created_at)}</span></div>
                    <div className={n.category === 'OTP' ? 'sms mt-8' : 'muted small'}>{n.message}</div>
                    {n.title === 'Security Verification Required' && !n.is_read && n.transaction_id && (
                      <div className="row wrap mt-8" onClick={(e) => e.stopPropagation()}>
                        <button className="btn btn-success btn-sm" disabled={!!busy} onClick={() => answer({ id: n.transaction_id }, 'YES')}>✓ YES, I INITIATED THIS TRANSACTION</button>
                        <button className="btn btn-danger btn-sm" disabled={!!busy} onClick={() => answer({ id: n.transaction_id }, 'NO')}>✕ NO, I DID NOT INITIATE THIS TRANSACTION</button>
                      </div>
                    )}
                  </div>
                  {!n.is_read && <span className="live-dot" style={{ background: 'var(--primary)', animation: 'none' }} />}
                </div>
              );
            })}
          </div>
        )}
        <Pagination meta={data?.meta} onPage={setPage} />
      </div>
    </>
  );
}
