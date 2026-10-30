import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { RiskScore, StatusBadge } from '../components/ui';

// Default rule set, as seeded in the database (analysts can tune it live).
const RULES = [
  { code: 'R1', name: 'High amount', weight: 30, icon: '💰', text: 'Far above the customer’s normal spending (5× their 90-day average).' },
  { code: 'R2', name: 'Velocity', weight: 25, icon: '⚡', text: 'More than 5 payments in 10 minutes from one account.' },
  { code: 'R3', name: 'Impossible travel', weight: 35, icon: '✈️', text: 'Two cities 100+ km apart within 30 minutes.' },
  { code: 'R4', name: 'New device', weight: 20, icon: '📱', text: 'Over ₹25,000 from a phone or browser never seen before.' },
  { code: 'R5', name: 'Odd hour', weight: 10, icon: '🌙', text: 'Over ₹10,000 between midnight and 5 AM.' },
  { code: 'R6', name: 'Watch-listed party', weight: 50, icon: '🚫', text: 'Receiver, device or IP is on the blacklist.' },
  { code: 'R7', name: 'Structuring', weight: 15, icon: '🧩', text: 'Repeated payments just under the ₹50,000 reporting limit.' },
  { code: 'R8', name: 'Dormant account', weight: 20, icon: '💤', text: 'Big payment after 180+ days of no activity.' },
  { code: 'R9', name: 'Account takeover', weight: 45, icon: '🕵️', text: 'Payment right after failed logins, wrong OTPs or a new-device login.' },
];

const PIPELINE = [
  ['1', 'Ingest', 'Payment details are validated'],
  ['2', 'Persist', 'Saved inside a database transaction'],
  ['3', 'Evaluate', 'All 9 SQL rules run on it'],
  ['4', 'Score', 'Weights of fired rules are added (max 100)'],
  ['5', 'Decide', 'Approve, hold for review, or block'],
  ['6', 'Alert', 'Fraud team sees it within seconds'],
];

const ROLES = [
  { key: 'USER', icon: '💸', tone: 'blue', title: 'User', who: 'The customer who pays',
    points: ['Send money by UPI, QR code or bank transfer', 'See instantly if a payment is sent or held', 'Answer YES or NO when a payment is flagged'] },
  { key: 'RECEIVER', icon: '📥', tone: 'green', title: 'Receiver', who: 'The customer who gets paid',
    points: ['See every incoming payment and its status', 'Money is credited only after approval', 'Share a UPI ID or downloadable QR code'] },
  { key: 'DETECTION', icon: '🛡️', tone: 'purple', title: 'Detection System', who: 'The fraud team',
    points: ['Live monitor that refreshes every 2 seconds', 'Investigate alerts with the exact rules and evidence', 'Tune rule weights, thresholds and the watchlist'] },
  { key: 'FRAUDER', icon: '🕵️', tone: 'red', title: 'Frauder', who: 'The presenter playing the attacker',
    points: ['Manually try stolen logins, unknown devices and other cities', 'Attempt transfers from a demo victim’s account', 'See every rule, the score and why it was stopped'] },
];

const EXAMPLES = [
  { amount: '₹1,250', to: 'FreshMart Grocery', method: 'UPI', city: 'Chennai', rules: [], score: 0, status: 'COMPLETED',
    note: 'Usual phone, usual amount – sent instantly.' },
  { amount: '₹10,000', to: 'QuickCash Services', method: 'UPI', city: 'Mumbai', rules: ['R6'], score: 50, status: 'UNDER_REVIEW',
    note: 'Receiver is on the watchlist – held until the owner answers YES or NO.' },
  { amount: '₹75,000', to: 'Rohan Traders', method: 'Bank Transfer', city: 'Kolkata', rules: ['R1', 'R4', 'R9'], score: 95, status: 'BLOCKED',
    note: 'New device after a phishing login – the owner answered NO: blocked, no money left.' },
];

