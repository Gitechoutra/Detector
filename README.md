# FraudShield – SQL-Based Real-Time Fraud Detection and Transaction Monitoring System

Every payment is checked against nine SQL fraud rules the moment it is made. Each fired rule adds its
weight to a risk score, `Risk = min(100, Σ weights)`. The score and its band (0–39 low, 40–69 review,
70–100 high) are recorded for investigation, but **the account owner makes the final decision**:

| Situation | Status shown | What happens |
|-----------|--------------|--------------|
| No rule triggered (genuine payment by the owner) | SUCCESSFUL | Money moves immediately; the receiver is credited |
| Any Frauder attempt, even with no rule triggered | USER_CONFIRMATION_PENDING | Never made by the owner, so always held for their YES/NO |
| Any rule triggered (any score – below 70 is not "safe", 70+ stays high risk) | USER_CONFIRMATION_PENDING | Held, nothing debited; the owner gets "Suspicious transaction detected. Did you initiate this transaction?" |
| Owner answers YES | OTP_VERIFICATION_PENDING | An OTP goes to the owner's registered phone and e-mail; nothing moves yet |
| Correct, unexpired OTP | SUCCESSFUL | Re-validated (accounts, balance), then debited and credited |
| Wrong OTP 3 times | BLOCKED | No money moves; HIGH alert |
| Owner answers NO | BLOCKED | No money moves; the **receiver account is flagged and blocked** in the database; HIGH alerts |
| No answer in 30 min | EXPIRED | Never authorized; no money moves |

All payments are simulated. Nothing connects to a real bank, UPI, SMS or payment system.

**Stack:** React 18 + JavaScript + CSS (Vite) · Python 3 / Flask (Blueprints, JWT) · MySQL 8 (InnoDB) ·
Flask-Migrate / Alembic.

---

## 1. Quick start

Prerequisites: Python 3.11+, Node 18+, a running MySQL 8 server.

**One step** (after `git clone` or `git pull`), from the repository root:

```bash
powershell -ExecutionPolicy Bypass -File .\setup.ps1     # Windows
bash setup.sh                                            # macOS / Linux
```

The script:
- creates `backend/.venv` and installs `requirements.txt`;
- creates `backend/.env` from `.env.example` if it doesn't exist yet. It asks for your MySQL host, user, password
  and database name, and generates random secret keys. An existing `.env` is never changed;
- runs `flask init-db`, which creates the database if it's missing and then runs every migration. That builds
  all tables, the dummy accounts, the sample transaction history, the fraud rules and the settings;
- runs `npm ci` for the frontend.

Re-running it is safe: nothing is deleted, and seed rows are only inserted when missing.
For a non-interactive setup (CI, scripted machines), set `SETUP_DB_HOST`, `SETUP_DB_PORT`, `SETUP_DB_USER`,
`SETUP_DB_PASSWORD` and `SETUP_DB_NAME` before running the script; it then asks nothing.

Then start the app in two terminals:

```bash
cd backend  && .venv\Scripts\python.exe app.py      # macOS/Linux: .venv/bin/python app.py  → http://127.0.0.1:5000
cd frontend && npm run dev                            # http://localhost:3000
```

**Manual setup** (same result):

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate        # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                                 # macOS/Linux: cp – then set DATABASE_URL and the secret keys
flask init-db                                          # creates the database if needed + all migrations and seed data
cd ../frontend && npm ci
```

**After `git pull`:** run the setup script again, or `pip install -r requirements.txt`, `flask db upgrade` and
`npm ci`. The migrations are committed in `backend/migrations/versions/`; never autogenerate your own. That way
every developer's database ends up with the same tables, dummy accounts and sample data.

**Tests:** `cd backend && .venv\Scripts\python.exe -m pytest -q`. They create and drop their own `<db>_test`
database on the same server and never touch your data.

**What is in git and what isn't:**
- **In git:** migrations, seeders (dummy accounts, sample history, rules, watchlist, settings), tests,
  `.env.example`, `.flaskenv`, `requirements.txt`, `package-lock.json`.
- **Not in git (each machine has its own):** `backend/.env` (passwords and keys), `.venv/`, `node_modules/`, `dist/`
  and logs.

### `.env`

| Key | Purpose |
|-----|---------|
| `DATABASE_URL` | `mysql+pymysql://root:<password>@localhost:3306/bank?charset=utf8mb4` |
| `SECRET_KEY`, `JWT_SECRET_KEY` | Long random strings: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `JWT_ACCESS_MINUTES` | Login session length (default 480) |
| `CORS_ORIGINS` | Frontend origin(s) |
| `SEED_<KEY>_EMAIL`, `SEED_<KEY>_PASSWORD` | Login of each dummy account (keys below). Defaults are in `.env.example` |

