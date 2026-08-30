# Testing Batch Production

```bash
cd tooling/upload
../ad-creatives/.venv/Scripts/python.exe -m unittest tests.test_batch_core -v
```

Manual dry-run:
1. Start `server.py`
2. Artwork Studio → Batch Production
3. Download template; keep example rows or reduce to 1–2 artworks
4. Upload → Validate → Confirm with dry-run checked
5. Watch progress; refresh browser; confirm Batch Runs + Factory Dashboard update
6. Restart server mid-batch; queued jobs continue

Never mix dry-run artifacts with real listings without checking `meta.dry_run`.
