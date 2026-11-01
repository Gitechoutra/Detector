import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import Icon from '../components/Icon';
import { dashboardHref, ROLE_INFO } from '../roles';
import { moneyShort } from '../utils/format';

const NAV = [['home', 'Home'], ['how', 'How It Works'], ['features', 'Features'], ['security', 'Security'], ['roles', 'User Roles']];

// Default rule set as seeded in the database (analysts can tune it live).
const RULES = [
  ['R1', 'High amount', 30], ['R2', 'Velocity', 25], ['R3', 'Impossible travel', 35],
  ['R4', 'New device', 20], ['R5', 'Odd hour', 10], ['R6', 'Watch-listed party', 50],
  ['R7', 'Structuring', 15], ['R8', 'Dormant account', 20], ['R9', 'Account takeover', 45],
];

const FEED = [
  { to: 'FreshMart Grocery', amount: 1250, method: 'UPI', city: 'Chennai', rules: [], score: 0, outcome: 'ok' },
  { to: 'QuickCash Services', amount: 10000, method: 'UPI', city: 'Mumbai', rules: ['R6'], score: 50, outcome: 'held' },
  { to: 'Metro Rail', amount: 120, method: 'QR', city: 'Bengaluru', rules: [], score: 0, outcome: 'ok' },
  { to: 'Rohan Traders', amount: 75000, method: 'Bank transfer', city: 'Kolkata', rules: ['R1', 'R4', 'R9'], score: 95, outcome: 'blocked' },
  { to: 'Priya Patel', amount: 4500, method: 'UPI', city: 'Delhi', rules: [], score: 0, outcome: 'ok' },
  { to: 'Anil Kumar', amount: 49500, method: 'Bank transfer', city: 'Jaipur', rules: ['R7'], score: 15, outcome: 'ok' },
  { to: 'City Pharmacy', amount: 840, method: 'QR', city: 'Pune', rules: [], score: 0, outcome: 'ok' },
  { to: 'Unknown merchant', amount: 32000, method: 'UPI', city: 'Delhi', rules: ['R3', 'R4'], score: 55, outcome: 'held' },
];
const OUTCOME = { ok: 'Approved automatically', held: 'Held · owner confirms', blocked: 'Blocked automatically' };

const STEPS = [
  ['send', 'User initiates a payment', 'By UPI ID, QR code or bank transfer, from their own dashboard.'],
  ['radar', 'Detection Engine analyzes it', 'All nine SQL rules run against the payment inside one database transaction.'],
  ['gauge', 'Risk score 0–100', 'The weights of every rule that fires are added up and capped at 100.'],
  ['inbox', 'The payee is credited', 'Approved payments land straight in the receiving customer’s account.'],
  ['pause', 'Decided instantly by the score', 'Low scores are approved and high scores blocked in milliseconds; the middle band waits for the owner.'],
  ['mask', 'Fraudster activity is monitored', 'Stolen logins, new devices and odd cities are recorded as evidence.'],
];

const FEATURES = [
  ['zap', 'Real-Time Fraud Detection', 'Every payment is checked the moment it is made, in well under a second.'],
  ['database', 'SQL-Based Fraud Rules', 'Nine rules written as SQL queries, tunable from a table without code changes.'],
  ['gauge', 'Risk Score Calculation', 'A transparent 0–100 score built from the weights of the rules that fired.'],
  ['activity', 'Transaction Monitoring', 'A live monitor that refreshes every two seconds for the fraud team.'],
  ['bell', 'Suspicious Activity Alerts', 'Flagged payments raise alerts with the exact evidence attached.'],
  ['shieldCheck', 'Payment Protection', 'Held payments never leave the account until the owner says YES.'],
  ['search', 'Fraud Investigation', 'Drill into any payment: rules fired, device, city, IP and history.'],
  ['history', 'Transaction History', 'Full, filterable history for senders, receivers and analysts.'],
];

