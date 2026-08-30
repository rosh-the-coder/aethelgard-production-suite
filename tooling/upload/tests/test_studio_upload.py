"""Artwork Studio Upload: aspect, filename grouping, listing-kind routing."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from io import BytesIO

HERE = os.path.dirname(os.path.abspath(__file__))
UPLOAD = os.path.dirname(HERE)
sys.path.insert(0, UPLOAD)

from pd_prep import classify_aspect  # noqa: E402
from studio_upload import (  # noqa: E402
    extract_size_token,
    group_upload_files,
    handle_studio_upload,
    humanize_filename,
    import_files_to_run,
    print_family_for,
    stem_key,
)


def _png_bytes(w, h, color=(40, 80, 120)):
    from PIL import Image

    im = Image.new("RGB", (w, h), color)
    buf = BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


class FilenameAndAspectTests(unittest.TestCase):
    def test_stem_groups_print_size_variants(self):
        self.assertEqual(stem_key("roses_8x10.jpg"), stem_key("roses_16x20.png"))
        self.assertNotEqual(stem_key("roses.jpg"), stem_key("tulips.jpg"))

    def test_size_token_from_filename(self):
        self.assertEqual(extract_size_token("french-kitchen_8x10.jpg"), "8x10")
        self.assertEqual(extract_size_token("still-life-A4.png"), "a4")
        self.assertEqual(extract_size_token("untitled.png"), "")

    def test_humanize_strips_size_token(self):
        self.assertEqual(humanize_filename("french_country_kitchen_8x10.jpg"), "French Country Kitchen")

    def test_classify_portrait_4x5_and_landscape_3x2(self):
        aspect, orient, _ = classify_aspect(800, 1000)
        self.assertEqual(aspect, "4:5")
        self.assertEqual(orient, "portrait")
        aspect, orient, _ = classify_aspect(1200, 800)
        self.assertEqual(aspect, "3:2")
        self.assertEqual(orient, "landscape")
        aspect, orient, _ = classify_aspect(1000, 1000)
        self.assertEqual(aspect, "1:1")
        self.assertEqual(orient, "square")

    def test_print_family_includes_8x10_for_4x5(self):
        fam = print_family_for("4:5", "portrait", "owl.png")
        self.assertIn("8x10", fam["print_sizes"])
        fam2 = print_family_for("4:5", "portrait", "owl_8x10.png")
        self.assertEqual(fam2["filename_size"], "8x10")

    def test_group_keeps_largest_as_master(self):
        files = [
            {"filename": "roses_8x10.png", "data": b"small"},
            {"filename": "roses_16x20.png", "data": b"much-larger-bytes"},
            {"filename": "tulips.png", "data": b"other"},
        ]
        grouped = group_upload_files(files)
        self.assertEqual(len(grouped), 2)
        roses = next(g for g in grouped if g["group_key"] == stem_key("roses_8x10.png"))
        self.assertEqual(roses["filename"], "roses_16x20.png")
        self.assertEqual(roses["size_siblings"], ["roses_8x10.png"])


class ImportRoutingTests(unittest.TestCase):
    def test_single_vs_bundle_product_type_and_native_aspect(self):
        portrait = _png_bytes(800, 1000)
        landscape = _png_bytes(1200, 800)
        files = [
            {"filename": "owl_8x10.png", "data": portrait},
            {"filename": "coast.png", "data": landscape},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            runs = os.path.join(tmp, "runs")
            os.makedirs(runs)
            run_dir, cands, errors, meta = import_files_to_run(
                files,
                runs,
                tmp,
                listing_kind="single",
                name="Night Owl",
                trim_borders=False,
                infer_context=False,
                title_fn=lambda concept, spine: [f"{concept} Wall Art"] * 3,
                gemini_key=None,
            )
            self.assertFalse(errors)
            self.assertEqual(len(cands), 2)
            self.assertEqual(meta["listing_kind"], "single")
            self.assertEqual(cands[0]["product_type"], "print")
            owl = next(c for c in cands if "owl" in (c.get("source_filename") or ""))
            self.assertEqual(owl["aspect"], "4:5")
            self.assertEqual(owl["orientation"], "portrait")
            self.assertIn("8x10", owl["print_sizes"])
            coast = next(c for c in cands if "coast" in (c.get("source_filename") or ""))
            self.assertEqual(coast["aspect"], "3:2")
            self.assertEqual(coast["orientation"], "landscape")
            self.assertTrue(os.path.isfile(os.path.join(run_dir, "studio_upload_manifest.json")))

            run2, cands2, _, meta2 = import_files_to_run(
                files,
                runs,
                tmp,
                listing_kind="bundle",
                name="Gallery Set",
                trim_borders=False,
                infer_context=False,
                title_fn=lambda concept, spine: [f"{concept} Set"] * 3,
            )
            self.assertEqual(meta2["listing_kind"], "bundle")
            self.assertEqual(cands2[0]["product_type"], "upload_bundle")
            self.assertEqual(meta2["pack_title"], "Gallery Set")
            self.assertGreaterEqual(len(cands2), 2)

    def test_size_variants_collapse_to_one_candidate(self):
        small = _png_bytes(400, 500)
        large = _png_bytes(800, 1000)
        files = [
            {"filename": "roses_8x10.png", "data": small},
            {"filename": "roses_16x20.png", "data": large},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            runs = os.path.join(tmp, "runs")
            os.makedirs(runs)
            _, cands, errors, _ = import_files_to_run(
                files, runs, tmp, listing_kind="single", infer_context=False
            )
            self.assertFalse(errors)
            self.assertEqual(len(cands), 1)
            self.assertEqual(cands[0]["source_filename"], "roses_16x20.png")
            self.assertIn("roses_8x10.png", cands[0]["size_siblings"])

    def test_json_handle_rejects_empty(self):
        status, payload = handle_studio_upload(
            content_type="application/json",
            body=b"{}",
            runs_dir=tempfile.gettempdir(),
            root_dir=tempfile.gettempdir(),
            json_data={},
        )
        self.assertEqual(status, 400)
        self.assertFalse(payload.get("success"))

    def test_json_handle_imports_one(self):
        import base64

        blob = _png_bytes(640, 800)
        with tempfile.TemporaryDirectory() as tmp:
            status, payload = handle_studio_upload(
                content_type="application/json",
                body=b"",
                runs_dir=os.path.join(tmp, "runs"),
                root_dir=tmp,
                json_data={
                    "listing_kind": "single",
                    "name": "Test Owl",
                    "infer_context": False,
                    "files": [{
                        "filename": "owl.png",
                        "data_b64": base64.b64encode(blob).decode("ascii"),
                    }],
                },
                title_fn=lambda c, s: [f"{c} A", f"{c} B", f"{c} C"],
            )
            self.assertEqual(status, 200, payload)
            self.assertTrue(payload["success"])
            self.assertEqual(len(payload["candidates"]), 1)
            self.assertEqual(payload["candidates"][0]["aspect"], "4:5")
            self.assertEqual(payload["listing_kind"], "single")

    def test_session_saves_to_disk_then_cleans_staging(self):
        from studio_upload import (
            add_upload_file,
            begin_upload_session,
            commit_upload_session,
            STAGING_ROOT,
        )

        portrait = _png_bytes(800, 1000)
        landscape = _png_bytes(1200, 800)
        with tempfile.TemporaryDirectory() as tmp:
            rec = begin_upload_session(listing_kind="single", name="Starboy", infer_context=False)
            sid = rec["id"]
            add_upload_file(sid, "the weeknd starboy 2_3.png", portrait)
            add_upload_file(sid, "the weeknd starboy A.png", landscape)
            self.assertTrue(os.path.isdir(os.path.join(STAGING_ROOT, sid)))
            run_dir, cands, errors, meta = commit_upload_session(
                sid,
                os.path.join(tmp, "runs"),
                tmp,
                title_fn=lambda c, s: [f"{c} A"] * 3,
            )
            self.assertFalse(errors)
            self.assertEqual(len(cands), 2)
            self.assertFalse(os.path.isdir(os.path.join(STAGING_ROOT, sid)))
            self.assertTrue(os.path.isfile(os.path.join(run_dir, "studio_upload_manifest.json")))

    def test_no_combined_payload_cap(self):
        import studio_upload as su
        self.assertFalse(hasattr(su, "MAX_TOTAL_BYTES"))
        self.assertGreaterEqual(su.MAX_FILE_BYTES, 2 * 1024 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
