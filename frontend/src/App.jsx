import { useEffect } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { useAuth } from './auth/AuthContext';
import { dashboardHref } from './roles';
import Layout from './components/Layout';
import TabbedPage from './components/TabbedPage';
import Landing from './pages/Landing';
import Login from './pages/Login';
import Notifications from './pages/Notifications';
import Register from './pages/Register';
import Alerts from './pages/detection/Alerts';
import DetectionEngine from './pages/detection/DetectionEngine';
import DetectionOverview from './pages/detection/Overview';
import Investigation from './pages/detection/Investigation';
import InvestigationCase from './pages/detection/InvestigationCase';
import InvestigationQueue from './pages/detection/InvestigationQueue';
import Monitor from './pages/detection/Monitor';
import Rules from './pages/detection/Rules';
import SecurityAudit from './pages/detection/SecurityAudit';
import Watchlist from './pages/detection/Watchlist';
import FrauderConsole from './pages/frauder/FrauderConsole';
import FrauderHistory from './pages/frauder/FrauderHistory';
import FraudRecords from './pages/frauder/FraudRecords';
import IncomingPayments from './pages/receiver/IncomingPayments';
import MyQR from './pages/receiver/MyQR';
import SendMoney from './pages/user/SendMoney';
import UserDashboard from './pages/user/UserDashboard';
import UserSecurity from './pages/user/UserSecurity';
import UserActivity from './pages/user/UserActivity';

// Not signed in, or signed in as another role: go through login for this role
// and come back to the exact page that was asked for.
function RequireRole({ role }) {
  const { session } = useAuth();
  const location = useLocation();
  if (!session || session.user.role !== role) {
    return <Navigate to={dashboardHref(session, role, location.pathname + location.search)} replace />;
  }
  return <Layout />;
}

function Home() {
  const { session } = useAuth();
  return <Navigate to={session ? session.dashboard : '/login'} replace />;
}

// Client-side navigation keeps the old scroll offset; start each page at the top.
function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);
  return null;
}

export default function App() {
  return (
    <>
      <ScrollToTop />
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />

        <Route path="/user" element={<RequireRole role="USER" />}>
          <Route index element={<UserDashboard />} />
          <Route path="send" element={<SendMoney />} />
          <Route element={<TabbedPage title="Receive money" subtitle="Share your QR or payment details, and see what has been credited to you."
                                      tabs={[['/user/qr', 'My QR & details'], ['/user/received', 'Money received']]} />}>
            <Route path="qr" element={<MyQR />} />
            <Route path="received" element={<IncomingPayments />} />
          </Route>
          <Route path="activity/:view" element={<UserActivity />} />
          <Route path="activity" element={<Navigate to="/user/activity/all" replace />} />
          {/* Transaction history now lives in Activity (with search, dates, sorting and status tabs). */}
          <Route path="transactions" element={<Navigate to="/user/activity/all" replace />} />
          <Route path="notifications" element={<Notifications />} />
          <Route path="security" element={<UserSecurity />} />
        </Route>

        {/* The Receiver login is retired: old links land on the same pages inside the User dashboard. */}
        <Route path="/receiver" element={<Navigate to="/user" replace />} />
        <Route path="/receiver/payments" element={<Navigate to="/user/received" replace />} />
        <Route path="/receiver/qr" element={<Navigate to="/user/qr" replace />} />
        <Route path="/receiver/*" element={<Navigate to="/user" replace />} />

        <Route path="/detection" element={<RequireRole role="DETECTION" />}>
          <Route index element={<DetectionOverview />} />
          <Route path="monitor" element={<Monitor />} />
          <Route path="transactions/:id" element={<Investigation />} />
          <Route path="investigations" element={<InvestigationQueue />} />
          <Route path="investigations/:id" element={<InvestigationCase />} />
          <Route path="alerts" element={<Alerts />} />
          <Route element={<TabbedPage title="Rules & watchlist" subtitle="What the engine checks, and who it always flags."
                                      tabs={[['/detection/rules', 'Fraud rules'], ['/detection/watchlist', 'Watchlist']]} />}>
            <Route path="rules" element={<Rules />} />
            <Route path="watchlist" element={<Watchlist />} />
          </Route>
          <Route element={<TabbedPage title="Tools" subtitle="Re-run the detection rules, and review logins and the audit trail."
                                      tabs={[['/detection/engine', 'Detection engine'], ['/detection/security', 'Security & audit']]} />}>
            <Route path="engine" element={<DetectionEngine />} />
            <Route path="security" element={<SecurityAudit />} />
          </Route>
        </Route>

        <Route path="/frauder" element={<RequireRole role="FRAUDER" />}>
          <Route index element={<FrauderConsole />} />
          <Route element={<TabbedPage title="Records" subtitle="What happened to every attempt you made."
                                      tabs={[['/frauder/records', 'Detection records'], ['/frauder/history', 'Attempt history']]} />}>
            <Route path="records" element={<FraudRecords />} />
            <Route path="history" element={<FrauderHistory />} />
          </Route>
        </Route>

        <Route path="*" element={<Home />} />
      </Routes>
    </>
  );
}
