# Batch Template Schema

See columns in `factory/batch_schema.py`.

Required: `listing_id`; `concept` for `ai` / `graphic_poster`.

Enums:
- `acquisition_mode`: ai | public_domain | graphic_poster
- `aspect_ratio`: 4:5 | 3:2 | 1:1 | 2:3 | 5:4
- `delivery_type`: digital_files | drive_pdf
- `selection_policy`: first_success | manual_review

`artwork_count` defaults to 1. Daily total = sum of artwork_count.
