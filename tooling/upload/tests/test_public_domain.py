"""Relevance ranking for Met Open Access search (no live API)."""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
UPLOAD = os.path.dirname(HERE)
sys.path.insert(0, UPLOAD)

from public_domain import (  # noqa: E402
    PD_IMPORT_MAX,
    _extract_source_url,
    _is_flat_artwork,
    _is_oil_on_canvas,
    _is_produce_query,
    _is_relevant_card,
    _loc_card_from_item,
    _loc_free_to_use_slug,
    _loc_masonry_items_from_payload,
    _loc_query_is_exclusive_set,
    _loc_resource_id,
    _loc_set_slug_for_query,
    _loc_tile_urls,
    _looks_like_bogus_met_ids,
    _score_card,
    expand_search_queries,
    search_met,
)


def _card(**kwargs):
    base = {
        "title": "",
        "artist": "",
        "department": "",
        "medium": "",
        "tags": [],
        "image": "https://example.test/img.jpg",
        "object_id": "1",
    }
    base.update(kwargs)
    return base


class ExpandQueryTests(unittest.TestCase):
    def test_vegetables_expands_to_still_life(self):
        variants = expand_search_queries("vegetables")
        self.assertTrue(any("still life" in v for v in variants), variants)
        self.assertTrue(any("cabbage" in v for v in variants), variants)
        self.assertFalse(any(v == "botanical" for v in variants), variants)

    def test_fungi_does_not_expand_to_floral(self):
        variants = expand_search_queries("mushroom")
        joined = " ".join(variants)
        self.assertIn("fungi", joined)
        self.assertNotIn("floral still life", joined)

    def test_produce_query_detects_vegetables(self):
        self.assertTrue(_is_produce_query("vegetables"))
        self.assertTrue(_is_produce_query("pumpkin"))
        self.assertFalse(_is_produce_query("coastal landscape"))


class RelevanceFilterTests(unittest.TestCase):
    def test_mask_is_not_relevant_for_vegetables(self):
        card = _card(title="Mask", department="The American Wing", tags=["Fish"])
        self.assertFalse(
            _is_relevant_card(card, ["vegetables"], ["vegetables", "cabbage"], min_score=8)
        )

    def test_rattle_and_gem_are_not_relevant(self):
        terms = ["vegetables", "cabbage", "pumpkin"]
        self.assertFalse(_is_relevant_card(_card(title="Raven rattle"), ["vegetables"], terms))
        self.assertFalse(_is_relevant_card(_card(title="Sard Amygdaloid"), ["vegetables"], terms))
        self.assertFalse(_is_relevant_card(_card(title="Ennanga"), ["vegetables"], terms))

    def test_vegetable_still_life_is_relevant(self):
        card = _card(
            title="Still Life: Balsam Apple and Vegetables",
            tags=["Vegetables", "Tomatoes", "Still Life"],
            department="The American Wing",
            classification="Paintings",
            medium="Oil on canvas",
        )
        self.assertTrue(_is_relevant_card(card, ["vegetables"], ["vegetables", "cabbage"]))

    def test_fruit_only_still_life_is_not_relevant_for_vegetables(self):
        card = _card(
            title="Still Life of Grapes and Peaches",
            tags=["Fruit", "Grapes"],
            department="European Paintings",
            classification="Paintings",
            medium="Oil on canvas",
        )
        terms = ["vegetables", "cabbage", "pumpkin"]
        card["_score"] = _score_card(card, terms, "vegetable still life", produce_mode=True)
        self.assertFalse(
            _is_relevant_card(card, ["vegetables"], terms, require_term=True, produce_mode=True)
        )

    def test_tagged_produce_without_title_word_is_relevant(self):
        card = _card(
            title="Kitchen table",
            tags=["Cabbage"],
            classification="Paintings",
            medium="Oil on canvas",
        )
        self.assertTrue(_is_relevant_card(card, ["vegetables"], ["vegetables", "cabbage"]))

    def test_corn_does_not_match_corner(self):
        card = _card(title="A quiet corner of the studio")
        self.assertFalse(_is_relevant_card(card, ["vegetables"], ["corn"]))


