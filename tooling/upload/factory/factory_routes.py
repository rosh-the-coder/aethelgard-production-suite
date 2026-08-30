"""HTTP helpers for factory / batch / dashboard / events APIs."""
from __future__ import annotations

import json
import os
import queue
import time
import urllib.parse
from typing import Any, Callable, Dict, Optional

from . import batch_parser
from . import batch_service
from . import batch_templates
from . import batch_worker
from . import draft_history
from . import email_notify
from . import events
from . import factory_state
from . import invalidation
from . import job_store
from . import quota
from .audit import audit, read_audit
from .paths import safe_batch_id


def _json_response(handler, payload: Any, status: int = 200) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-type", "application/json")
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _bytes_response(handler, data: bytes, content_type: str, filename: str) -> None:
    handler.send_response(200)
    handler.send_header("Content-type", content_type)
    handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(data)


def handle_get(
    handler,
    path: str,
    *,
    scan_runs: Callable,
    build_preflight: Callable,
    load_suite_settings: Callable,
    research_count: Optional[int] = None,
) -> bool:
    """Return True if handled."""
    if path == "/api/dashboard":
        preflight = build_preflight()
        auth = {}
        etsy = {}
        try:
            from etsy_api import api_status

            etsy = api_status()
        except Exception as e:
            etsy = {"error": str(e)}
        auth_path = os.path.join(os.path.dirname(__file__), "..", "auth_state.json")
        auth = {"authenticated": os.path.isfile(os.path.abspath(auth_path))}
        payload = factory_state.build_dashboard(
            scan_runs=scan_runs,
            preflight=preflight,
            auth=auth,
            etsy_api=etsy,
            research_count=research_count,
        )
        _json_response(handler, payload)
        return True

    if path == "/api/quota":
        _json_response(handler, quota.snapshot())
        return True

    if path == "/api/batches":
        grouped = batch_service.batches_by_date()
        _json_response(handler, {"by_date": grouped, "batches": job_store.list_batches(limit=100)})
        return True

    if path.startswith("/api/batches/") and path.endswith("/report"):
        bid = path[len("/api/batches/") : -len("/report")]
        try:
            bid = safe_batch_id(bid)
        except ValueError as e:
            _json_response(handler, {"error": str(e)}, 400)
            return True
        detail = job_store.recompute_batch_progress(bid)
        text = json.dumps(detail, indent=2)
        _bytes_response(handler, text.encode("utf-8"), "application/json", f"{bid}-report.json")
        return True

    if path.startswith("/api/batches/"):
        bid = path[len("/api/batches/") :]
        if "/" in bid:
            return False
        try:
            bid = safe_batch_id(bid)
        except ValueError as e:
            _json_response(handler, {"error": str(e)}, 400)
            return True
        detail = job_store.recompute_batch_progress(bid)
        if not detail.get("id"):
            _json_response(handler, {"error": "Batch not found"}, 404)
            return True
        _json_response(handler, detail)
        return True

    if path == "/api/templates/batch.csv":
        data = batch_templates.build_csv_template()
        _bytes_response(handler, data, "text/csv; charset=utf-8", "aethelgard_batch_template.csv")
        return True

    if path == "/api/templates/batch.xlsx":
        try:
            data = batch_templates.build_xlsx_template()
        except Exception as e:
            _json_response(handler, {"error": str(e)}, 500)
            return True
        _bytes_response(
            handler,
            data,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "aethelgard_batch_template.xlsx",
        )
        return True

    if path == "/api/audit":
        _json_response(handler, {"entries": read_audit(100)})
        return True

    if path.startswith("/api/products/") and path.endswith("/draft-history"):
        # /api/products/<encoded_path>/draft-history — use query piece_dir instead for safety
        return False

    if path == "/api/products/draft-history":
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(handler.path).query)
        piece_dir = (qs.get("piece_dir") or [""])[0]
        if not piece_dir or not os.path.isdir(piece_dir):
            _json_response(handler, {"error": "Invalid piece_dir"}, 400)
            return True
        _json_response(handler, draft_history.load_history(piece_dir))
        return True

    if path == "/api/events":
        # Server-Sent Events stream
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("Connection", "keep-alive")
        handler.end_headers()
        q = events.subscribe()
        try:
            # hello
            hello = json.dumps({"type": "connected", "ts": time.time()})
            handler.wfile.write(f"data: {hello}\n\n".encode("utf-8"))
            handler.wfile.flush()
            while True:
                try:
                    event = q.get(timeout=15)
                    line = f"id: {event['id']}\nevent: {event['type']}\ndata: {json.dumps(event)}\n\n"
                    handler.wfile.write(line.encode("utf-8"))
                    handler.wfile.flush()
                except queue.Empty:
                    handler.wfile.write(b": keepalive\n\n")
                    handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            events.unsubscribe(q)
        return True

    return False


