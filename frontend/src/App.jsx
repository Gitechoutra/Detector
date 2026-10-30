import { Navigate, Route, Routes } from 'react-router-dom';
import { useAuth } from './auth/AuthContext';
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
import ReceiverDashboard from './pages/receiver/ReceiverDashboard';
import SendMoney from './pages/user/SendMoney';
import UserDashboard from './pages/user/UserDashboard';
import UserSecurity from './pages/user/UserSecurity';
import UserTransactions from './pages/user/UserTransactions';

function RequireRole({ role }) {
  const { session } = useAuth();
  if (!session) return <Navigate to="/login" replace />;
  if (session.user.role !== role) return <Navigate to={session.dashboard} replace />;
  return <Layout />;
}

function Home() {
  const { session } = useAuth();
  return <Navigate to={session ? session.dashboard : '/login'} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/demo" element={<DemoMode />} />

      <Route path="/user" element={<RequireRole role="USER" />}>
        <Route index element={<UserDashboard />} />
        <Route path="send" element={<SendMoney />} />
        <Route path="transactions" element={<UserTransactions />} />
        <Route path="notifications" element={<Notifications />} />
        <Route path="security" element={<UserSecurity />} />
      </Route>

      <Route path="/receiver" element={<RequireRole role="RECEIVER" />}>
        <Route index element={<ReceiverDashboard />} />
        <Route path="payments" element={<IncomingPayments />} />
        <Route path="qr" element={<MyQR />} />
        <Route path="notifications" element={<Notifications />} />
      </Route>

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
  );
}