class MediumFilterTests(unittest.TestCase):
    def test_oil_painting_is_flat_art(self):
        card = _card(
            title="Still Life: Vegetables",
            classification="Paintings",
            medium="Oil on canvas",
            department="European Paintings",
        )
        self.assertTrue(_is_flat_artwork(card))

    def test_porcelain_teapot_is_not_flat_art(self):
        card = _card(
            title="Teapot in the form of a cabbage",
            classification="Ceramics",
            medium="Porcelain",
        )
        self.assertFalse(_is_flat_artwork(card))

    def test_photograph_is_not_flat_art(self):
        card = _card(
            title="Root vegetables",
            department="Photographs",
            classification="Photographs",
            medium="Albumen silver print",
        )
        self.assertFalse(_is_flat_artwork(card))

    def test_watercolor_is_rejected(self):
        card = _card(
            title="Still Life: Vegetables",
            classification="Drawings",
            medium="Watercolor on paper",
        )
        self.assertFalse(_is_flat_artwork(card))

    def test_oil_on_panel_is_rejected(self):
        card = _card(
            title="Still Life: Vegetables",
            classification="Paintings",
            medium="Oil on panel",
        )
        self.assertFalse(_is_flat_artwork(card))

    def test_oil_on_canvas_accepts_met_capitalization(self):
        card = _card(title="Washington Crossing the Delaware", medium="Oil on canvas")
        self.assertTrue(_is_oil_on_canvas(card))

    def test_photograph_not_allowed_even_when_user_asks(self):
        card = _card(
            title="Root vegetables",
            department="Photographs",
            classification="Photographs",
            medium="Albumen silver print",
        )
        self.assertFalse(_is_flat_artwork(card, query_terms=["vintage", "photograph"]))

    def test_oil_painting_outscores_porcelain(self):
        painting = _card(
            title="Cabbage still life",
            classification="Paintings",
            medium="Oil on canvas",
            department="European Paintings",
            tags=["Cabbage"],
        )
        pot = _card(
            title="Cabbage teapot",
            classification="Ceramics",
            medium="Porcelain",
            tags=["Cabbage"],
        )
        terms = ["cabbage"]
        self.assertGreater(
            _score_card(painting, terms, produce_mode=True),
            _score_card(pot, terms, produce_mode=True),
        )


class ScoringTests(unittest.TestCase):
    def test_vegetable_still_life_beats_mask(self):
        veg = _card(
            title="Still Life: Balsam Apple and Vegetables",
            tags=["Vegetables"],
            department="The American Wing",
            classification="Paintings",
            medium="Oil on canvas",
        )
        mask = _card(title="Mask", department="The American Wing", tags=["Fish"])
        terms = ["vegetables", "cabbage", "pumpkin"]
        veg_score = _score_card(veg, terms, "vegetable still life", produce_mode=True)
        mask_score = _score_card(mask, terms, "vegetables", produce_mode=True)
        self.assertGreater(veg_score, mask_score)
        self.assertGreater(veg_score, 10)
        self.assertLess(mask_score, 5)

    def test_bogus_id_cluster_still_detected(self):
        self.assertTrue(_looks_like_bogus_met_ids([544320, 310453, 200668, 1, 2, 3, 4, 5]))
        self.assertFalse(_looks_like_bogus_met_ids([11734, 10997, 435904, 1, 2, 3, 4, 5]))


