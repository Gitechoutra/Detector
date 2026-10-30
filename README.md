# FraudShield – SQL-Based Real-Time Fraud Detection and Transaction Monitoring System

Every payment is checked against nine SQL fraud rules the moment it is made. Each fired rule adds its
weight to a risk score, `Risk = min(100, Σ weights)`, which decides the outcome:

| Score  | Decision | What happens |
|--------|----------|--------------|
| 0–39   | APPROVED | Money moves immediately; the receiver is credited |
| 40–69  | REVIEW   | Payment held (nothing debited); customer step-up verification; medium alert |
| 70–100 | BLOCKED  | Payment declined; high alert |

All payments are simulated. Nothing connects to a real bank, UPI, SMS or payment system.

**Stack:** React 18 + JavaScript + CSS (Vite) · Python 3 / Flask (Blueprints, JWT) · MySQL 8 (InnoDB) ·
Flask-Migrate / Alembic.

---

## 1. Quick start

Prerequisites: Python 3.11+, Node 18+, MySQL 8.

```bash
# 1. Create the database (once)
mysql -u root -p -e "CREATE DATABASE bank CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# 2. Backend
cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # macOS/Linux: cp .env.example .env  – then edit it
flask db upgrade                # creates all tables + seeds roles, demo logins, rules, settings
python app.py                   # http://127.0.0.1:5000

# 3. Frontend (new terminal)
cd frontend
npm install
npm run dev                     # http://localhost:5173
```

Open **http://localhost:5173**. Use **Open Demo Mode** on the login page for the guided viva demo.

### `.env`

| Key | Purpose |
|-----|---------|
| `DATABASE_URL` | `mysql+pymysql://root:<password>@localhost:3306/bank?charset=utf8mb4` |
| `SECRET_KEY`, `JWT_SECRET_KEY` | Long random strings: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `JWT_ACCESS_MINUTES` | Login session length (default 480) |
| `CORS_ORIGINS` | Frontend origin(s) |
| `DEMO_MODE_ENABLED` | `true` for the viva. It exposes demo credentials and the reset buttons without login, so set it to `false` anywhere else |

No password or secret is written in the source code; everything comes from `.env`.

---

## 2. Demo credentials

| Role | Email | Password | Notes |
|------|-------|----------|-------|
| User | rahul@demo.bank | Rahul@123 | ₹2,50,000 · Mumbai · UPI `rahul@fsbank` |
| User | karan@demo.bank | Karan@123 | ₹1,50,000 · Delhi |
| Receiver | priya@demo.bank | Priya@123 | UPI `priya@fsbank` |
| Receiver | amit@demo.bank | Amit@123 | UPI `amit@fsbank` |
| Receiver (watch-listed) | quickcash@demo.bank | Quick@123 | Paying `quickcash@fsbank` fires R6 |
| Detection System | analyst@demo.bank | Detect@123 | Fraud team dashboard |
| Frauder | frauder@demo.bank | Fraud@123 | Manual attacker console |
| User (dormant demo) | suresh@demo.bank | Suresh@123 | Designated dormant account for R8 |

Each **browser tab** keeps its own login (sessionStorage), so you can have User, Receiver and Detection
open side by side.

**New customers** can sign up from **Create an account** on the login page (`/register`):
- Choose User (send money) or Receiver (receive money).
- Each new customer gets an account number, a UPI ID (from the email, e.g. `sita@fsbank`) and a QR code.
- A new User starts with a simulated ₹50,000 balance (`NEW_USER_OPENING_BALANCE` in `system_settings`).
  A new Receiver starts at ₹0.
- Detection System and Frauder accounts cannot be self-registered; they are staff accounts created by the
  seeders.

---

## 3. The four roles

