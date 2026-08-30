# API Reference (Factory / Batch)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/dashboard` | Aggregate factory state |
| GET | `/api/events` | SSE live stream |
| GET | `/api/quota` | Daily artwork quota |
| GET | `/api/batches` | Batches grouped by date |
| GET | `/api/batches/{id}` | Batch detail + progress |
| GET | `/api/batches/{id}/report` | JSON report download |
| POST | `/api/batches/validate` | Parse + validate upload |
| POST | `/api/batches` | Create batch from file |
| POST | `/api/batches/{id}/start` | Accept quota + queue |
| POST | `/api/batches/{id}/cancel` | Cancel queued jobs |
| POST | `/api/batches/{id}/retry` | Retry failed jobs |
| GET | `/api/templates/batch.csv` | CSV template |
| GET | `/api/templates/batch.xlsx` | XLSX template |
| POST | `/api/products/rebuild` | Mark stale artifacts |
| POST | `/api/products/etsy-draft` | New draft (confirm required) |
| GET | `/api/products/draft-history?piece_dir=` | Draft history |
| POST | `/api/settings/email/test` | Test SMTP |
| GET | `/api/audit` | Recent audit entries |

All paths validate IDs; batch ids cannot contain path separators.

Archive Studio (bulk public-domain acquisition) is documented separately: [ARCHIVE_STUDIO.md](./ARCHIVE_STUDIO.md). Prefix `/api/archive/`. It does not replace Artwork Studio `/api/public_domain/*` routes.