class SearchMetMockTests(unittest.TestCase):
    def test_search_drops_unrelated_artifacts(self):
        catalog = {
            1: _card(object_id="1", title="Mask", department="The American Wing", tags=["Fish"]),
            2: _card(
                object_id="2",
                title="Still Life: Balsam Apple and Vegetables",
                tags=["Vegetables"],
                department="The American Wing",
                classification="Paintings",
                medium="Oil on canvas",
            ),
            3: _card(object_id="3", title="Raven rattle"),
            4: _card(object_id="4", title="Sard Amygdaloid", department="Greek and Roman Art"),
            5: _card(
                object_id="5",
                title="Bowl with Radish and Vegetables",
                tags=["Vegetables"],
                department="Asian Art",
                classification="Paintings",
                medium="Ink and color on silk",
            ),
            6: _card(
                object_id="6",
                title="Teapot in the form of a cabbage",
                tags=["Cabbage"],
                department="European Sculpture and Decorative Arts",
                classification="Ceramics",
                medium="Porcelain",
            ),
            7: _card(
                object_id="7",
                title="Stereograph of root vegetables",
                tags=["Vegetables"],
                department="Photographs",
                classification="Photographs",
                medium="Albumen silver print",
            ),
        }

        import public_domain as pd

        orig_ids = pd._met_search_ids
        orig_fetch = pd.fetch_met_object
        orig_commons = pd.search_wikimedia_commons
        orig_loc = pd.search_loc

        def fake_ids(query):
            return [1, 2, 3, 4, 5, 6, 7], 7

        def fake_fetch(oid):
            return catalog.get(int(oid))

        pd._met_search_ids = fake_ids
        pd.fetch_met_object = fake_fetch
        pd.search_wikimedia_commons = lambda *a, **k: []
        pd.search_loc = lambda *a, **k: []
        try:
            results = search_met("vegetables", limit=48)
        finally:
            pd._met_search_ids = orig_ids
            pd.fetch_met_object = orig_fetch
            pd.search_wikimedia_commons = orig_commons
            pd.search_loc = orig_loc

        titles = [r.get("title") for r in results]
        self.assertIn("Still Life: Balsam Apple and Vegetables", titles)
        self.assertNotIn("Bowl with Radish and Vegetables", titles)
        self.assertNotIn("Mask", titles)
        self.assertNotIn("Raven rattle", titles)
        self.assertNotIn("Sard Amygdaloid", titles)
        self.assertNotIn("Teapot in the form of a cabbage", titles)
        self.assertNotIn("Stereograph of root vegetables", titles)
        self.assertEqual(titles, ["Still Life: Balsam Apple and Vegetables"])


