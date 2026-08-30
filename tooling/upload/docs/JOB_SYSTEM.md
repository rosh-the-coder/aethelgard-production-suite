# Job System

SQLite store at `.factory/jobs.sqlite3`.

- `batches` table — batch metadata + progress counters
- `jobs` table — one row per artwork unit

Worker: `factory/batch_worker.py` daemon thread started with the HTTP server.

Claim is atomic (`queued`/`retry` → `running`). Survives UI navigation and browser refresh. On server restart, queued/retry jobs resume; in-flight jobs left `running` can be retried manually.

Concurrency: Presets & Settings → batch concurrency (default 1, max 4).
