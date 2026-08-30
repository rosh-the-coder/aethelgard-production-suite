# Migration — V2 Batch / Factory OS

No database migration of artwork-runs is required. New state lives under `tooling/upload/.factory/`.

Existing products continue to appear via `scan_runs()`. Batch-created pieces are normal catalog pieces with `meta.batch_id`.

Restart the Production Suite server to load factory routes and the background worker.

Backward compatible: generator routes unchanged; Batch Production is a fourth Artwork Studio mode tab.
