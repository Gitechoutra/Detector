import { Suspense, useState } from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { useApi } from '../hooks';
import Icon from './Icon';
import { Avatar, Loading } from './ui';

// [link, icon, label, paths that keep it highlighted, badge count]. Related screens share one entry
// and appear as tabs on its page, so every feature stays one click away.
const NAV = {
  USER: {
    title: 'Personal banking',
    items: [
      ['/user', 'home', 'Home', ['/user']],
      ['/user/send', 'send', 'Send money', ['/user/send']],
      ['/user/qr', 'qr', 'Receive', ['/user/qr', '/user/received']],
      ['/user/activity/all', 'list', 'Activity', ['/user/activity']],
      ['/user/notifications', 'bell', 'Notifications', ['/user/notifications'], 'notifications'],
      ['/user/security', 'shield', 'Security', ['/user/security']],
    ],
  },
  DETECTION: {
    title: 'Fraud detection',
    items: [
      ['/detection', 'grid', 'Overview', ['/detection']],
      ['/detection/investigations', 'folder', 'Investigations', ['/detection/investigations'], 'investigations'],
      ['/detection/monitor', 'activity', 'Transactions', ['/detection/monitor', '/detection/transactions']],
      ['/detection/alerts', 'alert', 'Alerts', ['/detection/alerts'], 'alerts'],
      ['/detection/rules', 'sliders', 'Rules & watchlist', ['/detection/rules', '/detection/watchlist']],
      ['/detection/engine', 'tool', 'Tools', ['/detection/engine', '/detection/security']],
    ],
  },
  FRAUDER: {
    title: 'Frauder simulation',
    items: [
      ['/frauder', 'mask', 'Console', ['/frauder']],
      ['/frauder/records', 'fileText', 'Records', ['/frauder/records', '/frauder/history']],
    ],
  },
};

// A section's root (/user) only matches itself; other entries also match their sub-pages.
const isActive = (pathname, paths) => paths.some((p) => pathname === p || (p.split('/').length > 2 && pathname.startsWith(`${p}/`)));

const TONE = { USER: 'blue', DETECTION: 'purple', FRAUDER: 'red' };

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const { pathname } = useLocation();
  const [open, setOpen] = useState(false);
  const role = user.role;
  const nav = NAV[role];

  const notes = useApi('/notifications', { unread: 1, page_size: 1 }, { interval: 5000, enabled: role !== 'DETECTION' && role !== 'FRAUDER' });
  const alerts = useApi('/alerts', { status: 'OPEN', page_size: 1 }, { interval: 5000, enabled: role === 'DETECTION' });
  const cases = useApi('/detection/investigations', { view: 'open', page_size: 1 }, { interval: 10000, enabled: role === 'DETECTION' });
  const counts = { notifications: notes.data?.unread, alerts: alerts.data?.meta?.total, investigations: cases.data?.counts?.open };

  const doLogout = async () => {
    await logout();
    navigate('/login');
  };

  return (
    <div className={`app role-${role}`}>
      {open && <div className="sidebar-scrim" onClick={() => setOpen(false)} aria-hidden />}
      <aside className={`sidebar ${open ? 'open' : ''}`}>
        <div className="brand">
          <div className="brand-mark"><Icon name="shield" size={18} stroke={2.2} /></div>
          <div>
            <div className="brand-name">FraudShield</div>
            <div className="brand-role">{nav.title}</div>
          </div>
        </div>
        <nav className="nav" onClick={() => setOpen(false)}>
          {nav.items.map(([to, icon, label, paths, countKey]) => {
            const active = isActive(pathname, paths);
            return (
              <Link key={to} to={to} className={active ? 'active' : undefined} aria-current={active ? 'page' : undefined}>
                <Icon name={icon} size={18} />{label}
                {countKey && counts[countKey] > 0 && <span className="count-pill badge-count">{counts[countKey]}</span>}
              </Link>
            );
          })}
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="row">
            <button className="btn btn-ghost btn-sm menu-btn" onClick={() => setOpen(!open)} aria-label="Menu"><Icon name="menu" size={18} /></button>
            <span className="env-chip">Simulated environment · no real money moves</span>
          </div>
          <div className="row">
            <Avatar name={user.full_name} tone={TONE[role]} />
            <div className="small user-id">
              <div style={{ fontWeight: 600 }}>{user.full_name}</div>
              <div className="muted">{user.email}</div>
            </div>
            <button className="btn btn-ghost btn-sm" onClick={doLogout} title="Log out"><Icon name="logout" size={16} /><span className="hide-sm">Log out</span></button>
          </div>
        </header>
        <main className="content"><Suspense fallback={<Loading />}><Outlet /></Suspense></main>
      </div>
    </div>
  );
}