No password or secret is written in the source code; everything comes from `.env` (missing `SEED_*` values fall
back to `.env.example`).

---

## 2. Dummy accounts

Created by `flask db upgrade` – there is no screen or API to create them. The emails and passwords below are the
defaults from `.env.example`; set `SEED_<KEY>_EMAIL` / `SEED_<KEY>_PASSWORD` in `backend/.env` to change them.

| Key | Role | Default email | Default password | Notes |
|-----|------|---------------|------------------|-------|
| `RAHUL` | User | rahul@demo.bank | Rahul@123 | ₹2,50,000 · Mumbai · UPI `rahul@fsbank` |
| `KARAN` | User | karan@demo.bank | Karan@123 | ₹1,50,000 · Delhi |
| `PRIYA` | User | priya@demo.bank | Priya@123 | UPI `priya@fsbank` |
| `AMIT` | User | amit@demo.bank | Amit@123 | UPI `amit@fsbank` |
| `QUICKCASH` | User (watch-listed) | quickcash@demo.bank | Quick@123 | Paying `quickcash@fsbank` fires R6 |
| `SURESH` | User (dormant) | suresh@demo.bank | Suresh@123 | Designated dormant account for R8 |
| `ANALYST` | Detection System | analyst@demo.bank | Detect@123 | Fraud team dashboard |
| `FRAUDER` | Frauder | frauder@demo.bank | Fraud@123 | Manual attacker console |

**Changing a login.** Edit `.env`, then restart the backend (or run `flask seed`). On every start the app
compares each dummy account with `.env` and updates its email, password (stored hashed) and role. Accounts
are matched by a fixed key (`users.seed_key`), so a new email renames the existing account – its balance and
history stay, and no duplicate is created. If the new email already belongs to another account, the change
is skipped and a warning is logged.

Each **browser tab** keeps its own login (sessionStorage), so you can have two Users (one paying, one
being paid) and Detection open side by side. Every customer sends and receives with one User login.

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
When any rule flags a payment, the user sees **Security Verification Required** with the amount,
receiver, transaction ID, time, triggered rules, risk score and reason. They answer
**YES, I INITIATED THIS TRANSACTION** (it is paid) or **NO, I DID NOT INITIATE THIS TRANSACTION** (it is
blocked). See "Account-owner authorization" below.

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
- **Detection Engine:** runs the nine SQL rules over the stored transactions of the dummy accounts – the
  seeded sample history plus every payment made since – and shows what they find. You can choose one account
  or all of them, a period, and whether to include Frauder attempts. It shows rule hits, risk bands, a
  per-account summary and every flagged transaction with its reasons; each row opens the Investigation view.
  - Each payment is evaluated at its own time inside a database savepoint that is rolled back, so a scan never
    changes a payment, its status or its stored score.
  - The run's results are saved in `detection_runs` and can be reopened.
  - "Differs from stored result" counts payments whose rules or weights have changed since they were decided.
  - R4 (device first use) and R8 (dormancy) read the account's current state, so for older payments they
    show what the rule says today.

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
- **Reset fraud attempts** (Frauder console) reverses exactly the money Frauder
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

**Account-owner verification ("Suspicious transaction detected").** Any payment on which at least one of
the nine risk factors fires is held (`USER_CONFIRMATION_PENDING`) and its owner is asked to verify it. This
happens whatever the score: a low score is not treated as safe, and a score of 70+ is still recorded as high
risk but held, not decided automatically. (The old `DECISION_MODE=AUTO` path is retired by migration 0010.)