const SECURITY = [
  ['🔐', 'Owner authorization', 'Any flagged payment waits for its owner: YES sends it after a final balance check, NO blocks it, no answer lets it expire.'],
  ['⚛️', 'All-or-nothing payments', 'Saving, scoring and moving money happen in one database transaction. A crash halfway changes nothing.'],
  ['🔁', 'No double payments', 'Clicking “Send” twice still creates exactly one payment.'],
  ['🔗', 'Tamper-evident audit trail', 'Every rule change and decision is hash-chained. The database refuses edits and deletes.'],
  ['🔒', 'Account lockout', 'Five wrong passwords lock the account and alert the fraud team.'],
  ['🧾', 'Fully explainable', 'Every flagged payment lists which rules fired and why. No black box.'],
];

const decisionFor = (score) => (score > 0 ? 'UNDER_REVIEW' : 'COMPLETED');

function LivePaymentCard() {
  const [i, setI] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setI((x) => (x + 1) % EXAMPLES.length), 3500);
    return () => clearInterval(id);
  }, []);
  const ex = EXAMPLES[i];
  return (
    <div className="lp-live card" aria-live="polite">
      <div className="row-between">
        <span className="small muted row"><span className="live-dot" /> Payment being checked</span>
        <span className="small muted">{i + 1} / {EXAMPLES.length}</span>
      </div>
      <div key={i} className="lp-live-body">
        <div className="lp-live-amount">{ex.amount}</div>
        <div className="muted small">to <strong style={{ color: 'var(--text)' }}>{ex.to}</strong> · {ex.method} · {ex.city}</div>
        <div className="divider" />
        <div className="small muted">Rules fired</div>
        <div className="row wrap mt-8" style={{ minHeight: 26 }}>
          {ex.rules.length === 0 ? <span className="badge b-green">None</span>
            : ex.rules.map((code) => {
              const r = RULES.find((x) => x.code === code);
              return <span key={code} className="badge b-purple">{r.icon} {code} {r.name} +{r.weight}</span>;
            })}
        </div>
        <div className="row-between mt-16">
          <RiskScore score={ex.score} />
          <StatusBadge status={ex.status} />
        </div>
        <p className="small muted mt-8">{ex.note}</p>
      </div>
      <div className="lp-dots">
        {EXAMPLES.map((_, j) => (
          <button key={j} className={j === i ? 'active' : ''} onClick={() => setI(j)} aria-label={`Example ${j + 1}`} />
        ))}
      </div>
    </div>
  );
}

function ScoreCalculator() {
  const [on, setOn] = useState(new Set(['R4', 'R9']));
  const raw = useMemo(() => RULES.filter((r) => on.has(r.code)).reduce((s, r) => s + r.weight, 0), [on]);
  const score = Math.min(100, raw);
  const status = decisionFor(score);
  const toggle = (code) => setOn((s) => {
    const next = new Set(s);
    if (next.has(code)) next.delete(code); else next.add(code);
    return next;
  });
  const message = {
    COMPLETED: 'No rule fired – the money moves instantly and the receiver is credited.',
    UNDER_REVIEW: 'Flagged – nothing is debited. The owner is asked “Did you initiate this transaction?”: YES sends it, NO blocks it.',
    BLOCKED: 'Blocked – no money moved.',
  }[status];
  return (
    <div className="grid grid-main lp-calc">
      <div className="card card-pad">
        <h3>Pick the warning signs on a payment</h3>
        <p className="muted small mt-8">Tap the rules that apply. Weights shown are the system defaults.</p>
        <div className="lp-rule-toggles mt-16">
          {RULES.map((r) => (
            <button key={r.code} type="button" className={`lp-toggle ${on.has(r.code) ? 'on' : ''}`} onClick={() => toggle(r.code)} aria-pressed={on.has(r.code)}>
              <span>{r.icon}</span>
              <span style={{ flex: 1, textAlign: 'left' }}><strong>{r.code}</strong> {r.name}</span>
              <span className="lp-weight">+{r.weight}</span>
            </button>
          ))}
        </div>
        <button className="link-btn small mt-16" onClick={() => setOn(new Set())}>Clear all</button>
      </div>
      <div className="card card-pad lp-result" data-status={status}>
        <div className="small muted">Risk score</div>
        <div className="lp-score">{score}<span>/100</span></div>
        <div className="score-bar" style={{ height: 10 }}>
          <span style={{ width: `${score}%`, background: score >= 70 ? '#EF4444' : score >= 40 ? '#F59E0B' : '#22C55E', transition: 'width .3s' }} />
        </div>
        <div className="mono small muted mt-8">
          min(100, {[...on].length ? RULES.filter((r) => on.has(r.code)).map((r) => r.weight).join(' + ') : '0'}) = {score}
        </div>
        <div className="mt-16"><StatusBadge status={status} /></div>
        <p className="mt-8">{message}</p>
        <div className="lp-bands mt-16">
          <span className={status === 'COMPLETED' ? 'active' : ''}>No rule → sent</span>
          <span className={status === 'UNDER_REVIEW' ? 'active' : ''}>Any rule → owner decides</span>
        </div>
      </div>
    </div>
  );
}

