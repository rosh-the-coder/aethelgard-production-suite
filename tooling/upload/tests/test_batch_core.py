"""Unit tests for batch parser, quota, grouping, and dry-run pipeline."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
UPLOAD = os.path.dirname(HERE)
sys.path.insert(0, UPLOAD)


class BatchParserTests(unittest.TestCase):
    def test_csv_parse_and_group(self):
        from factory import batch_parser

        csv = (
            "listing_id,artwork_id,concept,acquisition_mode,artwork_count,aspect_ratio,selection_policy\n"
            "L1,a1,owl in library,ai,1,4:5,first_success\n"
            "L1,a2,owl feathers,ai,1,4:5,first_success\n"
            "L2,b1,coast fog,ai,2,3:2,manual_review\n"
        ).encode("utf-8")
        rows = batch_parser.parse_csv_bytes(csv)
        self.assertEqual(len(rows), 3)
        result = batch_parser.validate_rows(rows)
        self.assertTrue(result["ok"], result.get("errors"))
        self.assertEqual(result["artworks_requested"], 4)
        self.assertEqual(result["listings_detected"], 2)
        groups = batch_parser.group_by_listing(result["rows"])
        self.assertEqual(len(groups["L1"]), 2)

    def test_quota_blocks_over_limit(self):
        from factory import batch_parser, quota
        from factory.paths import QUOTA_PATH

        # isolate quota file
        if os.path.isfile(QUOTA_PATH):
            # don't destroy user quota — use accept check only with large request
            pass
        rows = [
            {
                "listing_id": "X",
                "artwork_id": f"a{i}",
                "concept": "test",
                "acquisition_mode": "ai",
                "artwork_count": "1",
                "aspect_ratio": "4:5",
            }
            for i in range(25)
        ]
        result = batch_parser.validate_rows(rows)
        self.assertFalse(result["ok"])

    def test_duplicate_artwork_id(self):
        from factory import batch_parser

        rows = [
            {
                "listing_id": "L",
                "artwork_id": "same",
                "concept": "a",
                "acquisition_mode": "ai",
                "artwork_count": "1",
            },
            {
                "listing_id": "L",
                "artwork_id": "same",
                "concept": "b",
                "acquisition_mode": "ai",
                "artwork_count": "1",
            },
        ]
        result = batch_parser.validate_rows(rows)
        self.assertFalse(result["ok"])

    def test_inconsistent_listing_fields(self):
        from factory import batch_parser

        rows = [
            {
                "listing_id": "L",
                "artwork_id": "a",
                "concept": "a",
                "acquisition_mode": "ai",
                "product_type": "single",
                "listing_title": "One",
            },
            {
                "listing_id": "L",
                "artwork_id": "b",
                "concept": "b",
                "acquisition_mode": "ai",
                "product_type": "single",
                "listing_title": "Two",
            },
        ]
        result = batch_parser.validate_rows(rows)
        self.assertFalse(result["ok"])


class QuotaTests(unittest.TestCase):
    def test_accept_and_restore(self):
        from factory import quota
        from factory.paths import FACTORY_DATA_DIR
        import json

        # use unique batch ids
        snap0 = quota.snapshot()
        remaining = snap0["remaining"]
        if remaining < 2:
            self.skipTest("not enough remaining quota in live ledger")
        snap = quota.accept(2, batch_id="test-quota-unit", listing_ids=["L"])
        self.assertEqual(snap["remaining"], remaining - 2)
        snap2 = quota.restore_cancelled(2, batch_id="test-quota-unit")
        self.assertEqual(snap2["remaining"], remaining)


class JobStoreTests(unittest.TestCase):
    def test_batch_progress(self):
        from factory import job_store

        job_store.init_db()
        bid = job_store.next_batch_id()
        job_store.create_batch(
            batch_id=bid,
            source_filename="t.csv",
            source_path="/tmp/t.csv",
            artwork_total=2,
            listing_total=1,
            dry_run=True,
        )
        job_store.create_job(batch_id=bid, listing_id="L", artwork_id="a1", row={"listing_id": "L"})
        job_store.create_job(batch_id=bid, listing_id="L", artwork_id="a2", row={"listing_id": "L"})
        progress = job_store.recompute_batch_progress(bid)
        self.assertEqual(progress["progress"]["artworks_total"], 2)


class DryRunPipelineTests(unittest.TestCase):
    def test_dry_run_creates_piece(self):
        from factory import job_store, batch_pipeline, batch_service
        from factory.paths import RUNS_DIR

        job_store.init_db()
        csv = (
            "listing_id,artwork_id,concept,acquisition_mode,artwork_count,aspect_ratio,selection_policy,listing_title\n"
            "dry_l1,dry_a1,test owl dry-run,ai,1,4:5,first_success,Dry Run Owl\n"
        ).encode("utf-8")
        from factory import batch_parser

        rows = batch_parser.parse_csv_bytes(csv)
        validation = batch_parser.validate_rows(rows)
        self.assertTrue(validation["ok"], validation.get("errors"))
        # may fail if quota exhausted
        try:
            batch = batch_service.create_batch_from_validation(
                filename="dry.csv",
                data=csv,
                validation=validation,
                dry_run=True,
            )
        except ValueError as e:
            self.skipTest(str(e))
        bid = batch["id"]
        batch_service.start_batch(bid)
        job = job_store.claim_next_job()
        self.assertIsNotNone(job)
        result = batch_pipeline.process_job(job, suite_settings={"prices": {"single": 2.99}})
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result.get("piece_path"))
        self.assertTrue(os.path.isfile(os.path.join(result["piece_path"], "meta.json")))
        self.assertTrue(os.path.isfile(os.path.join(result["piece_path"], "master.png")))


class InvalidationTests(unittest.TestCase):
    def test_mark_stale(self):
        from factory import invalidation

        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "meta.json"), "w", encoding="utf-8") as f:
                f.write("{}")
            payload = invalidation.mark_stale(td, "artwork", reason="test")
            self.assertIn("prints", payload["stale"])
            self.assertIn("mockups", payload["stale"])


class DraftHistoryTests(unittest.TestCase):
    def test_resubmit_preserves_old(self):
        from factory import draft_history

        with tempfile.TemporaryDirectory() as td:
            draft_history.record_draft(td, draft_id="d1", dry_run=True)
            draft_history.record_draft(td, draft_id="d2", replaces_draft_id="d1", dry_run=True)
            hist = draft_history.load_history(td)
            self.assertEqual(hist["current_draft_id"], "d2")
            statuses = {d["draft_id"]: d["status"] for d in hist["drafts"]}
            self.assertEqual(statuses["d1"], "superseded")
            self.assertEqual(statuses["d2"], "draft")


if __name__ == "__main__":
    unittest.main()