const ROLES = [
  { key: 'USER', icon: 'user', tone: 'blue', who: 'The customer – sends and receives', demo: 'rahul@demo.bank',
    points: ['Send money by UPI, QR or bank transfer', 'Receive money with a UPI ID or QR code', 'Track payment status', 'Full sent and received history'] },
  { key: 'DETECTION', icon: 'radar', tone: 'violet', who: 'The fraud team', demo: 'analyst@demo.bank',
    points: ['Monitor incoming transactions', 'Analyze SQL fraud rules', 'Calculate risk scores', 'Approve, hold or block payments'] },
  { key: 'FRAUDER', icon: 'mask', tone: 'rose', who: 'The presenter playing the attacker', demo: 'frauder@demo.bank',
    points: ['Access the fraudster demo dashboard', 'View simulated suspicious activity', 'Demonstrate fraud scenarios'] },
];

const SECURITY = [
  ['database', 'Nine SQL fraud detection rules', 'Amount, velocity, travel, device, hour, watchlist, structuring, dormancy and takeover.'],
  ['gauge', 'Risk-based evaluation', 'Each payment gets a score, so the response matches the risk.'],
  ['search', 'Suspicious transaction identification', 'Every flag lists the rules that fired and why. No black box.'],
  ['shieldCheck', 'Payment approval and blocking', 'Owner says YES and the payment goes through; NO and it is blocked.'],
  ['link', 'Transaction audit records', 'Decisions and rule changes are hash-chained and cannot be edited.'],
];

/** Adds `.in` to every `.reveal` inside the page once it scrolls into view. */
function useReveal(rootRef) {
  useEffect(() => {
    const els = rootRef.current?.querySelectorAll('.reveal') || [];
    if (!('IntersectionObserver' in window)) {
      els.forEach((el) => el.classList.add('in'));
      return undefined;
    }
    const io = new IntersectionObserver((entries) => entries.forEach((e) => {
      if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
    }), { threshold: 0.15, rootMargin: '0px 0px -40px 0px' });
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [rootRef]);
}

/** Section id currently under the sticky nav, for highlighting its link. */
function useActiveSection() {
  const [active, setActive] = useState('home');
  useEffect(() => {
    const onScroll = () => {
      let current = 'home';
      NAV.forEach(([id]) => {
        const el = document.getElementById(id);
        if (el && el.getBoundingClientRect().top <= 120) current = id;
      });
      setActive(current);
    };
    onScroll();
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);
  return active;
}

function CountUp({ to, suffix = '', ms = 1200 }) {
  const ref = useRef(null);
  const [value, setValue] = useState(0);
  useEffect(() => {
    let raf;
    const run = () => {
      const t0 = performance.now();
      const tick = (t) => {
        const p = Math.min(1, (t - t0) / ms);
        setValue(Math.round(to * (1 - (1 - p) ** 3)));
        if (p < 1) raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
    };
    if (!('IntersectionObserver' in window)) { setValue(to); return undefined; }
    const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { run(); io.disconnect(); } });
    if (ref.current) io.observe(ref.current);
    return () => { io.disconnect(); cancelAnimationFrame(raf); };
  }, [to, ms]);
  return <span ref={ref}>{value.toLocaleString('en-IN')}{suffix}</span>;
}

function ScoreRing({ score, outcome }) {
  const r = 46;
  const c = 2 * Math.PI * r;
  return (
    <div className={`fx-ring is-${outcome}`}>
      <svg viewBox="0 0 110 110">
        <circle cx="55" cy="55" r={r} className="fx-ring-track" />
        <circle cx="55" cy="55" r={r} className="fx-ring-value"
                style={{ strokeDasharray: c, strokeDashoffset: c * (1 - Math.max(score, 2) / 100) }} />
      </svg>
      <div className="fx-ring-label"><strong>{score}</strong><span>risk</span></div>
    </div>
  );
}

function DashboardPreview() {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 2400);
    return () => clearInterval(id);
  }, []);
  const rows = Array.from({ length: 5 }, (_, n) => ({ ...FEED[(tick - n + FEED.length * 100) % FEED.length], id: tick - n }));
  const latest = rows[0];
  const checked = 1284 + tick;
  const held = 37 + rows.filter((r) => r.outcome === 'held').length;
  const blocked = 9 + (latest.outcome === 'blocked' ? 1 : 0);

  return (
    <div className="fx-preview" aria-label="Animated preview of the detection dashboard">
      <div className="fx-preview-bar">
        <span /><span /><span />
        <div className="fx-preview-url">fraudshield.bank/detection/monitor</div>
        <div className="fx-live"><i /> Live</div>
      </div>
      <div className="fx-preview-body">
        <div className="fx-kpis">
          <div><span>Checked today</span><strong>{checked.toLocaleString('en-IN')}</strong></div>
          <div><span>Held for owner</span><strong className="t-amber">{held}</strong></div>
          <div><span>Blocked</span><strong className="t-rose">{blocked}</strong></div>
        </div>
        <div className="fx-preview-main">
          <div className="fx-feed">
            <div className="fx-feed-head"><span>Payment</span><span>Score</span><span>Decision</span></div>
            {rows.map((r, n) => (
              <div key={r.id} className={`fx-feed-row${n === 0 ? ' is-new' : ''}`}>
                <div>
                  <strong>{moneyShort(r.amount)}</strong>
                  <span>{r.to} · {r.method}</span>
                </div>
                <div className="fx-feed-score"><i style={{ width: `${Math.max(r.score, 4)}%` }} className={`is-${r.outcome}`} />{r.score}</div>
                <span className={`fx-pill is-${r.outcome}`}>{r.outcome === 'ok' ? 'Approved' : r.outcome === 'held' ? 'Held' : 'Blocked'}</span>
              </div>
            ))}
          </div>
          <div className="fx-inspect" key={latest.id}>
            <span className="fx-inspect-label">Latest decision</span>
            <ScoreRing score={latest.score} outcome={latest.outcome} />
            <strong className={`fx-verdict is-${latest.outcome}`}>{OUTCOME[latest.outcome]}</strong>
            <div className="fx-inspect-rules">
              {latest.rules.length
                ? latest.rules.map((code) => <span key={code}>{code} {RULES.find((x) => x[0] === code)[1]}</span>)
                : <span className="clean">No rule fired</span>}
            </div>
            <small>{latest.city} · {latest.method}</small>
          </div>
        </div>
      </div>
    </div>
  );
}

