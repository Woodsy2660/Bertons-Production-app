# Scripts

| Script | Purpose |
|--------|---------|
| `deploy.sh` | Production Docker deploy helper |
| `docker-entrypoint.sh` | Container entry (migrate + start) |
| `dev-up.ps1` | Windows local up helper |
| `seed_dashboard_runs.py` | Seed sample dashboard batches |
| `seed_history_runs.py` | Seed 10 older COMPLETE runs for history search |
| `seed_test_run.py` | Seed a single test run |
| `populate_run_15785.py` | Populate a specific run with demo data |
| `qa_*.py` | Live QA / load / concurrency checks (need running app + DB) |
| `restore_missing_uploads.py` | Recreate missing files under `uploads/` when DB rows still exist |

Run from repo root with `DATABASE_URL` set as for the app.

If work-order / label PDFs fail to open after a cleanup that emptied `uploads/`, run:

```bash
python scripts/restore_missing_uploads.py
```