- **The notification:** *"Suspicious transaction detected. Did you initiate this transaction?"* appears on
  the User dashboard, on the Send money result, and in the notification centre until it is answered or
  expires. It shows the amount, receiver, transaction ID, date and time, device, IP and location, the risk
  factors with reasons, and the risk score.
- **YES → OTP:**
  - The server checks that the logged-in user owns the payment and that the request is still pending, then
    records the answer and time.
  - A 6-digit OTP is generated (only its hash is stored) and sent to the owner's registered phone and e-mail.
    No SMS or e-mail gateway is configured, so delivery is simulated: the message appears in the owner's
    notification centre, addressed to the masked contacts.
  - The OTP is valid for `OTP_EXPIRY_MINUTES` (5). An expired OTP is rejected (410) and a new one can be sent
    ("Resend OTP"), which voids the old one. A wrong OTP is rejected (422), and after `OTP_MAX_ATTEMPTS` (3)
    wrong codes the payment is BLOCKED (**OTP FAILED – PAYMENT BLOCKED**).
  - Only a correct, unexpired OTP authorizes the payment. The server then locks both accounts and
    re-validates them: both active, receiver not blocked, enough balance, no absolute restriction. The sender
    is debited and the receiver credited exactly once (**USER AUTHORIZED – PAYMENT SUCCESSFUL**).
- **NO → stop and block the receiver:**
  - The payment is BLOCKED with reason *"Account owner denied initiating this transaction."* No money moves.
  - The receiver account is set to `BLOCKED` in `accounts.status`, so every payment to it (UPI, QR or bank
    transfer, from anyone) is refused by the server with `RECEIVER_BLOCKED`. Payments already held for it
    cannot be authorized either.
  - The receiver's UPI ID and account number are flagged on the watchlist (R6 fires for them).
  - A `receiver_blocks` record stores the reason, risk score, risk factors, a transaction snapshot and the
    time.
  - Alerts raised: HIGH `USER_DENIED` and `RECEIVER_BLOCKED`. The receiver is notified, and the attacker's
    device and public IP are watch-listed.
  - A blocked account can still send its own money; only receiving is blocked.
  - A fraud analyst can lift a block (Detection → Watchlist → *Blocked receiver accounts*, reason required,
    audited). The account becomes ACTIVE once no other block on it is active.
- **Unchanged by the answer:** the risk score and triggered rules are kept exactly as first calculated.
- **Safeguards:**
  - The answer is validated on the server. Only the logged-in owner can answer (anyone else gets 404; other
    roles, including the Frauder, get 403).
  - The transaction row is locked, so only the first answer counts; a repeat gets 409.
  - Answers after expiry are rejected (410).
  - Analysts cannot decide a payment that is still waiting for its owner (409).
- **Settings (`system_settings`):**
  - `CONFIRMATION_EXPIRY_MINUTES` (30).
  - `CONFIRMATION_EXPIRY_ACTION`: `EXPIRE` (default), `BLOCK`, or `HOLD`, which hands the payment to an
    analyst. A payment is never approved automatically.
  - `CONFIRMATION_HARD_BLOCK_RULES`: empty by default. Listing a rule here (e.g. `R6`) makes it an absolute
    restriction that is blocked without asking.
- **Expiry timing:** it is applied whenever confirmations, dashboards or notifications are read. There is
  no background thread.
- **APIs:**
  - `GET /api/transactions/confirmations`
  - `POST /api/transactions/<id>/confirmation {"response": "YES"|"NO"}`
  - `POST /api/transactions/<id>/verification/confirm {"otp": "123456"}`
  - `POST /api/transactions/<id>/verification/start` (resend the OTP)
  - `GET /api/detection/confirmations`
  - `GET /api/detection/receiver-blocks`
  - `POST /api/detection/receiver-blocks/<id>/lift {"reason": "..."}`
  - `GET /api/frauder/records`
