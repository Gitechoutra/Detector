import { useEffect } from 'react';
import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { useAuth } from './auth/AuthContext';
import { dashboardHref } from './roles';
import Layout from './components/Layout';
import DemoMode from './pages/DemoMode';
import Landing from './pages/Landing';
import Login from './pages/Login';
import Notifications from './pages/Notifications';
import Register from './pages/Register';
import Alerts from './pages/detection/Alerts';
import DetectionOverview from './pages/detection/Overview';
import Investigation from './pages/detection/Investigation';
import Monitor from './pages/detection/Monitor';
import Rules from './pages/detection/Rules';
import SecurityAudit from './pages/detection/SecurityAudit';
import Watchlist from './pages/detection/Watchlist';
import FrauderConsole from './pages/frauder/FrauderConsole';
import FrauderHistory from './pages/frauder/FrauderHistory';
import IncomingPayments from './pages/receiver/IncomingPayments';
import MyQR from './pages/receiver/MyQR';
import SendMoney from './pages/user/SendMoney';
import UserDashboard from './pages/user/UserDashboard';
import UserSecurity from './pages/user/UserSecurity';
import UserTransactions from './pages/user/UserTransactions';

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
        <Route path="/demo" element={<DemoMode />} />

        <Route path="/user" element={<RequireRole role="USER" />}>
          <Route index element={<UserDashboard />} />
          <Route path="send" element={<SendMoney />} />
          <Route path="received" element={<IncomingPayments />} />
          <Route path="qr" element={<MyQR />} />
          <Route path="transactions" element={<UserTransactions />} />
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
          <Route path="alerts" element={<Alerts />} />
          <Route path="rules" element={<Rules />} />
          <Route path="watchlist" element={<Watchlist />} />
          <Route path="security" element={<SecurityAudit />} />
        </Route>

        <Route path="/frauder" element={<RequireRole role="FRAUDER" />}>
          <Route index element={<FrauderConsole />} />
          <Route path="history" element={<FrauderHistory />} />
        </Route>

        <Route path="*" element={<Home />} />
      </Routes>
    </>
  );
}
