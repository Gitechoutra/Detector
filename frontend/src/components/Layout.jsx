import { useState } from 'react';
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { useApi } from '../hooks';
import { Avatar } from './ui';

const NAV = {
  USER: {
    title: 'User', mark: 'U', home: '/user',
    items: [
      ['/user', '🏠', 'Dashboard', true], ['/user/send', '💸', 'Send Money'], ['/user/received', '📥', 'Money Received'],
      ['/user/qr', '🔳', 'My QR & UPI'], ['/user/transactions', '📄', 'Transactions'],
      ['/user/notifications', '🔔', 'Notifications', false, 'notifications'], ['/user/security', '🛡️', 'Security'],
    ],
  },
  DETECTION: {
    title: 'Detection System', mark: 'D', home: '/detection',
    items: [
      ['/detection', '📊', 'Overview', true], ['/detection/monitor', '📡', 'Live Monitor'],
      ['/detection/alerts', '🚨', 'Alerts & Cases', false, 'alerts'], ['/detection/rules', '⚙️', 'Fraud Rules'],
      ['/detection/watchlist', '🚫', 'Watchlist'], ['/detection/security', '🔐', 'Security & Audit'],
    ],
  },
  FRAUDER: {
    title: 'Frauder', mark: 'F', home: '/frauder',
    items: [['/frauder', '🕵️', 'Frauder Console', true], ['/frauder/history', '🗂️', 'Attempt History']],
  },
};

const TONE = { USER: 'blue', DETECTION: 'purple', FRAUDER: 'red' };

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const role = user.role;
  const nav = NAV[role];

  const notes = useApi('/notifications', { unread: 1, page_size: 1 }, { interval: 5000, enabled: role !== 'DETECTION' && role !== 'FRAUDER' });
  const alerts = useApi('/alerts', { status: 'OPEN', page_size: 1 }, { interval: 5000, enabled: role === 'DETECTION' });
  const counts = { notifications: notes.data?.unread, alerts: alerts.data?.meta?.total };

  const doLogout = async () => {
    await logout();
    navigate('/login');
  };

  return (
    <div className={`app role-${role}`}>
      <aside className={`sidebar ${open ? 'open' : ''}`}>
        <div className="brand">
          <div className="brand-mark">{nav.mark}</div>
          <div>
            <div className="brand-name">FraudShield</div>
            <div className="brand-role">{nav.title}</div>
          </div>
        </div>
        <nav className="nav" onClick={() => setOpen(false)}>
          {nav.items.map(([to, icon, label, end, countKey]) => (
            <NavLink key={to} to={to} end={end}>
              <span aria-hidden>{icon}</span>{label}
              {countKey && counts[countKey] > 0 && <span className="count-pill badge-count">{counts[countKey]}</span>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <Link to="/demo" className="small">🎓 Demo Mode guide</Link>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="row">
            <button className="btn btn-ghost btn-sm menu-btn" onClick={() => setOpen(!open)} aria-label="Menu">☰</button>
            <span className="muted small">Simulated banking environment · no real money moves</span>
          </div>
          <div className="row">
            <Avatar name={user.full_name} tone={TONE[role]} />
            <div className="small" style={{ lineHeight: 1.3 }}>
              <div style={{ fontWeight: 600 }}>{user.full_name}</div>
              <div className="muted">{user.email}</div>
            </div>
            <button className="btn btn-ghost btn-sm" onClick={doLogout}>Log out</button>
          </div>
        </header>
        <main className="content"><Outlet /></main>
      </div>
    </div>
  );
}