- **Dashboards:**
  - User: pending verifications with YES/NO, plus Successful, Blocked and Expired history.
  - Receiver: only credited payments.
  - Frauder → **Fraud Records**: only records the application generated. That means flagged transactions
    (seeded sample history excluded), flagged and blocked receiver accounts, transaction details, risk scores
    and factors, the owner's YES/NO, OTP status and detection timestamps. The console no longer shows victim
    profile cards, previously typed device IDs, rule hints or the typed attacker details.
  - Detection: "Suspicious transactions – owner confirmations" with rules, score, answer and final status.
  - All four use the same label (`outcome_label`). The plain status name is in `display_status`; the database
    still stores COMPLETED / UNDER_REVIEW.

**Viva example (tested on the real `bank` database):**

1. As the Frauder, target Rahul. Type city Delhi, location Connaught Place, device type Android phone, device ID
   ATK-VIVA-01 and IP 49.36.12.8. Attempt ₹80,000 to Priya.
2. R4 fires (new device, ₹80,000), score 20, so the payment is **USER CONFIRMATION PENDING**. Nothing has moved.
3. Log in as Rahul. The "Security Verification Required" card appears.
   - **NO** blocks it: no money moves, and every dashboard shows USER DENIED – PAYMENT BLOCKED.
   - Repeat with device ID ATK-VIVA-02 and answer **YES**: ₹80,000 moves from Rahul to Priya, and Priya sees
     it credited.
4. **Reset fraud attempts** reverses the ₹80,000.


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

`flask db upgrade` runs the migrations in `backend/migrations/versions/` (committed to git):

1. **0001_create_schema**: 22 tables with primary keys, foreign keys, CHECK constraints and indexes.
   Each table is created only if missing.
2. **0002_seed_master_data**: runs the seeders in `portal/seeders/` (roles, cities, dummy accounts, the 9
   rules, the 3 risk bands, scenarios, watchlist, settings). Rows are inserted only if their natural key
   is absent, so re-running never duplicates rows or overwrites an admin's changes.
3. **0003_views_and_audit_triggers**: `v_rule_performance` and `v_daily_transaction_summary` views, plus
   triggers that make `audit_logs` append-only.
4. **0004–0008**: registration settings, Frauder console and owner-confirmation columns, the `EXPIRED` status.
5. **0009_seed_accounts_engine**:
   - `users.seed_key`, the stable key of each dummy account
   - the retired `RECEIVER` role merged into `USER`
   - the `detection_runs` table
   - re-runs every seeder, so an older database gets missing settings, dummy accounts and the sample history
6. **0010_receiver_blocks**: the `BLOCKED` account status, the `receiver_blocks` table, and `DECISION_MODE`
   retired (every flagged payment is verified by its owner).
7. **0011_notification_cleared**: `notifications.cleared_at` – "Mark all read" clears the list (rows are kept).
8. **0012_revoked_tokens**: logout revokes the login token; every request rejects a revoked token.

**Seeded sample history** (`seed_transactions.py`, references `SEED-0001`…`SEED-0024`):
- Ordinary payments between the dummy accounts in the last two months.
- Older patterns that trip R1, R2, R3, R5, R6 and R7, for the Detection Engine to find. These are older than
  90 days, so they do not change the Frauder console's R1 averages.
- It is the accounts' past, so it never changes a balance. Suresh is left dormant.

`flask seed` re-runs every seeder on its own, e.g. to restore a deleted dummy login.

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

The 160 tests never touch `bank`. While they run they use a temporary `bank_test` database on the same
server, named automatically from `DATABASE_URL`. Delete it afterwards if you only want one database. They cover:
- all four logins, account lockout and role-based access
- every rule firing individually
- score capping, decision bands, and rule/band configuration
- balances moving only on approval
- idempotency and rollback on mid-pipeline failure
- each of the nine rules triggered alone through the Frauder console, held, then YES (paid) and NO (blocked) – 18 cases
- multiple rules, duplicates, expiry, insufficient balance, frozen receiver, unauthorized and Frauder responses
- the legacy OTP step-up and analyst approve/reject
- each of the nine rules triggered by hand through the Frauder console, with exact rules, score and decision; money moving only for approved attempts; repeated submissions, lockout, demo-clock handling, Frauder permissions and the scoped reset
- dummy accounts: one per key, credentials synchronised from `.env` (email rename, password, role), no
  duplicates, conflicts skipped; sample history seeded once without moving money
