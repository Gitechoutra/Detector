import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { errorMessage, get, post } from '../api/client';
import { useToast } from '../components/Toast';
import { Loading, Modal } from '../components/ui';
import { rotateDeviceId } from '../utils/device';

const ROLE_TONE = { USER: 'b-blue', RECEIVER: 'b-green', DETECTION: 'b-purple', FRAUDER: 'b-red' };

export default function DemoMode() {
  const toast = useToast();
  const [info, setInfo] = useState(null);
  const [error, setError] = useState('');
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetting, setResetting] = useState(false);

  useEffect(() => {
    get('/demo/info').then(setInfo).catch((e) => setError(errorMessage(e)));
  }, []);

  const open = (email) => window.open(`/login?as=${encodeURIComponent(email)}`, '_blank', 'noopener');

  const resetAttempts = async () => {
    try {
      const res = await post('/demo/reset-attempts', { confirm: 'RESET' });
      toast(res.message, 'success', 'Fraud attempts reset');
    } catch (e) {
      toast(errorMessage(e), 'error');
    }
  };

  const resetAll = async () => {
    setResetting(true);
    try {
      const res = await post('/demo/reset', { confirm: 'RESET' });
      setConfirmReset(false);
      toast(res.message, 'success', 'Demo data reset');
    } catch (e) {
      toast(errorMessage(e), 'error');
    } finally {
      setResetting(false);
    }
  };

  const newDevice = () => {
    rotateDeviceId();
    toast('This browser now looks like a brand-new device. Log in again as Rahul and send ₹30,000+ to see R4 and R9.', 'info', 'New device simulated');
  };

  return (
    <div style={{ minHeight: '100vh' }} className="role-DETECTION">
      <header className="topbar">
        <div className="row">
          <div className="brand-mark">FS</div>
          <strong>FraudShield · Viva Demo Mode</strong>
        </div>
        <div className="row wrap">
          <Link to="/login" className="btn btn-ghost btn-sm">← Normal login</Link>
          <button className="btn btn-ghost btn-sm" onClick={resetAttempts} title="Reverse only Frauder transfers">↺ Reset fraud attempts</button>
          <button className="btn btn-danger-soft btn-sm" onClick={() => setConfirmReset(true)}>↺ Reset all demo data</button>
        </div>
      </header>

      <main className="content" style={{ margin: '0 auto' }}>
        {error && <div className="notice notice-danger">⚠ {error}</div>}
        {!info && !error && <Loading />}
        {info && (
          <div className="stack">
            <div className="demo-banner">
              <h1>Guided presentation</h1>
              <p className="muted mt-8">
                You act out all three roles by hand: the genuine User, the Receiver and the Frauder. Nothing runs on
                its own – the SQL fraud engine automatically checks every login and payment you make. Open each role
                in its own browser tab (every tab keeps its own login).
              </p>
            </div>

            <div className="grid grid-main">
              <div className="card">
                <div className="card-head"><h2>1 · Demo logins</h2><span className="muted small">Opens in a new tab</span></div>
                <div className="table-wrap">
                  <table className="table cred-table">
                    <thead><tr><th>Role</th><th>Name</th><th>Email / password</th><th /></tr></thead>
                    <tbody>
                      {info.credentials.map((c) => (
                        <tr key={c.email}>
                          <td><span className={`badge ${ROLE_TONE[c.role]}`}>{c.label}</span></td>
                          <td><strong>{c.name}</strong><div className="muted small">{c.what}</div></td>
                          <td className="mono nowrap">{c.email}<br />{c.password}</td>
                          <td className="right"><button className="btn btn-primary btn-sm" onClick={() => open(c.email)}>Open dashboard ↗</button></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="card">
                <div className="card-head"><h2>2 · Presentation script</h2></div>
                <div className="card-body">
                  <div className="timeline">
                    {info.guide.map((step, i) => (
                      <div className="timeline-item" key={step.title}>
                        <strong>{i + 1}. {step.title}</strong>
                        <div className="muted small">{step.detail}</div>
                      </div>
                    ))}
                  </div>
                  <div className="divider" />
                  <button className="btn btn-ghost btn-sm" onClick={newDevice}>📱 Make this browser a new device</button>
                  <p className="muted small mt-8">Lets you show R4/R9 from the genuine User login too.</p>
                </div>
              </div>
            </div>

            <div className="card card-pad">
              <h2>3 · Demonstrate the nine rules</h2>
              <p className="muted mt-8">
                Log in as the Frauder and use <strong>“Test the 9 Fraud Detection Rules”</strong>. Each rule card explains the
                manual steps using the live thresholds and the victim’s real history. After every attempt the result
                screen shows all nine rules with the measured values, the risk score, the decision, the reason and
                whether any money moved.
              </p>
              <button className="btn btn-primary mt-16" onClick={() => open('frauder@demo.bank')}>Open the Frauder console ↗</button>
            </div>
          </div>
        )}
      </main>

      {confirmReset && (
        <Modal title="Reset all demo data?" onClose={() => setConfirmReset(false)} footer={<>
          <button className="btn btn-ghost" onClick={() => setConfirmReset(false)}>Cancel</button>
          <button className="btn btn-danger" disabled={resetting} onClick={resetAll}>{resetting ? 'Resetting…' : 'Yes, reset'}</button>
        </>}>
          <p>This clears all transactions, alerts, notifications and login history, restores every account to its
            opening balance, and restores default rule weights and score bands.</p>
          <p className="muted small mt-8">To undo only the Frauder’s attempts and keep genuine payments, use “Reset fraud attempts” instead.</p>
        </Modal>
      )}
    </div>
  );
}