class LocSourceTests(unittest.TestCase):
    def test_extracts_pasted_loc_url(self):
        url = _extract_source_url(
            "please use https://www.loc.gov/free-to-use/autumn-and-halloween/"
        )
        self.assertEqual(url, "https://www.loc.gov/free-to-use/autumn-and-halloween/")

    def test_import_cap_allows_a_full_search_page(self):
        self.assertGreaterEqual(PD_IMPORT_MAX, 96)

    def test_loc_free_to_use_is_not_oil_filtered(self):
        card = _loc_card_from_item({
            "title": "Do Spirits Return?",
            "id": "http://www.loc.gov/item/2018694110/",
            "url": "https://www.loc.gov/item/2018694110/",
            "image_url": ["//cdn.loc.gov/small.jpg", "//cdn.loc.gov/large.jpg"],
            "access_restricted": False,
            "item": {"creators": [{"title": "Houdini"}], "medium": ["1 print (poster)"]},
        }, source="loc_free_to_use")
        self.assertIsNotNone(card)
        self.assertTrue(card["image"].startswith("https:"))
        self.assertTrue(_is_oil_on_canvas(card))
        self.assertTrue(_is_relevant_card(card, ["halloween"], ["halloween"]))

    def test_html_extracts_loc_item_ids(self):
        from public_domain import _loc_item_ids_from_html
        html = (
            '<a href="/item/2018694110/">Houdini</a>'
            '<a href="https://www.loc.gov/item/2017647655/">pumpkin</a>'
        )
        ids = _loc_item_ids_from_html(html)
        self.assertIn("2018694110", ids)
        self.assertIn("2017647655", ids)
    def test_extracts_loc_url_without_scheme(self):
        url = _extract_source_url("www.loc.gov/free-to-use/autumn-and-halloween/")
        self.assertEqual(url, "https://www.loc.gov/free-to-use/autumn-and-halloween/")

    def test_masonry_gallery_card(self):
        from public_domain import _loc_card_from_masonry
        card = _loc_card_from_masonry({
            "title": "Do spirits return? Houdini says no.",
            "image": "/static/portals/free-to-use/public-domain/autumn-and-halloween/autumn-11.jpg",
            "link": "/resource/cph.3g06112/",
        })
        self.assertIsNotNone(card)
        self.assertTrue(card["image"].startswith("/api/public_domain/image"))
        self.assertTrue(card["loc_source_image"].startswith("https://www.loc.gov/"))
        self.assertTrue(_is_oil_on_canvas(card))
        self.assertTrue(_is_relevant_card(card, ["halloween"], ["halloween"]))

    def test_pasted_loc_url_uses_cached_set_not_met(self):
        import public_domain as pd

        def boom(*_a, **_k):
            raise AssertionError("Met search should not run for a loc.gov URL")

        orig = pd._met_search_ids
        pd._met_search_ids = boom
        try:
            results, meta = search_met(
                "https://www.loc.gov/free-to-use/autumn-and-halloween/",
                limit=12,
                return_meta=True,
            )
        finally:
            pd._met_search_ids = orig
        self.assertGreaterEqual(len(results), 8)
        self.assertTrue(all(str(r.get("source") or "").startswith("loc") for r in results))
        blob = " ".join((r.get("title") or "").lower() for r in results)
        self.assertIn("october", blob)
        self.assertNotIn("classical landscape", blob)
        self.assertIn("library of congress", (meta.get("note") or "").lower())

    def test_halloween_keyword_uses_loc_set_not_met(self):
        import public_domain as pd

        def boom(*_a, **_k):
            raise AssertionError("Met search should not run for halloween")

        orig = pd._met_search_ids
        pd._met_search_ids = boom
        try:
            results, meta = search_met("halloween", limit=12, return_meta=True)
        finally:
            pd._met_search_ids = orig
        self.assertGreaterEqual(len(results), 8)
        self.assertTrue(all(str(r.get("source") or "").startswith("loc") for r in results))
        self.assertIn("not a met", (meta.get("note") or "").lower())

    def test_cats_keyword_is_loc_exclusive(self):
        self.assertEqual(_loc_set_slug_for_query("cats"), "cats")
        self.assertTrue(_loc_query_is_exclusive_set("cats"))
        import public_domain as pd

        def boom(*_a, **_k):
            raise AssertionError("Met search should not run for cats")

        orig = pd._met_search_ids
        pd._met_search_ids = boom
        try:
            results, meta = search_met("cats", limit=12, return_meta=True)
        finally:
            pd._met_search_ids = orig
        self.assertTrue(all(str(r.get("source") or "").startswith("loc") for r in results))
        blob = " ".join((r.get("title") or "").lower() for r in results)
        self.assertNotIn("classical landscape", blob)
        self.assertGreaterEqual(len(results), 8)

    def test_childrens_books_url_slug(self):
        from public_domain import _loc_free_to_use_slug
        self.assertEqual(
            _loc_free_to_use_slug("https://www.loc.gov/free-to-use/classic-childrens-books/"),
            "classic-childrens-books",
        )
        self.assertEqual(_loc_set_slug_for_query("denslow wonderland"), "classic-childrens-books")
        self.assertTrue(_loc_query_is_exclusive_set("classic childrens books"))
        import public_domain as pd

        def boom(*_a, **_k):
            raise AssertionError("Met search should not run for children's books")

        orig = pd._met_search_ids
        pd._met_search_ids = boom
        try:
            results, meta = search_met(
                "https://www.loc.gov/free-to-use/classic-childrens-books/",
                limit=24,
                return_meta=True,
            )
        finally:
            pd._met_search_ids = orig
        self.assertGreaterEqual(len(results), 8)
        self.assertTrue(all(str(r.get("source") or "").startswith("loc") for r in results))
        self.assertNotIn("classical landscape", " ".join((r.get("title") or "").lower() for r in results))


