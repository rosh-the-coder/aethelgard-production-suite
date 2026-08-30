# Dashboard State

The Factory Dashboard is a **projection** of application state, not a separate store.

Aggregate: `GET /api/dashboard` via `factory/factory_state.py`

Sources:
- `scan_runs()` artwork folders
- SQLite batch/jobs
- quota ledger
- audit log
- preflight / Etsy auth

Live updates: `GET /api/events` (SSE). Client falls back to 8s polling if the stream drops.

Deletion, batch progress, quota, and draft creation publish invalidation events so open dashboards refresh without a full page reload.
