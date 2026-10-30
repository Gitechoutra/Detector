import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { errorMessage, get } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { Field } from '../components/ui';

const FLOW = [
  ['1', 'tone-blue', 'User', 'Sends money manually (UPI, QR, bank transfer)'],
  ['2', 'tone-purple', 'Detection System', 'Checks 9 SQL rules and scores the risk 0–100'],
  ['3', 'tone-green', 'Receiver', 'Credited only when the payment is approved'],
  ['4', 'tone-red', 'Frauder', 'Simulates fraud to test the detection system'],
];

export default function Login() {
  const { login, session } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [locationId, setLocationId] = useState('');
  const [locations, setLocations] = useState([]);
  const [error, setError] = useState(params.get('expired') ? 'Your session ended. Please log in again.' : '');
  const [busy, setBusy] = useState(false);
  const autoTried = useRef(false);

  useEffect(() => {
    get('/meta/locations').then(setLocations).catch(() => {});
  }, []);

  const submit = async (e, creds) => {
    e?.preventDefault();
    setBusy(true);
    setError('');
    try {
      const next = await login(creds?.email ?? email, creds?.password ?? password, creds ? null : locationId);
      navigate(next.dashboard, { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  // Demo Mode opens /login?as=<email> in a new tab and logs that role in.
  useEffect(() => {
    const as = params.get('as');
    if (!as || autoTried.current) return;
    autoTried.current = true;
    get('/demo/info')
      .then((info) => {
        const cred = info.credentials.find((c) => c.email === as);
        if (cred) {
          setEmail(cred.email);
          setPassword(cred.password);
          submit(null, cred);
        }
      })
      .catch((err) => setError(errorMessage(err)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  return (
    <div className="auth-page">
      <section className="auth-hero">
        <div>
          <Link to="/" className="row" style={{ marginBottom: 18, color: "var(--text)", textDecoration: "none" }}>
            <div className="brand-mark" style={{ background: '#3B82F6' }}>FS</div>
            <strong style={{ fontSize: 16 }}>FraudShield Bank</strong>
          </Link>
          <h1>Real-time fraud detection for every payment</h1>
          <p className="muted mt-8" style={{ fontSize: 15, maxWidth: 520 }}>
            Every transaction is checked against nine SQL-based fraud rules the moment it is made, scored
            from 0 to 100, and approved, held for review or blocked – with the reasons recorded.
          </p>
        </div>
        <div className="flow">
          {FLOW.map(([n, tone, title, text]) => (
            <div className="flow-step" key={n}>
              <div className={`flow-num ${tone}`}>{n}</div>
              <div><strong>{title}</strong><div className="muted small">{text}</div></div>
            </div>
          ))}
        </div>
        <div className="row wrap small">
          <span className="badge b-green">No rule → Successful</span>
          <span className="badge b-amber">Any rule → owner confirms</span>
          <span className="badge b-red">Owner says NO → Blocked</span>
        </div>
      </section>

      <section className="auth-panel">
        <div className="auth-card stack">
          <div className="demo-banner row-between wrap">
            <div>
              <strong>🎓 Viva / Demo Mode</strong>
              <div className="small muted">Guided demo, sample logins and one-click fraud scenarios.</div>
            </div>
            <Link to="/demo" className="btn btn-primary" style={{ background: '#7C3AED' }}>Open Demo Mode</Link>
          </div>

          <div className="card card-pad">
            <h2>Sign in</h2>
            <p className="muted small mt-8">One login page for all four roles – you are taken to your dashboard.</p>
            <form className="form-grid mt-16" onSubmit={submit}>
              <Field label="Email">
                <input className="input" type="email" autoComplete="username" value={email}
                       onChange={(e) => setEmail(e.target.value)} required placeholder="rahul@demo.bank" />
              </Field>
              <Field label="Password">
                <input className="input" type="password" autoComplete="current-password" value={password}
                       onChange={(e) => setPassword(e.target.value)} required />
              </Field>
              <Field label="Login location (simulated)" hint="Leave as home city. Choosing another city simulates a login from elsewhere.">
                <select className="input" value={locationId} onChange={(e) => setLocationId(e.target.value)}>
                  <option value="">My home city</option>
                  {locations.map((l) => <option key={l.id} value={l.id}>{l.city}</option>)}
                </select>
              </Field>
              {error && <div className="notice notice-danger">⚠ {error}</div>}
              <button className="btn btn-primary btn-lg btn-block" disabled={busy}>
                {busy ? 'Signing in…' : 'Sign in'}
              </button>
            </form>
          </div>
          <p className="small muted" style={{ textAlign: 'center' }}>
            New customer? <Link to="/register" style={{ fontWeight: 600 }}>Create an account</Link>
          </p>
          {session && (
            <p className="small muted" style={{ textAlign: 'center' }}>
              Already signed in as {session.user.full_name}. <Link to={session.dashboard}>Go to dashboard →</Link>
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