class LocTileUrlTests(unittest.TestCase):
    def test_ppmsca_group_by_hundreds(self):
        urls = " ".join(_loc_tile_urls("ppmsca.15528"))
        self.assertIn("ppmsca/15500/15528r.jpg", urls)

    def test_cph_three_level_path(self):
        urls = " ".join(_loc_tile_urls("cph.3c21044"))
        self.assertIn("cph/3c20000/3c21000/3c21000/3c21044", urls)

    def test_cai_and_agc_nested(self):
        cai = " ".join(_loc_tile_urls("cai.2a15065"))
        agc = " ".join(_loc_tile_urls("agc.7a16795"))
        self.assertIn("cai/2a15000/2a15000/2a15065", cai)
        self.assertIn("agc/7a16000/7a16700/7a16795", agc)

    def test_highsm_and_rbc(self):
        highsm = " ".join(_loc_tile_urls("highsm.41081"))
        rbc = " ".join(_loc_tile_urls("rbc0001.2003bit11404"))
        self.assertIn("highsm/41000/41081", highsm)
        self.assertIn("public:rbc:2003bit11404:0001", rbc)
        self.assertIn("public:rbc:2003juv23925:001", " ".join(_loc_tile_urls("rbc0001.2003juv23925")))
        self.assertIn("full/800,/", rbc)
        var = " ".join(_loc_tile_urls("var.1627"))
        self.assertIn("var/1600/1627/1627r.jpg", var)
        gott = " ".join(_loc_tile_urls("gottlieb.10861"))
        self.assertIn("musgottlieb-10861", gott)

    def test_resource_id_strips_trailing_page_index(self):
        self.assertEqual(
            _loc_resource_id("https://www.loc.gov/resource/gottlieb.10861.0"),
            "gottlieb.10861",
        )


class LocGalleryJsonTests(unittest.TestCase):
    def test_reads_content_set_items_not_sibling_sets(self):
        payload = {
            "content": {
                "title": "Architecture & Design",
                "set": {
                    "items": [
                        {
                            "title": "Carpenter Center",
                            "image": "/static/portals/free-to-use/public-domain/architecture-and-design/12845v.jpg",
                            "link": "/resource/highsm.12845/",
                        }
                    ]
                },
            },
            "next": {
                "set": {
                    "items": [
                        {"title": "Other gallery", "image": "/x.jpg", "link": "/resource/foo.1/"}
                    ]
                }
            },
        }
        items = _loc_masonry_items_from_payload(payload)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Carpenter Center")

    def test_architecture_url_slug(self):
        self.assertEqual(
            _loc_free_to_use_slug("https://www.loc.gov/free-to-use/architecture-and-design/"),
            "architecture-and-design",
        )
        self.assertEqual(_loc_set_slug_for_query("architecture"), "architecture-and-design")

    def test_free_to_use_json_url_omits_result_count(self):
        from public_domain import _loc_json_url, _loc_wayback_json_url
        u = _loc_json_url("https://www.loc.gov/free-to-use/architecture-and-design/")
        self.assertIn("fo=json", u)
        self.assertNotIn("c=80", u)
        wb = _loc_wayback_json_url("https://www.loc.gov/free-to-use/architecture-and-design/")
        self.assertIn("2id_/", wb)
        self.assertNotIn("c=80", wb)


if __name__ == "__main__":
    unittest.main()
