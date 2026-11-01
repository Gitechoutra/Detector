import { Link } from 'react-router-dom';
import Icon from './Icon';

/** Standalone, centred layout shared by the login and register pages. */
export default function AuthShell({ children, wide }) {
  return (
    <div className="au">
      <div className="au-bg" aria-hidden="true" />
      <header className="au-top">
        <Link to="/" className="au-brand">
          <span className="au-mark"><Icon name="shield" size={18} stroke={2.2} /></span>
          FraudShield <em>Bank</em>
        </Link>
        <Link to="/" className="au-back">← Back to home</Link>
      </header>
      <main className="au-main">
        <div className={`au-col${wide ? ' wide' : ''}`}>{children}</div>
      </main>
      <footer className="au-foot">Simulated bank for demonstration. No real money, bank or UPI system is involved.</footer>
    </div>
  );
}
