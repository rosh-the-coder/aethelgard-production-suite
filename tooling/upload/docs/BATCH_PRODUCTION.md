# Batch Production

Artwork Studio → **Batch Production** turns a CSV/XLSX into background factory jobs.

## Flow

1. Download template (`/api/templates/batch.xlsx` or `.csv`)
2. Fill rows (one row = one artwork; shared `listing_id` = one listing)
3. Upload → Validate → Confirm quota → Start
4. Worker processes jobs through acquire → master → prints → mockups → SEO → package → Etsy draft → review
5. Products appear in Catalog & Listings; organisational view in **Batch Runs**

## Dry-run

Enable the dry-run checkbox (default). Creates clearly marked test artifacts under `artwork-runs/dryrun_*`, does not call paid APIs or real Etsy, does not send email unless configured and enabled.

## Quota

20 artworks / local calendar day. Consumed on batch **start**. Retries do not consume extra. Cancel-before-start restores quota.

## Persistence

- Products: `artwork-runs/`
- Jobs/batches: `.factory/jobs.sqlite3`
- Quota: `.factory/quota_ledger.json`
- Source files: `.factory/batches/<id>/`
