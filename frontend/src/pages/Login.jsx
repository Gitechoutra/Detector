import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { errorMessage, get } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import AuthShell from '../components/AuthShell';
import Icon from '../components/Icon';
import { useToast } from '../components/Toast';
import { Field } from '../components/ui';
import { isRole, ROLE_INFO, roleForPath } from '../roles';

const ROLE_ICONS = { USER: 'user', DETECTION: 'radar', FRAUDER: 'mask' };

export default function Login() {
  const { login, session } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const role = isRole(params.get('role')) ? params.get('role') : '';
  const next = params.get('next') || '';
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [locationId, setLocationId] = useState('');
  const [locations, setLocations] = useState([]);
  const [error, setError] = useState(params.get('expired') ? 'Your session ended. Please log in again.' : '');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    get('/meta/locations').then(setLocations).catch(() => {});
  }, []);

  // After login: the page that was asked for if it belongs to this account's
  // role, otherwise the account's own dashboard.
  const goAfterLogin = (s) => {
    const wanted = next && roleForPath(next) === s.user.role ? next : s.dashboard;
    if (role && s.user.role !== role) {
      toast(`${s.user.full_name} is a ${ROLE_INFO[s.user.role].label} account, so you are on that dashboard.`, 'info', 'Different role');
    }
    navigate(wanted, { replace: true });
  };

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const s = await login(email.trim().toLowerCase(), password, locationId);
      goAfterLogin(s);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const pickRole = (r) => {
    const p = new URLSearchParams(params);
    p.set('role', r);
    if (roleForPath(next) !== r) p.set('next', ROLE_INFO[r].dashboard);
    p.delete('expired');
    setParams(p, { replace: true });
    setError('');
  };

  const roleLabel = role && ROLE_INFO[role].label;
  const signedInElsewhere = session && role && session.user.role !== role;

  return (
    <AuthShell>
      <div className="au-card">
        <h1>{role ? `Sign in as ${roleLabel}` : 'Welcome back'}</h1>
        <p className="muted small mt-8">
          {role
            ? `After signing in you go straight to the ${roleLabel} dashboard.`
            : 'One sign-in for every role. You are taken straight to your dashboard.'}
        </p>

        <div className="au-roles mt-16" role="tablist" aria-label="Choose a role">
          {Object.entries(ROLE_INFO).map(([key, info]) => (
            <button key={key} type="button" role="tab" aria-selected={role === key}
                    className={`r-${key}${role === key ? ' on' : ''}`} onClick={() => pickRole(key)}>
              <Icon name={ROLE_ICONS[key]} size={18} />
              {info.label.replace(' Engine', '')}
            </button>
          ))}
        </div>

        {signedInElsewhere && (
          <div className="notice notice-info mt-16">
            You are signed in as {session.user.full_name} ({ROLE_INFO[session.user.role].label}).
            Sign in with a {roleLabel} account to open its dashboard, or <Link to={session.dashboard}>go back to yours</Link>.
          </div>
        )}

        <form className="form-grid mt-16" onSubmit={submit}>
          <Field label="Email">
            <input className="input" type="email" autoComplete="username" value={email}
                   onChange={(e) => setEmail(e.target.value)} required placeholder="you@example.com" />
          </Field>
          <Field label="Password">
            <input className="input" type="password" autoComplete="current-password" value={password}
                   onChange={(e) => setPassword(e.target.value)} required placeholder="••••••••" />
          </Field>
          <Field label="Login location (simulated)" hint="Leave as home city. Choosing another city simulates a login from elsewhere.">
            <select className="input" value={locationId} onChange={(e) => setLocationId(e.target.value)}>
              <option value="">My home city</option>
              {locations.map((l) => <option key={l.id} value={l.id}>{l.city}</option>)}
            </select>
          </Field>
          {error && <div className="notice notice-danger">⚠ {error}</div>}
          <button className="btn btn-glow btn-lg btn-block" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>

      <p className="au-link">New customer? <Link to="/register">Create an account</Link></p>
      {session && !signedInElsewhere && (
        <p className="au-link">Already signed in as {session.user.full_name}. <Link to={session.dashboard}>Go to dashboard →</Link></p>
      )}
    </AuthShell>
  );
}
