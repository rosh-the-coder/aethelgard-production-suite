"""Archive Studio unit tests — no live museum APIs."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
UPLOAD = os.path.dirname(HERE)
sys.path.insert(0, UPLOAD)


class RightsTests(unittest.TestCase):
    def test_classify_cc0_and_pd(self):
        from archive.schema import classify_rights, rights_is_clear_reuse

        self.assertEqual(classify_rights("CC0 1.0 Universal"), "cc0")
        self.assertEqual(classify_rights("Public Domain Mark"), "public_domain")
        self.assertEqual(classify_rights("in copyright"), "restricted")
        self.assertEqual(classify_rights("maybe free?"), "unclear")
        self.assertTrue(rights_is_clear_reuse("cc0"))
        self.assertFalse(rights_is_clear_reuse("unclear"))

    def test_orientation(self):
        from archive.schema import classify_orientation

        self.assertEqual(classify_orientation(1000, 2000), "portrait")
        self.assertEqual(classify_orientation(2000, 1000), "landscape")
        self.assertEqual(classify_orientation(1000, 1000), "square")
        self.assertEqual(classify_orientation(None, 10), "unknown")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        import archive.store as store
        import archive.paths as paths

        paths.ARCHIVE_DATA_DIR = self.tmp.name
        paths.DB_PATH = os.path.join(self.tmp.name, "archive.sqlite3")
        paths.FILES_DIR = os.path.join(self.tmp.name, "files")
        paths.THUMBS_DIR = os.path.join(self.tmp.name, "thumbs")
        paths.CACHE_DIR = os.path.join(self.tmp.name, "cache")
        store.DB_PATH = paths.DB_PATH
        store._INIT = False
        store.init_db()
        self.store = store

    def test_upsert_dedupes_source_id(self):
        from archive.schema import NormalizedRecord

        rec = NormalizedRecord(
            source="cleveland",
            source_object_id="42",
            title="Still Life",
            artist="Test",
            source_image_url="https://openaccess-cdn.clevelandart.org/x.jpg",
            rights_status="cc0",
            is_public_domain=True,
        )
        a, created = self.store.upsert_record(rec)
        self.assertTrue(created)
        rec.title = "Still Life (updated)"
        b, created2 = self.store.upsert_record(rec)
        self.assertFalse(created2)
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(b["title"], "Still Life (updated)")
        listed = self.store.list_assets(q="Still")
        self.assertEqual(listed["total"], 1)

    def test_collections_and_jobs(self):
        from archive.schema import NormalizedRecord

        rec = NormalizedRecord(source="met", source_object_id="1", title="Wave")
        asset, _ = self.store.upsert_record(rec)
        col = self.store.create_collection("Japanese Prints")
        self.store.add_assets_to_collection(col["id"], [asset["id"]])
        got = self.store.get_collection(col["id"])
        self.assertEqual(got["asset_count"], 1)
        job = self.store.create_job("fullres_download", {"asset_ids": [asset["id"]]}, total=1)
        claimed = self.store.claim_next_job()
        self.assertEqual(claimed["id"], job["id"])
        self.assertEqual(claimed["status"], "running")


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        import archive.store as store
        import archive.paths as paths

        paths.ARCHIVE_DATA_DIR = self.tmp.name
        paths.DB_PATH = os.path.join(self.tmp.name, "archive.sqlite3")
        store.DB_PATH = paths.DB_PATH
        store._INIT = False
        store.init_db()

    def test_import_records_and_skip_dupes(self):
        from archive import ingest

        records = [
            {
                "source": "artic",
                "source_object_id": "99",
                "title": "Lilies",
                "artist": "Unknown",
                "rights_status": "public_domain",
                "is_public_domain": True,
                "source_image_url": "https://www.artic.edu/iiif/2/abc/full/max/0/default.jpg",
            }
        ]
        first = ingest.import_records(records)
        second = ingest.import_records(records, skip_duplicates=True)
        self.assertEqual(first["created"], 1)
        self.assertEqual(second["created"], 0)
        self.assertEqual(second["skipped"], 1)


class DedupeQcTests(unittest.TestCase):
    def test_hamming(self):
        from archive.dedupe import hamming_hex

        self.assertEqual(hamming_hex("00", "00"), 0)
        self.assertGreater(hamming_hex("00", "ff"), 0)

    def test_qc_flags(self):
        from archive.qc import evaluate

        flags = evaluate(
            {
                "title": "Helmet",
                "artist": "",
                "rights_status": "unclear",
                "source_image_url": "",
                "media_type": "armor",
            }
        )
        self.assertIn("missing_image", flags)
        self.assertIn("unclear_rights", flags)
        self.assertIn("metadata_incomplete", flags)
        self.assertIn("not_wall_art", flags)


class ConnectorNormalizeTests(unittest.TestCase):
    def test_cleveland_record(self):
        from archive.connectors.cleveland import _record

        rec = _record(
            {
                "id": 123,
                "title": "Fruit Piece",
                "creators": [{"description": "Jane Doe (American)"}],
                "creation_date": "1888",
                "url": "https://www.clevelandart.org/art/123",
                "share_license_status": "CC0",
                "type": "Painting",
                "technique": "oil on canvas",
                "images": {
                    "web": {"url": "https://openaccess-cdn.clevelandart.org/web.jpg", "width": 800, "height": 1000},
                    "full": {"url": "https://openaccess-cdn.clevelandart.org/full.jpg", "width": 4000, "height": 5000},
                },
            }
        )
        self.assertEqual(rec.source, "cleveland")
        self.assertTrue(rec.is_public_domain)
        self.assertEqual(rec.rights_status, "cc0")
        self.assertIn("full.jpg", rec.source_image_url)
        self.assertEqual(rec.orientation, "portrait")

    def test_artic_skips_without_image(self):
        from archive.connectors.artic import _record

        self.assertIsNone(_record({"id": 1, "title": "No image", "is_public_domain": True}))

    def test_met_requires_public_domain(self):
        from archive.connectors.met import _record

        self.assertIsNone(_record({"objectID": 1, "isPublicDomain": False, "primaryImage": "https://images.metmuseum.org/x.jpg"}))
        rec = _record(
            {
                "objectID": 2,
                "isPublicDomain": True,
                "primaryImage": "https://images.metmuseum.org/x.jpg",
                "title": "Wheat Field",
                "artistDisplayName": "Van Gogh",
            }
        )
        self.assertEqual(rec.source, "met")
        self.assertTrue(rec.is_public_domain)

    def test_pipeline_object_shape(self):
        from archive.pipeline import assets_to_import_objects

        objs = assets_to_import_objects(
            [
                {
                    "id": "ast_1",
                    "source": "cleveland",
                    "source_object_id": "9",
                    "title": "Roses",
                    "artist": "Anon",
                    "source_image_url": "https://openaccess-cdn.clevelandart.org/a.jpg",
                    "rights_status": "cc0",
                    "licence_type": "CC0",
                }
            ]
        )
        self.assertEqual(objs[0]["object_id"], "9")
        self.assertEqual(objs[0]["image"], "https://openaccess-cdn.clevelandart.org/a.jpg")
        self.assertEqual(objs[0]["archive_asset_id"], "ast_1")


class HttpAllowlistTests(unittest.TestCase):
    def test_host_allowlist(self):
        from archive.http_util import host_allowed

        self.assertTrue(host_allowed("https://openaccess-cdn.clevelandart.org/x.jpg"))
        self.assertTrue(host_allowed("https://www.artic.edu/iiif/2/x/full/max/0/default.jpg"))
        self.assertFalse(host_allowed("https://evil.example/steal.jpg"))


if __name__ == "__main__":
    unittest.main()