- the Detection Engine: finds the seeded patterns, filters by account and period, never changes a
  transaction, Detection role only
- Demo Mode is gone (its endpoints return 404); the automatic simulation endpoints are gone
- the audit hash chain and immutability
- re-running migrations without duplicates or data loss

**Manual check (viva script):**
1. Rahul sends ₹5,000 to `priya@fsbank`: SUCCESSFUL (no rule fired).
2. Log in as Priya in another tab: ₹5,000 credited.
3. Rahul pays ₹10,000 to `quickcash@fsbank`: R6 (50), so it is USER CONFIRMATION PENDING. Not credited. An
   alert appears on the Detection dashboard within ~3 s.
4. Rahul answers YES: QuickCash is credited. Repeat and answer NO: it is blocked.
5. Log in as Rahul from another browser or a private window (a new device) and send ₹30,000: R4 + R9 = 65,
   so it is held for Rahul's answer.
6. As the Frauder, follow “Test the 9 Fraud Detection Rules” and watch each attempt appear for Rahul and in the live monitor.
7. As the Detection System, open **Detection Engine** and press **Run detection**: the seeded patterns and
   today's payments are listed with their rules and scores.
8. As the Frauder, **Reset fraud attempts** reverses everything the Frauder did.

---

## 7. Project layout

```
backend/
  app.py              entry point (python app.py; FLASK_APP=app.py in .flaskenv)
  config/config.py    Config / TestConfig, read from .env
  docs/API.md         every endpoint
  logs/               app.log (rotating)
  migrations/         Alembic env + versions 0001–0012 (committed – do not autogenerate)
  portal/
    __init__.py       create_app(): logger → db/migrate → JWT → api → routes → seed CLI
    extensions.py     db, migrate, jwt
    logger.py         console + rotating file logging
    seeds.py          `flask seed` command
    api/              CORS, JWT error responses, JSON error handlers
    helpers/          fraud_rules.py (9 SQL rules), fraud_engine.py (scoring), payment_engine.py
                      (pipeline, step-up, analyst decisions), auth.py, frauder.py (manual attacker console),
                      analytics.py, detection_engine.py, audit.py (hash chain), security.py (JWT + RBAC),
                      validators.py, responses.py, helpers.py (settings, notifications, alerts)
    models/           one module per table + utils.py
    routes/           one package per feature: <feature>/__init__.py creates the Blueprint,
                      <feature>/routes.py adds the views. authentication, users, receivers,
                      transactions, detection, alerts, notifications, analytics, security,
                      frauder, meta
    seeders/          seed_roles, seed_locations, seed_users (dummy accounts + .env sync),
                      seed_fraud_rules, seed_risk_categories, seed_scenarios, seed_watchlist,
                      seed_settings, seed_transactions (sample history)
  tests/              pytest suite
  requirements.txt  .env.example
frontend/
  src/pages/      Landing, Login, Register, user/, receiver/, detection/ (incl. DetectionEngine), frauder/
  src/components/ Layout, tables, modals, badges
  src/api/client.js  src/styles.css
```

**Notes and limits**
- Device identity is a per-browser ID in localStorage, and location is chosen from a list (both simulated).
- The simulated OTP is shown in-app as an "SMS". No SMS is sent.
- **Before a real deployment:**
  - Remove the on-screen demo OTP: the `demo_otp` field in `routes/transactions/routes.py` and the "Demo OTP" box
    in `SecurityConfirmation.jsx`.
  - Connect a real SMS/e-mail gateway in `payment_engine._issue_otp`.
  - Serve the API with a production WSGI server (e.g. `waitress-serve --port=5000 app:app` on Windows, or
    gunicorn on Linux). `python app.py` is Flask's development server.
  - Serve `frontend/dist` (from `npm run build`) as static files.
  - Set strong `SECRET_KEY`/`JWT_SECRET_KEY` and change every `SEED_*_PASSWORD` in `.env`.