**User (manual).** Sends money by UPI ID, QR code (upload the receiver's QR image or paste its data) or
bank transfer (account number + IFSC). Sees balance, history, status and the rules that flagged a payment.
For REVIEW payments the user verifies with a simulated SMS OTP plus their password. The backend then
**re-runs every rule**:
- Only identity rules (R4 new device, R9 account takeover) can be cleared by verification.
- Behavioural rules (amount, velocity, travel, watchlist, structuring, dormant, odd hour) still count.
- If the new score is below 40 the payment is released. If it is still 40–69 it goes to a fraud analyst.
  If it is 70 or more it is blocked.
- Three wrong OTP/password attempts decline the payment.

**Receiver (manual).** Sees incoming payments, sender, amount and status. Only approved payments are credited.
Under-review and blocked payments are shown as *not credited*. The receiver can also show and download their
QR code.

**Detection System (automatic engine + analyst screens).**
- **Overview:** KPIs, charts, recent suspicious activity, precision/recall/F1/FPR and latency.
- **Live monitor:** refreshes every 2 s, with filters for date, status, risk level, user and source.
- **Investigation view:** every assessment, the rules fired with evidence, logins and security events.
  Approve or reject from here. An approval is refused if the re-evaluation now scores BLOCKED.
- **Alerts & cases:** assign, add notes, close as confirmed fraud or false positive.
- **Rule console:** enable or disable rules, change weights, thresholds and score bands. Every change is audited.
- **Watchlist**, plus **security events / login attempts / audit trail** with hash-chain verification.

**Frauder (manual attacker console).** There is no automatic or random fraud generation. The presenter plays
the attacker by hand on designated demo victim accounts, and the SQL engine decides every outcome.

- **Victims:** Rahul (main), Karan, and Suresh, the dormant demo account (opened ~400 days ago, never used,
  for R8).
- **Receivers:** Priya, Amit, and the watch-listed QuickCash.
- **Attack details form (typed by hand, nothing auto-filled):** target user account, receiver account, amount,
  fraud scenario, and the SIMULATED attacker details:
  - target city (typed or picked; it must be a known city because R3 needs its coordinates)
  - target location (free text)
  - device type and device ID; the same device ID means the same attacker device
  - IP address (validated)
  - optionally "use the victim's registered device" (remote-access scam), plus a demo clock for R5
  - No geolocation, random IPs or default city. **Clear form** empties every field.
- **What happens to these values:** they are stored with the attempt in `transactions.simulated_details`, marked
  `"source": "SIMULATED", "verified": false`, and used as rule inputs (city → R3, device → R4/R9, IP → R6).
  They are never written to the victim's profile.
- **Login attempts** (they use the same city, device and IP): "Wrong password", "Log in with stolen password",
  "Wrong OTP". Passwords are never shown or typed. Five wrong passwords lock the account for 15 minutes.
- **Result screen:**
  - all nine rules with *Triggered / Not triggered*, the measured value and the configured threshold
  - the score formula (`min(100, …)`), the decision and a plain-language reason
  - the sender's and receiver's balances before and after
  - a timeline: suspicious activity → submitted → rules evaluated → rules triggered → score → decision →
    alert → money moved or not
- **Test the 9 Fraud Detection Rules:** one card per rule.
  - The hint is built from the live thresholds and the victim's real history, e.g. *"Rahul's average over
    his last 3 payments is ₹1,000, so R1 fires above ₹5,000."*
  - Hints are text only and never fill the form.
- **Attempt history** lists every login, OTP and transfer. Click a transfer to reopen its full detection result.
- **Limits on the Frauder:**
  - It can act only on the designated demo accounts.
  - It cannot change balances, approve payments, edit rules, or use the normal payment API.
  - Every transfer goes through `send_money`: locked rows, a single commit, and idempotency (pressing Send
    twice never pays twice).
- **Outcomes:**
  - Approved attempts really debit and credit.
  - Blocked attempts move nothing.
  - Held attempts ask the owner for a confirmation (see below).
- **Reset fraud attempts** (Frauder, Detection System or Demo Mode) reverses exactly the money Frauder
  transfers moved and removes their records. Genuine payments are kept, and Suresh stays dormant.

| Rule | What you do in the Frauder console (default thresholds) | Result on its own |
|------|---------------------------------------------------------|-------------------|
| R1 | Send > 5× the victim's 90-day average (or ≥ ₹1,00,000 if < 3 past payments) from the victim's own device | R1 (30) → Approved |
| R2 | Press Send 6+ times within 10 minutes | R2 (25) → Approved |
| R3 | Send from Mumbai, then within 30 min from Delhi | R3 (35) → Approved |
| R4 | A device ID never used before, amount > ₹25,000 | R4 (20) → Approved |
| R5 | Demo clock 02:30, amount > ₹10,000 | R5 (10) → Approved |
| R6 | Receiver QuickCash (watch-listed) | R6 (50) → **Review** |
| R7 | Three payments of ₹45,000–₹49,999 within 24 h | R7 (15) → Approved |
| R8 | Victim Suresh (dormant), amount ≥ ₹25,000 | R8 (20) → Approved |
| R9 | Stolen-password login (or 3 × wrong password) with a new device ID, then send ≥ ₹5,000 with that device ID | R9 (45) → **Review** |

Rules combine. For example, 3 wrong passwords plus a stolen login, then ₹80,000 to QuickCash from that
device, fires R4 + R6 + R9 (+ R1) = 100 → **Blocked**, with no money moved. Attempts on the same account also
carry over: a burst of payments adds R2, and a change of city adds R3. Use **Reset fraud attempts** between
rules to show each one on its own.

**Account-owner confirmation ("Was this transaction initiated by you?").** Every payment the engine scores
Review (40–69) opens a confirmation request for its owner.

- **The alert:** it appears prominently on the User dashboard with the amount, receiver, transaction ID, date
  and time, device and IP, location and the reason it was flagged. It has two buttons:
  **YES, IT WAS ME** and **NO, NOT ME**.
- **NO:** the payment is BLOCKED at once with *"Transaction blocked because the account owner denied initiating
  this payment."* No money moves. A HIGH `USER_DENIED` alert is raised and the attacker device is watch-listed.
  The Frauder sees **USER DENIED – BLOCKED**.
- **YES:** this never approves on its own.
  - The owner verifies with an OTP and their password, then every rule is re-evaluated.
  - Only the identity rules (R4, R9) are cleared by the verification.
  - If the payment now scores Approved, money moves (**USER CONFIRMED – SUCCESSFUL**).
  - If it still scores Review, it goes to a fraud analyst.
  - If a hard-block rule still fires (default R6, a watch-listed receiver), it stays **BLOCKED**.
- **Safeguards:**
  - The answer is validated on the server. Only the logged-in owner can answer (anyone else gets 404, other
    roles 403).
  - The transaction row is locked, so only the first answer counts; a repeat gets 409.
  - Answers after expiry are rejected (410).
- **Expiry:** unanswered requests expire after `CONFIRMATION_EXPIRY_MINUTES` (30). `CONFIRMATION_EXPIRY_ACTION`
  decides what follows: `BLOCK` (default) or `HOLD`, which hands the payment to the fraud team. A payment is
  never approved automatically. Expiry is applied whenever confirmations are read or answered; there is no
  background thread.
- **Settings:** all three (`CONFIRMATION_EXPIRY_MINUTES`, `CONFIRMATION_EXPIRY_ACTION`,
  `CONFIRMATION_HARD_BLOCK_RULES`) are in `system_settings`.
- **APIs:**
  - `GET /api/transactions/confirmations`
  - `POST /api/transactions/<id>/confirmation {"response": "YES"|"NO"}`
  - `POST /api/transactions/<id>/verification/confirm`
  - `GET /api/detection/confirmations`
- **Dashboards:**
  - User: pending alerts, plus Successful and Blocked history.
  - Receiver: only payments that were approved and credited.
  - Frauder: the typed details, the owner's answer and the final label.
  - Detection System: "Account-owner confirmations" with rules, score, answer and final status.
  - All four use the same label (`outcome_label`).

**Viva example (tested on the real `bank` database):**

1. As the Frauder, target Rahul. Type city Delhi, location Connaught Place, device type Android phone, device ID
   ATK-VIVA-01 and IP 49.36.12.8.
2. Click **Log in with stolen password**.
3. Attempt ₹80,000 to Priya. R4 + R9 = 65, so the payment is held for Review.
4. Log in as Rahul: the security alert appears.
   - **NO** blocks it and no money moves.
   - Repeat with device ID ATK-VIVA-02 and answer **YES**, then enter the OTP and password. The re-evaluation
     scores 0, and ₹80,000 moves from Rahul to Priya.

The login step matters. With only a new device and a different city, the engine fires just R4 (20), so the
payment is **approved and the money moves**. R1 does not fire for Rahul because he has fewer than 3 payments
in 90 days, so it uses the ₹1,00,000 no-history limit.

---

## 4. The nine rules

Each rule is one parameterised SQL query in `backend/portal/helpers/fraud_rules.py`. Parameters and weights live in
the `fraud_rules` table and can be edited live.

| Code | Rule | SQL technique | Weight | Default parameters |
|------|------|---------------|-------:|--------------------|
| R1 | High amount | `AVG()` over a per-account time range | 30 | > 5× 90-day average (≥ 3 past payments), else ≥ ₹1,00,000 |
| R2 | Velocity | `COUNT()` over a sliding window | 25 | > 5 payments in 10 min |
| R3 | Impossible travel | `LAG()` window function, `TIMESTAMPDIFF`, `ST_Distance_Sphere` | 35 | different city ≥ 100 km within 30 min |
| R4 | New device + high amount | `NOT EXISTS` on device history | 20 | untrusted, never-used device, > ₹25,000 |
| R5 | Odd hour | `HOUR()` + amount | 10 | 00:00–05:00, > ₹10,000 |
| R6 | Watch-listed counterparty | `JOIN` against `watchlist` | 50 | account, UPI, device or IP listed |
| R7 | Structuring | `COUNT()` with `BETWEEN` | 15 | ≥ 3 payments within 10 % below ₹50,000 in 24 h |
| R8 | Dormant reactivation | `DATEDIFF()` on `accounts.last_txn_at` | 20 | ≥ 180 idle days, ≥ ₹25,000 |
| R9 | Suspicious login / takeover | correlated subqueries on `login_attempts`, `security_events`, `devices` | 45 | ≥ ₹5,000 after ≥ 3 failed logins, ≥ 2 wrong OTPs, new-device login (15 min) or login away from home |

**Pipeline.** `POST /api/transactions/send` does all of the following inside **one DB transaction with one
commit**:
1. Lock the sender and receiver rows (`SELECT … FOR UPDATE`, in id order).
2. Check the balance.
3. `INSERT` the transaction.
4. Evaluate all active rules on the same connection.
5. Write `risk_assessments` and `triggered_rules`.
6. Decide, and move money only if APPROVED.
7. Raise alerts and notifications.

Any error rolls back everything. `Idempotency-Key` plus a unique `(sender_account_id, idempotency_key)`
index means a double-clicked submit creates one payment.

---

## 5. Database

`flask db upgrade` runs three migrations in `backend/migrations/versions/`:

1. **0001_create_schema**: 22 tables with primary keys, foreign keys, CHECK constraints and indexes.
   Each table is created only if missing.
2. **0002_seed_master_data**: runs the seeders in `portal/seeders/`.
   - inserts 4 roles, 12 cities, the demo logins, the simulation accounts, the 9 rules, the 3 risk bands,
     11 scenarios, the watchlist seeds and the settings
   - each row is inserted only if its natural key is absent, so it never duplicates rows or overwrites an
     admin's changes
   - inserts no transactions
   - `flask seed` re-runs the same seeders on their own, e.g. to restore a deleted demo login
3. **0003_views_and_audit_triggers**: `v_rule_performance` (per-rule hits/precision) and
   `v_daily_transaction_summary` views, plus triggers that make `audit_logs` append-only.

Main tables:

| Area | Tables |
|------|--------|
| Users and roles | `roles`, `users` |
| Accounts and balances | `accounts` (balance ≥ 0 CHECK) |
| Devices and locations | `devices`, `locations` |
| Transactions | `transactions` (composite index `(sender_account_id, txn_time)`) |
| Fraud rules and bands | `fraud_rules`, `risk_categories` |
| Risk scores and decisions | `risk_assessments` |
| Triggered-rule records | `triggered_rules` |
| Security | `login_attempts`, `security_events`, `verification_challenges` |
| Watchlisted entities | `watchlist` |
| Alerts and notifications | `alerts`, `notifications` |
| Retired auto-simulation (kept, unused) | `fraud_scenarios`, `simulation_runs`, `simulation_events` |
| Audit | `audit_logs` (SHA-256 hash chain + append-only triggers) |
| Settings | `system_settings` |

Running `flask db upgrade` again, or on a database that already has these tables, is safe. A
`flask db downgrade` past 0001 drops the tables, so only do that deliberately.

---

## 6. Testing

```bash
cd backend
.venv\Scripts\activate
pytest -q
```

The 87 tests never touch `bank`. While they run they use a temporary `bank_test` database on the same
server, named automatically from `DATABASE_URL`. Delete it afterwards if you only want one database. They cover:
- all four logins, account lockout and role-based access
- every rule firing individually
- score capping, decision bands, and rule/band configuration
- balances moving only on approval
- idempotency and rollback on mid-pipeline failure
- step-up verification and analyst approve/reject
- each of the nine rules triggered by hand through the Frauder console, with exact rules, score and decision; money moving only for approved attempts; repeated submissions, lockout, demo-clock handling, Frauder permissions and the scoped reset
- Demo Mode and its resets; the automatic simulation endpoints are gone
- the audit hash chain and immutability
- re-running migrations without duplicates or data loss

**Manual check (viva script):**
1. Rahul sends ₹5,000 to `priya@fsbank`: APPROVED.
2. Log in as Priya in another tab: ₹5,000 credited.
3. Rahul pays ₹10,000 to `quickcash@fsbank`: UNDER REVIEW (R6, 50). Not credited. An alert appears on the
   Detection dashboard within ~3 s.
4. Rahul verifies with the OTP: it is still R6, so it goes to the analyst. The analyst approves or rejects
   it in the investigation view.
5. Demo Mode → *Simulate a new device*, log in as Rahul again, send ₹30,000: R4 + R9 = 65 → REVIEW.
   Verifying clears both, and the payment is released.
6. As the Frauder, follow “Test the 9 Fraud Detection Rules” and watch each attempt appear for Rahul and in the live monitor.
7. Demo Mode → **Reset demo data** restores everything.

---

## 7. Project layout

```
backend/
  app.py              entry point (python app.py; FLASK_APP=app.py in .flaskenv)
  config/config.py    Config / TestConfig, read from .env
  docs/API.md         every endpoint
  logs/               app.log (rotating)
  migrations/         Alembic env + versions 0001–0007
  portal/
    __init__.py       create_app(): logger → db/migrate → JWT → api → routes → seed CLI
    extensions.py     db, migrate, jwt
    logger.py         console + rotating file logging
    seeds.py          `flask seed` command
    api/              CORS, JWT error responses, JSON error handlers
    helpers/          fraud_rules.py (9 SQL rules), fraud_engine.py (scoring), payment_engine.py
                      (pipeline, step-up, analyst decisions), auth.py, frauder.py (manual attacker console),
                      analytics.py, demo.py, audit.py (hash chain), security.py (JWT + RBAC),
                      validators.py, responses.py, helpers.py (settings, notifications, alerts)
    models/           one module per table + utils.py
    routes/           one package per feature: <feature>/__init__.py creates the Blueprint,
                      <feature>/routes.py adds the views. authentication, users, receivers,
                      transactions, detection, alerts, notifications, analytics, security,
                      frauder, demo, meta
    seeders/          seed_roles, seed_locations, seed_users, seed_fraud_rules,
                      seed_risk_categories, seed_scenarios, seed_watchlist, seed_settings
  tests/              pytest suite
  requirements.txt  .env.example
frontend/
  src/pages/      Login, DemoMode, user/, receiver/, detection/, frauder/
  src/components/ Layout, tables, modals, badges
  src/api/client.js  src/styles.css
```

**Notes and limits**
- Device identity is a per-browser ID in localStorage, and location is chosen from a list (both simulated).
- The simulated OTP is shown in-app as an "SMS". No SMS is sent.