def handle_post(
    handler,
    path: str,
    body: Dict[str, Any],
    *,
    load_suite_settings: Callable,
    save_suite_settings: Callable,
) -> bool:
    if path == "/api/batches/validate":
        filename = body.get("filename") or "upload.csv"
        raw_b64 = body.get("content_base64")
        raw_text = body.get("content_text")
        if raw_b64:
            import base64

            data = base64.b64decode(raw_b64)
        elif raw_text is not None:
            data = str(raw_text).encode("utf-8")
        else:
            _json_response(handler, {"error": "Missing file content"}, 400)
            return True
        try:
            rows = batch_parser.parse_upload(filename, data)
            result = batch_parser.validate_rows(rows)
            result["filename"] = filename
            result["report"] = batch_parser.validation_report_text(result, filename)
            audit("batch.validated", filename=filename, ok=result.get("ok"), rows=result.get("total_rows"))
            _json_response(handler, result)
        except Exception as e:
            _json_response(handler, {"error": str(e)}, 400)
        return True

    if path == "/api/batches":
        filename = body.get("filename") or "upload.csv"
        dry_run = bool(body.get("dry_run"))
        exclude_invalid = bool(body.get("exclude_invalid"))
        raw_b64 = body.get("content_base64")
        raw_text = body.get("content_text")
        if raw_b64:
            import base64

            data = base64.b64decode(raw_b64)
        elif raw_text is not None:
            data = str(raw_text).encode("utf-8")
        else:
            _json_response(handler, {"error": "Missing file content"}, 400)
            return True
        try:
            rows = batch_parser.parse_upload(filename, data)
            validation = batch_parser.validate_rows(rows)
            batch = batch_service.create_batch_from_validation(
                filename=filename,
                data=data,
                validation=validation,
                dry_run=dry_run,
                exclude_invalid=exclude_invalid,
            )
            _json_response(handler, {"success": True, "batch": batch})
        except Exception as e:
            _json_response(handler, {"error": str(e)}, 400)
        return True

    if path.startswith("/api/batches/") and path.endswith("/start"):
        bid = path[len("/api/batches/") : -len("/start")]
        try:
            result = batch_service.start_batch(bid)
            _json_response(handler, {"success": True, "batch": result})
        except Exception as e:
            _json_response(handler, {"error": str(e)}, 400)
        return True

    if path.startswith("/api/batches/") and path.endswith("/cancel"):
        bid = path[len("/api/batches/") : -len("/cancel")]
        try:
            result = batch_service.cancel_batch(bid)
            _json_response(handler, {"success": True, "batch": result})
        except Exception as e:
            _json_response(handler, {"error": str(e)}, 400)
        return True

    if path.startswith("/api/batches/") and path.endswith("/retry"):
        bid = path[len("/api/batches/") : -len("/retry")]
        try:
            result = batch_service.retry_failed(bid)
            _json_response(
                handler,
                {
                    "success": True,
                    "retried_count": result.get("retried_count", 0),
                    "message": (
                        f"Queued {result.get('retried_count', 0)} failed job(s) for retry"
                        if result.get("retried_count")
                        else "No failed jobs to retry"
                    ),
                    "batch": result,
                },
            )
        except Exception as e:
            _json_response(handler, {"error": str(e)}, 400)
        return True

    if path == "/api/jobs/resume-selection":
        job_id = body.get("job_id")
        from . import batch_pipeline

        job = batch_pipeline.resume_selection(job_id)
        if not job:
            _json_response(handler, {"error": "Job not found"}, 404)
            return True
        _json_response(handler, {"success": True, "job": job})
        return True

    if path == "/api/products/rebuild":
        piece_dir = body.get("piece_dir")
        changed = body.get("changed") or "artwork"
        if not piece_dir or not os.path.isdir(piece_dir):
            _json_response(handler, {"error": "Invalid piece_dir"}, 400)
            return True
        payload = invalidation.mark_stale(piece_dir, changed, reason=body.get("reason") or "")
        audit("product.invalidated", piece_dir=piece_dir, changed=changed)
        events.publish("metadata.changed", {"piece_dir": piece_dir, "stale": payload})
        events.invalidate("product.rebuild", piece_dir=piece_dir)
        _json_response(handler, {"success": True, **payload})
        return True

    if path == "/api/products/etsy-draft":
        piece_dir = body.get("piece_dir")
        if not piece_dir or not os.path.isdir(piece_dir):
            _json_response(handler, {"error": "Invalid piece_dir"}, 400)
            return True
        if not body.get("confirm"):
            _json_response(handler, {"error": "Confirmation required to create a new Etsy draft"}, 400)
            return True
        prev = draft_history.current_draft_id(piece_dir)
        dry_run = bool(body.get("dry_run"))
        draft_id = body.get("draft_id") or f"{'dryrun-' if dry_run else 'draft-'}{int(time.time())}"
        entry = draft_history.record_draft(
            piece_dir,
            draft_id=str(draft_id),
            batch_id=body.get("batch_id") or "",
            replaces_draft_id=prev,
            dry_run=dry_run,
            status="draft",
        )
        # update upload status without publishing
        status = {
            "status": "draft",
            "message": "New draft created (previous preserved)",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "piece_dir": piece_dir.replace("\\", "/"),
            "draft_id": draft_id,
            "replaces_draft_id": prev,
            "publish": False,
        }
        with open(os.path.join(piece_dir, "upload_status.json"), "w", encoding="utf-8") as f:
            json.dump(status, f, indent=2)
        audit("etsy.draft_created", piece_dir=piece_dir, draft_id=draft_id, replaces=prev)
        events.publish("etsy.draft_created", {"draft_id": draft_id, "replaces": prev})
        events.invalidate("etsy.draft")
        _json_response(handler, {"success": True, "draft": entry, "history": draft_history.load_history(piece_dir)})
        return True

    if path == "/api/settings/email/test":
        suite = load_suite_settings()
        result = email_notify.send_email(
            suite=suite,
            subject="Aethelgard test email",
            body="This is a test message from Aethelgard Presets & Settings.",
            force=True,
        )
        _json_response(handler, result, 200 if result.get("ok") else 400)
        return True

    return False


def boot_factory(load_suite_settings: Callable) -> None:
    job_store.init_db()
    batch_worker.start_worker(get_settings=load_suite_settings, concurrency=1)
    audit("factory.booted")
