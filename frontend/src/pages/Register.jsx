import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { errorMessage, get } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { useToast } from '../components/Toast';
import AuthShell from '../components/AuthShell';
import { Field } from '../components/ui';

export default function Register() {
  const { register } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const [locations, setLocations] = useState([]);
  const [locationsError, setLocationsError] = useState('');
  const [form, setForm] = useState({ full_name: '', email: '', phone: '', password: '', confirm: '', role: 'USER', location_id: '' });
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    get('/meta/locations')
      .then((list) => {
        setLocations(list);
        if (!list.length) setLocationsError('No cities are set up yet. Run `flask seed` in the backend, then reload this page.');
      })
      .catch((err) => setLocationsError(errorMessage(err)));
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
    <AuthShell wide>
      <div className="au-card">
        <h1>Open your account</h1>
        <p className="muted small mt-8">
          One account to send and receive money: you get an account number, a UPI ID, a QR code and a
          ₹50,000 simulated balance straight away. Detection and Fraudster logins are issued by the bank.
        </p>
        <form className="form-grid mt-16" onSubmit={submit}>
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
                <option value="" disabled>{locations.length ? 'Choose…' : 'Loading cities…'}</option>
                {locations.map((l) => <option key={l.id} value={l.id}>{l.city}</option>)}
              </select>
            </Field>
          </div>
          {locationsError && <div className="notice notice-warn">⚠ Could not load cities: {locationsError}</div>}
          <div className="grid grid-2" style={{ gap: 12 }}>
            <Field label="Password" hint="8+ characters, letters and numbers">
              <input className="input" type="password" value={form.password} onChange={set('password')} required minLength={8} autoComplete="new-password" />
            </Field>
            <Field label="Confirm password">
              <input className="input" type="password" value={form.confirm} onChange={set('confirm')} required autoComplete="new-password" />
            </Field>
          </div>
          {error && <div className="notice notice-danger">⚠ {error}</div>}
          <button className="btn btn-glow btn-lg btn-block" disabled={busy}>
            {busy ? 'Creating account…' : 'Create account'}
          </button>
        </form>
      </div>
      <p className="au-link">
        Already have an account? <Link to="/login">Sign in</Link>
      </p>
    </AuthShell>
  );
}
