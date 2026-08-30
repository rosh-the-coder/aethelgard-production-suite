# Archive Studio

Bulk public-domain / open-access **acquisition and listing engine** for Aethelgard.

This is a **dedicated feature**, not an extension of Artwork Studio. Existing Art Studio search, mockup generation, SEO, listing drafts, factory jobs, and Google Drive packaging are unchanged. Archive Studio feeds selected works into that same downstream pipeline.

Internal name: **Aethelgard Archive Studio — Bulk Public Domain Art Acquisition & Listing Engine**.

## Architecture

```
dashboard.html  →  Archive Studio view (#view-archive)
archive_studio.js / archive_studio.css

/api/archive/*  →  archive/routes.py
                     ├─ connectors/     (one module per museum API)
                     ├─ ingest.py       (live search + metadata import)
                     ├─ download.py     (thumbnails, then selective full-res)
                     ├─ store.py        (SQLite .archive/archive.sqlite3)
                     ├─ worker.py       (background jobs, separate from factory)
                     ├─ drive_sync.py   (reuses drive_delivery OAuth)
                     └─ pipeline.py     (calls public_domain.import_objects_to_run)
```

Data lives under `tooling/upload/.archive/` so factory `.factory/jobs.sqlite3` and Artwork Studio `artwork-runs/` are never migrated or overwritten.

## Usage flow

1. Open **Archive Studio** in the sidebar.
2. On **Sources**, confirm which APIs are reachable (keys optional except Rijksmuseum / Europeana).
3. **Search / Import** — keyword + rights + orientation + source chips. Results are metadata + thumbnails only.
4. Import selected hits, or **Queue bulk ingest** for hundreds of metadata records (resumable job).
5. **Library** — filter, collect, QC flags, bulk full-res download.
6. **Listing Pipeline** — send a collection or selection into `import_objects_to_run`. Continue in Artwork Studio / Catalog for mockups, SEO, drafts.
7. **Drive Sync** — upload full-res files into configurable `Aethelgard/...` folders using the existing Drive connection.

## Connectors

| Source | Auth | Notes |
|---|---|---|
| Cleveland Museum of Art | none | CC0 Open Access. First-class connector. |
| Rijksmuseum | `RIJKSMUSEUM_API_KEY` | Image-only search. Verify rights per object. |
| Smithsonian Open Access | `SMITHSONIAN_API_KEY` or `DEMO_KEY` | Prefers CC0 media. DEMO_KEY is rate-limited. |
| Library of Congress | none | Rights **vary**. Default filters should exclude unclear records. |
| Art Institute of Chicago | none | `is_public_domain=true` + IIIF `full/max`. |
| The Met | none | Open Access `isPublicDomain=true`. Independent of Art Studio `public_domain.py`. |
| Europeana | `EUROPEANA_API_KEY` | Filter `RIGHTS:*zero*` / public-domain URLs. |

Put keys in `~/.config/ai-images/env` (same file as Drive / Etsy):

```
RIJKSMUSEUM_API_KEY=...
SMITHSONIAN_API_KEY=...
EUROPEANA_API_KEY=...
```

### Extending sources

Add `archive/connectors/<name>.py` implementing `health`, `search`, `fetch`, returning `NormalizedRecord`. Register it in `archive/connectors/__init__.py` and `schema.SOURCE_ORDER`.

## Data model

SQLite tables: `assets`, `collections`, `collection_assets`, `jobs`, `job_items`, `rules`, `logs`.

Normalized asset fields include source identity, rights/licence, dimensions, orientation, tags, processing / mockup / SEO / listing / Drive statuses, SHA-256, perceptual (average) hash, QC flags, and local/Drive paths.

Schema is additive and isolated — no changes to factory or listing tables.

## Jobs

Kinds: `search_ingest`, `thumbnail_sync`, `fullres_download`, `image_prep`, `drive_sync`, `pipeline_handoff`, `dedupe_scan`, `rule_run`.

Daemon thread `aethelgard-archive-worker` starts with the HTTP server. Jobs are resumable (`queued` → `running` → `done` / `failed` / `cancelled`). Search ingest stores an offset cursor.

## Google Drive

Reuses `drive_delivery.get_service()` (same OAuth as Catalog → Package to Drive). Default relative folders (configurable in the Drive tab):

```
Aethelgard/Source Archive/{source}/{theme}/
Aethelgard/Processed Assets/{collection}/
Aethelgard/Mockups/{collection}/
Aethelgard/SEO/{collection}/
Aethelgard/Listing Packages/{collection}/
```

Uploads are idempotent by filename inside the target folder (Drive file replace). Duplicate uploads of the same local file name in that folder are updated, not doubled.

Listing **customer delivery** folders (`00_Mockups_Private` / `01_Customer_Delivery`) remain the Catalog packaging path and are not replaced.

## Pipeline handoff

`POST /api/archive/pipeline/handoff` downloads missing full-res files, maps assets to the object shape Artwork Studio already imports, and calls `public_domain.import_objects_to_run`. That creates a pack under `tooling/digital-product-research/artwork-runs/`. Mockup generation, SEO packs, Etsy drafts, and listing Drive packaging stay on existing endpoints.

## API (prefix `/api/archive`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/sources` | Connector health + library counts |
| GET | `/search` | Live multi-source metadata search |
| POST | `/import` | Import selected records (metadata) |
| POST | `/import/search` | Queue bulk metadata ingest |
| GET | `/assets` | Library list + filters |
| POST | `/assets/bulk` | download / collect / pipeline / drive / qc / delete |
| GET/POST | `/collections` | Collections CRUD |
| GET/POST | `/jobs` | Queue; `/retry` `/cancel` |
| POST | `/pipeline/handoff` | Create Artwork Studio PD pack |
| POST | `/drive/sync` | Queue Drive upload |
| GET/POST | `/rules` | Automation rules |
| GET | `/proxy-image` | Allowlisted thumbnail proxy |

## Environment / setup

No new Python packages. Uses `requests` and `Pillow` already in `requirements.txt`.

Image hosts are allowlisted (`archive/schema.py` `IMAGE_HOST_ALLOWLIST`) so the proxy cannot fetch arbitrary URLs.

## Known limitations / TODOs

- Rijksmuseum and Europeana need API keys; without them the connector reports `needs_key` and search returns a warning instead of failing the rest of the suite.
- Met search fetches object records after an ID list (rate-limited). Large Met ingests are slower than Cleveland / AIC.
- Library of Congress JSON sometimes omits stable full-res URLs; those records stay metadata-only until a usable image URL exists.
- Perceptual hash is average-hash (aHash), not pHash/dHash. Near-duplicates with heavy crops may be missed.
- Automation rules run on demand, not on a cron.
- Full-res files are cached locally under `.archive/files/` before Drive upload. Disk is the working set; Drive is the long-term 5TB archive.

## Tests

```
python -m unittest tooling.upload.tests.test_archive_studio
```

From `tooling/upload`:

```
python -m unittest tests.test_archive_studio
```
