# API endpoints

Generated with `flask routes`. All paths are JSON; protected routes need `Authorization: Bearer <token>`.

| Method | Path | Handler |
|---|---|---|
| GET | `/api/alerts` | alerts.list_alerts |
| PATCH | `/api/alerts/<int:alert_id>` | alerts.update_alert |
| GET | `/api/analytics/summary` | analytics.summary |
| POST | `/api/auth/login` | auth.login |
| POST | `/api/auth/logout` | auth.logout |
| GET | `/api/auth/me` | auth.me |
| GET | `/api/demo/info` | demo.info |
| POST | `/api/demo/reset` | demo.reset |
| POST | `/api/demo/scenarios/<code>/run` | demo.run |
| GET | `/api/detection/live` | detection.live |
| GET | `/api/detection/risk-categories` | detection.risk_categories |
| PUT | `/api/detection/risk-categories` | detection.update_risk_categories |
| GET | `/api/detection/rules` | detection.rules |
| PUT | `/api/detection/rules/<code>` | detection.update_rule |
| GET | `/api/detection/search` | detection.search |
| GET | `/api/detection/transactions` | detection.transactions |
| GET | `/api/detection/transactions/<int:txn_id>` | detection.investigate |
| POST | `/api/detection/transactions/<int:txn_id>/decision` | detection.decide |
| GET | `/api/detection/users` | detection.users |
| GET | `/api/detection/watchlist` | detection.watchlist |
| POST | `/api/detection/watchlist` | detection.add_watchlist |
| PATCH | `/api/detection/watchlist/<int:entry_id>` | detection.toggle_watchlist |
| DELETE | `/api/detection/watchlist/<int:entry_id>` | detection.delete_watchlist |
| GET | `/api/health` | meta.health |
| GET | `/api/meta/locations` | meta.locations |
| GET | `/api/meta/risk-categories` | meta.risk_categories |
| GET | `/api/notifications` | notifications.notifications |
| POST | `/api/notifications/<int:notification_id>/read` | notifications.read_notification |
| POST | `/api/notifications/read-all` | notifications.read_all |
| GET | `/api/receiver/dashboard` | receiver.dashboard |
| GET | `/api/receiver/payments` | receiver.payments |
| GET | `/api/security/audit-logs` | security.audit_logs |
| GET | `/api/security/audit/verify` | security.verify_audit |
| GET | `/api/security/events` | security.events |
| GET | `/api/security/login-attempts` | security.login_attempts |
| GET | `/api/simulation/history` | simulation.history |
| GET | `/api/simulation/runs` | simulation.runs |
| GET | `/api/simulation/scenarios` | simulation.scenarios |
| POST | `/api/simulation/scenarios/<code>/run` | simulation.run_scenario |
| POST | `/api/simulation/start` | simulation.start |
| GET | `/api/simulation/stats` | simulation.stats |
| GET | `/api/simulation/status` | simulation.status |
| POST | `/api/simulation/stop` | simulation.stop |
| POST | `/api/transactions/<int:txn_id>/cancel` | transactions.cancel |
| POST | `/api/transactions/<int:txn_id>/verification/confirm` | transactions.confirm_verification |
| POST | `/api/transactions/<int:txn_id>/verification/start` | transactions.start_verification |
| POST | `/api/transactions/send` | transactions.send |
| GET | `/api/user/dashboard` | user.dashboard |
| POST | `/api/user/receivers/lookup` | user.lookup_receiver |
| GET | `/api/user/security` | user.security |
| GET | `/api/user/transactions` | user.transactions |
| GET | `/api/user/transactions/<int:txn_id>` | user.transaction_detail |