export default function Landing() {
  const { session } = useAuth();
  const [menu, setMenu] = useState(false);
  const nav = [['#how', 'How it works'], ['#roles', 'Who it’s for'], ['#rules', 'Fraud rules'], ['#calculator', 'Try the score'], ['#security', 'Security']];

  return (
    <div className="lp">
      <header className="lp-nav">
        <div className="lp-wrap row-between">
          <Link to="/" className="row" style={{ color: 'var(--text)', textDecoration: 'none' }}>
            <div className="brand-mark" style={{ background: 'var(--primary)' }}>FS</div>
            <strong style={{ fontSize: 16 }}>FraudShield Bank</strong>
          </Link>
          <nav className={`lp-links ${menu ? 'open' : ''}`} onClick={() => setMenu(false)}>
            {nav.map(([href, label]) => <a key={href} href={href}>{label}</a>)}
          </nav>
          <div className="row">
            {session ? (
              <Link to={session.dashboard} className="btn btn-primary">Go to dashboard →</Link>
            ) : (
              <>
                <Link to="/login" className="btn btn-ghost lp-hide-sm">Sign in</Link>
                <Link to="/register" className="btn btn-primary">Open account</Link>
              </>
            )}
            <button className="btn btn-ghost btn-sm lp-menu" onClick={() => setMenu(!menu)} aria-label="Menu">☰</button>
          </div>
        </div>
      </header>

      <section className="lp-hero">
        <div className="lp-wrap lp-hero-grid">
          <div>
            <span className="badge b-purple">Real-time · SQL-based · Explainable</span>
            <h1 className="lp-title">Every payment checked for fraud <span>before</span> the money moves.</h1>
            <p className="lp-lead">
              FraudShield scores each transaction against nine fraud rules the instant it is made, then approves it,
              holds it for verification or blocks it, and tells you exactly why.
            </p>
            <div className="row wrap mt-24">
              {session
                ? <Link to={session.dashboard} className="btn btn-primary btn-lg">Go to my dashboard</Link>
                : <Link to="/register" className="btn btn-primary btn-lg">Create free account</Link>}
              <Link to="/demo" className="btn btn-lg lp-btn-demo">🎓 Try Demo Mode</Link>
            </div>
            {!session && <p className="small muted mt-16">Already a customer? <Link to="/login">Sign in</Link></p>}
            <div className="lp-stats">
              <div><strong>9</strong><span>fraud rules</span></div>
              <div><strong>&lt; 100 ms</strong><span>per decision</span></div>
              <div><strong>0–100</strong><span>explainable score</span></div>
              <div><strong>4</strong><span>role dashboards</span></div>
            </div>
          </div>
          <LivePaymentCard />
        </div>
      </section>

      <section id="how" className="lp-section">
        <div className="lp-wrap">
          <div className="lp-head">
            <span className="lp-eyebrow">How it works</span>
            <h2>From “Send” to decision in under a second</h2>
            <p>Six steps run for every payment. Steps 2–5 happen in a single database transaction, so a payment is never saved without its decision and evidence.</p>
          </div>
          <div className="lp-pipeline">
            {PIPELINE.map(([n, title, text]) => (
              <div key={n} className="lp-step">
                <div className="lp-step-num">{n}</div>
                <strong>{title}</strong>
                <span className="small muted">{text}</span>
              </div>
            ))}
          </div>
          <div className="grid grid-3 mt-24">
            <div className="lp-outcome tone-green"><strong>✓ Successful</strong><span>No rule fired, or the owner answered YES. Sender debited, receiver credited.</span></div>
            <div className="lp-outcome tone-amber"><strong>🔐 Confirmation pending</strong><span>Any rule fired. Held, nothing debited, until the owner answers.</span></div>
            <div className="lp-outcome tone-red"><strong>⛔ Blocked</strong><span>The owner answered NO. No money moved; fraud team alerted.</span></div>
          </div>
        </div>
      </section>

      <section id="roles" className="lp-section lp-alt">
        <div className="lp-wrap">
          <div className="lp-head">
            <span className="lp-eyebrow">Who it’s for</span>
            <h2>Four roles, one shared truth</h2>
            <p>Each role has its own dashboard. A payment made by the User shows up for the Receiver and the Detection System at the same moment.</p>
          </div>
          <div className="grid grid-4">
            {ROLES.map((r) => (
              <div key={r.key} className={`card card-pad lp-role role-${r.key}`}>
                <div className={`stat-icon tone-${r.tone}`}>{r.icon}</div>
                <h3 className="mt-16">{r.title}</h3>
                <div className="small muted">{r.who}</div>
                <ul>
                  {r.points.map((p) => <li key={p}>{p}</li>)}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="rules" className="lp-section">
        <div className="lp-wrap">
          <div className="lp-head">
            <span className="lp-eyebrow">The detection engine</span>
            <h2>Nine rules that catch real fraud patterns</h2>
            <p>Each rule is a SQL query running inside MySQL. Thresholds and weights live in a table, so the fraud team can tune them without touching code.</p>
          </div>
          <div className="grid grid-3">
            {RULES.map((r) => (
              <div key={r.code} className="card lp-rule">
                <div className="row-between">
                  <div className="row"><span className="lp-rule-icon">{r.icon}</span><strong>{r.name}</strong></div>
                  <span className="rule-chip">{r.code}</span>
                </div>
                <p className="small muted mt-8">{r.text}</p>
                <div className="small mt-8"><span className="muted">Weight</span> <strong>+{r.weight}</strong></div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="calculator" className="lp-section lp-alt">
        <div className="lp-wrap">
          <div className="lp-head">
            <span className="lp-eyebrow">Try it yourself</span>
            <h2>See how a risk score is built</h2>
            <p>Risk = min(100, sum of the weights of every rule that fires). Toggle rules to watch the decision change.</p>
          </div>
          <ScoreCalculator />
        </div>
      </section>

      <section id="security" className="lp-section">
        <div className="lp-wrap">
          <div className="lp-head">
            <span className="lp-eyebrow">Built to be trusted</span>
            <h2>Security beyond the rules</h2>
          </div>
          <div className="grid grid-3">
            {SECURITY.map(([icon, title, text]) => (
              <div key={title} className="lp-feature">
                <div className="lp-feature-icon">{icon}</div>
                <div><strong>{title}</strong><p className="small muted mt-8">{text}</p></div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="lp-section">
        <div className="lp-wrap">
          <div className="lp-cta">
            <div>
              <h2>Ready to see it catch fraud?</h2>
              <p>Open Demo Mode for one-click logins and a step-by-step presentation guide. Or create your own account and send a payment.</p>
            </div>
            <div className="row wrap">
              <Link to="/demo" className="btn btn-lg lp-btn-light">🎓 Open Demo Mode</Link>
              {!session && <Link to="/register" className="btn btn-lg lp-btn-outline">Create account</Link>}
            </div>
          </div>
        </div>
      </section>

      <footer className="lp-footer">
        <div className="lp-wrap row-between wrap">
          <div className="row"><div className="brand-mark" style={{ background: 'var(--primary)', width: 28, height: 28, fontSize: 12 }}>FS</div>
            <span className="small">FraudShield · SQL-Based Real-Time Fraud Detection and Transaction Monitoring System</span></div>
          <span className="small muted">Simulated banking environment. No real money, bank or UPI system is used.</span>
        </div>
      </footer>
    </div>
  );
}
