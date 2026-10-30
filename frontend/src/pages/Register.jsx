import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { errorMessage, get } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { useToast } from '../components/Toast';
import { Field } from '../components/ui';

const ACCOUNT_TYPES = [
  ['USER', '💸', 'Send money', 'Pay others by UPI, QR or bank transfer. Starts with a ₹50,000 simulated balance.'],
  ['RECEIVER', '📥', 'Receive money', 'Accept payments with your UPI ID or QR code. Starts at ₹0.'],
];

export default function Register() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const [locations, setLocations] = useState([]);
  const [form, setForm] = useState({ full_name: '', email: '', phone: '', password: '', confirm: '', role: 'USER', location_id: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    get('/meta/locations').then(setLocations).catch(() => {});
  }, []);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    if (form.password !== form.confirm) {
      setError('Passwords do not match.');
      return;
    }
    setBusy(true);
    try {
      const { confirm, ...body } = form;
      const next = await register({ ...body, phone: body.phone || null });
      toast(`Your UPI ID is ${next.account.upi_id}`, 'success', 'Account created');
      navigate(next.dashboard, { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-page">
      <section className="auth-hero">
        <div>
          <Link to="/" className="row" style={{ marginBottom: 18, color: "var(--text)", textDecoration: "none" }}>
            <div className="brand-mark" style={{ background: '#3B82F6' }}>FS</div>
            <strong style={{ fontSize: 16 }}>FraudShield Bank</strong>
          </Link>
          <h1>Open your account</h1>
          <p className="muted mt-8" style={{ fontSize: 15, maxWidth: 520 }}>
            You get an account number, a UPI ID and a QR code straight away. Every payment you make or
            receive is checked by the real-time fraud detection system.
          </p>
        </div>
        <div className="notice notice-info" style={{ maxWidth: 520 }}>
          ℹ This is a simulated bank for demonstration. No real money, bank or UPI system is involved.
        </div>
      </section>

      <section className="auth-panel">
        <div className="auth-card stack">
          <div className="card card-pad">
            <h2>Create account</h2>
            <p className="muted small mt-8">Customer accounts only. Detection System and Frauder logins are issued by the bank.</p>
            <form className="form-grid mt-16" onSubmit={submit}>
              <div className="field">
                <label>Account type</label>
                <div className="grid grid-2" style={{ gap: 8 }}>
                  {ACCOUNT_TYPES.map(([value, icon, title, text]) => (
                    <label key={value} className="card" style={{
                      padding: 12, cursor: 'pointer',
                      borderColor: form.role === value ? 'var(--primary)' : undefined,
                      background: form.role === value ? 'var(--primary-light)' : undefined,
                    }}>
                      <input type="radio" name="role" value={value} checked={form.role === value} onChange={set('role')} style={{ display: 'none' }} />
                      <strong>{icon} {title}</strong>
                      <div className="muted small">{text}</div>
                    </label>
                  ))}
                </div>
              </div>
              <Field label="Full name">
                <input className="input" value={form.full_name} onChange={set('full_name')} required maxLength={100} autoComplete="name" />
              </Field>
              <Field label="Email">
                <input className="input" type="email" value={form.email} onChange={set('email')} required autoComplete="email" />
              </Field>
              <div className="grid grid-2" style={{ gap: 12 }}>
                <Field label="Mobile (optional)">
                  <input className="input" inputMode="numeric" maxLength={10} value={form.phone}
                         onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value.replace(/\D/g, '') }))} placeholder="98xxxxxxxx" />
                </Field>
                <Field label="Home city">
                  <select className="input" value={form.location_id} onChange={set('location_id')} required>
                    <option value="" disabled>Choose…</option>
                    {locations.map((l) => <option key={l.id} value={l.id}>{l.city}</option>)}
                  </select>
                </Field>
              </div>
              <div className="grid grid-2" style={{ gap: 12 }}>
                <Field label="Password" hint="8+ characters, letters and numbers">
                  <input className="input" type="password" value={form.password} onChange={set('password')} required minLength={8} autoComplete="new-password" />
                </Field>
                <Field label="Confirm password">
                  <input className="input" type="password" value={form.confirm} onChange={set('confirm')} required autoComplete="new-password" />
                </Field>
              </div>
              {error && <div className="notice notice-danger">⚠ {error}</div>}
              <button className="btn btn-primary btn-lg btn-block" disabled={busy}>
                {busy ? 'Creating account…' : 'Create account'}
              </button>
            </form>
          </div>
          <p className="small muted" style={{ textAlign: 'center' }}>
            Already have an account? <Link to="/login">Sign in</Link>
          </p>
        </div>
      </section>
    </div>
  );
}