function SectionHead({ eyebrow, title, text, light }) {
  return (
    <div className={`fx-head reveal${light ? ' on-dark' : ''}`}>
      <span className="fx-eyebrow">{eyebrow}</span>
      <h2>{title}</h2>
      {text && <p>{text}</p>}
    </div>
  );
}

export default function Landing() {
  const { session } = useAuth();
  const [menu, setMenu] = useState(false);
  const rootRef = useRef(null);
  const active = useActiveSection();
  useReveal(rootRef);

  useEffect(() => {
    const html = document.documentElement;
    const before = html.style.scrollBehavior;
    html.style.scrollBehavior = 'smooth';
    return () => { html.style.scrollBehavior = before; };
  }, []);

  const start = session ? session.dashboard : '/register';
  const startLabel = session ? 'Go to my dashboard' : 'Get Started';

  return (
    <div className="fx" ref={rootRef}>
      <header className="fx-nav">
        <div className="fx-wrap fx-nav-inner">
          <a href="#home" className="fx-brand" onClick={() => setMenu(false)}>
            <span className="fx-mark"><Icon name="shield" size={18} stroke={2.2} /></span>
            FraudShield <em>Bank</em>
          </a>
          <nav className={`fx-links${menu ? ' open' : ''}`}>
            {NAV.map(([id, label]) => (
              <a key={id} href={`#${id}`} className={active === id ? 'active' : ''} onClick={() => setMenu(false)}>{label}</a>
            ))}
            <div className="fx-links-cta">
              {session
                ? <Link to={session.dashboard} className="fx-btn fx-btn-primary">Dashboard</Link>
                : <><Link to="/login" className="fx-btn fx-btn-ghost">Login</Link><Link to="/register" className="fx-btn fx-btn-primary">Get Started</Link></>}
            </div>
          </nav>
          <div className="fx-nav-cta">
            {session ? (
              <Link to={session.dashboard} className="fx-btn fx-btn-primary">Dashboard <Icon name="arrowRight" size={16} /></Link>
            ) : (
              <>
                <Link to="/login" className="fx-btn fx-btn-ghost">Login</Link>
                <Link to="/register" className="fx-btn fx-btn-primary">Get Started</Link>
              </>
            )}
          </div>
          <button className="fx-burger" onClick={() => setMenu((m) => !m)} aria-label="Toggle menu" aria-expanded={menu}>
            <Icon name={menu ? 'x' : 'menu'} />
          </button>
        </div>
      </header>

      {/* Hero */}
      <section id="home" className="fx-hero">
        <div className="fx-hero-bg" aria-hidden="true" />
        <div className="fx-wrap fx-hero-grid">
          <div className="fx-hero-copy">
            <span className="fx-chip reveal"><i /> Real-time · SQL-based · Explainable</span>
            <h1 className="reveal">Stop Fraud <span>Before the Money Moves.</span></h1>
            <p className="reveal">
              An intelligent payment monitoring system that detects suspicious transactions, prevents fraud,
              and protects every payment in real time.
            </p>
            <div className="fx-hero-actions reveal">
              <Link to={start} className="fx-btn fx-btn-primary fx-btn-lg">{startLabel} <Icon name="arrowRight" size={18} /></Link>
              <a href="#how" className="fx-btn fx-btn-glass fx-btn-lg"><Icon name="play" size={14} /> Explore How It Works</a>
            </div>
            <div className="fx-stats reveal">
              <div><strong><CountUp to={9} /></strong><span>SQL fraud rules</span></div>
              <div><strong>&lt;<CountUp to={100} />ms</strong><span>per decision</span></div>
              <div><strong>0–<CountUp to={100} /></strong><span>explainable score</span></div>
              <div><strong><CountUp to={3} /></strong><span>role dashboards</span></div>
            </div>
          </div>
          <div className="reveal fx-hero-visual"><DashboardPreview /></div>
        </div>
      </section>

      {/* How it works */}
      <section id="how" className="fx-section">
        <div className="fx-wrap">
          <SectionHead eyebrow="How FraudShield works" title="From “Send” to a decision in under a second"
                       text="Every payment follows the same six steps. Saving, scoring and moving money happen in one database transaction, so a payment is never left half-done." />
          <ol className="fx-timeline">
            {STEPS.map(([icon, title, text], n) => (
              <li key={title} className="reveal" style={{ '--i': n }}>
                <div className="fx-step-icon"><Icon name={icon} size={22} /><span>{n + 1}</span></div>
                <h3>{title}</h3>
                <p>{text}</p>
              </li>
            ))}
          </ol>
          <div className="fx-outcomes reveal">
            <div className="is-ok"><Icon name="check" size={18} /><div><strong>Score 0–39</strong><span>Approved instantly, receiver credited</span></div></div>
            <div className="is-held"><Icon name="pause" size={18} /><div><strong>Score 40–69</strong><span>Held until the owner says YES or NO</span></div></div>
            <div className="is-blocked"><Icon name="x" size={18} /><div><strong>Score 70–100</strong><span>Blocked instantly, no money moves</span></div></div>
          </div>
        </div>
      </section>

      {/* Features */}
      <section id="features" className="fx-section fx-alt">
        <div className="fx-wrap">
          <SectionHead eyebrow="Platform features" title="Everything a fraud team needs, in one place"
                       text="Built around a transparent rule engine, so every decision can be explained to the customer and the examiner." />
          <div className="fx-features">
            {FEATURES.map(([icon, title, text], n) => (
              <article key={title} className="fx-feature reveal" style={{ '--i': n % 4 }}>
                <div className="fx-feature-icon"><Icon name={icon} size={22} /></div>
                <h3>{title}</h3>
                <p>{text}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      {/* Security */}
      <section id="security" className="fx-section fx-dark">
        <div className="fx-wrap fx-sec-grid">
          <div>
            <SectionHead light eyebrow="Security and protection" title="Every payment is judged on evidence"
                         text="Nine SQL rules weigh each payment. The score decides whether money moves, waits for its owner, or stops." />
            <ul className="fx-sec-list">
              {SECURITY.map(([icon, title, text], n) => (
                <li key={title} className="reveal" style={{ '--i': n }}>
                  <span><Icon name={icon} size={20} /></span>
                  <div><strong>{title}</strong><p>{text}</p></div>
                </li>
              ))}
            </ul>
          </div>
          <div className="fx-console reveal">
            <div className="fx-console-head"><Icon name="database" size={16} /> fraud_rules <span>9 active</span></div>
            {RULES.map(([code, name, weight], n) => (
              <div key={code} className="fx-console-row" style={{ '--i': n }}>
                <code>{code}</code>
                <span>{name}</span>
                <div className="fx-console-bar"><i style={{ '--w': `${weight * 2}%` }} /></div>
                <b>+{weight}</b>
              </div>
            ))}
            <div className="fx-console-foot">risk = min(100, Σ weights of fired rules)</div>
          </div>
        </div>
      </section>

      {/* Roles */}
      <section id="roles" className="fx-section">
        <div className="fx-wrap">
          <SectionHead eyebrow="User roles and dashboards" title="Three roles, three dashboards, one shared truth"
                       text="Pick a role to open its dashboard. If you are not signed in as that role, you will sign in first and land right on it." />
          <div className="fx-roles">
            {ROLES.map((r, n) => {
              const info = ROLE_INFO[r.key];
              const signedIn = session?.user?.role === r.key;
              return (
                <Link key={r.key} to={dashboardHref(session, r.key)} className={`fx-role fx-tone-${r.tone} reveal`} style={{ '--i': n }}>
                  <div className="fx-role-top">
                    <span className="fx-role-icon"><Icon name={r.icon} size={24} /></span>
                    <span className="fx-role-path">{info.dashboard}</span>
                  </div>
                  <h3>{info.label}</h3>
                  <span className="fx-role-who">{r.who}</span>
                  <ul>{r.points.map((p) => <li key={p}><Icon name="check" size={15} stroke={2.4} /> {p}</li>)}</ul>
                  <div className="fx-role-foot">
                    <span>{signedIn ? 'Open dashboard' : 'Sign in & open dashboard'}</span>
                    <Icon name="arrowRight" size={18} />
                  </div>
                  {!signedIn && <small className="fx-role-demo">Demo: {r.demo}</small>}
                </Link>
              );
            })}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="fx-section fx-cta-wrap">
        <div className="fx-wrap">
          <div className="fx-cta reveal">
            <div>
              <h2>Every Transaction Deserves Protection.</h2>
              <p>Experience smarter payment security with FraudShield Bank.</p>
            </div>
            <div className="fx-cta-actions">
              {session
                ? <Link to={session.dashboard} className="fx-btn fx-btn-white fx-btn-lg">Explore Dashboard</Link>
                : <a href="#roles" className="fx-btn fx-btn-white fx-btn-lg">Explore Dashboard</a>}
              <Link to={start} className="fx-btn fx-btn-outline fx-btn-lg">{startLabel} <Icon name="arrowRight" size={18} /></Link>
            </div>
          </div>
        </div>
      </section>

      <footer className="fx-footer">
        <div className="fx-wrap fx-footer-grid">
          <div>
            <a href="#home" className="fx-brand"><span className="fx-mark"><Icon name="shield" size={18} stroke={2.2} /></span>FraudShield <em>Bank</em></a>
            <p>SQL-based real-time fraud detection and transaction monitoring. A simulated bank: no real money, bank or UPI system is involved.</p>
            <Link to="/demo" className="fx-footer-demo"><Icon name="sparkles" size={16} /> Viva / Demo Mode</Link>
          </div>
          <div>
            <h4>Navigate</h4>
            {NAV.map(([id, label]) => <a key={id} href={`#${id}`}>{label}</a>)}
            <Link to="/login">Login</Link>
          </div>
          <div>
            <h4>Platform</h4>
            {FEATURES.slice(0, 5).map(([, title]) => <a key={title} href="#features">{title}</a>)}
          </div>
          <div>
            <h4>User roles</h4>
            {ROLES.map((r) => <Link key={r.key} to={dashboardHref(session, r.key)}>{ROLE_INFO[r.key].label} dashboard</Link>)}
            <Link to="/register">Open an account</Link>
          </div>
        </div>
        <div className="fx-wrap fx-copy">
          <span>© {new Date().getFullYear()} FraudShield Bank. Academic demonstration project.</span>
          <span>Made with MySQL, Flask and React</span>
        </div>
      </footer>
    </div>
  );
}
