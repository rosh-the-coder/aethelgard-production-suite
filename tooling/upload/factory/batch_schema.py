"""Batch spreadsheet schema and allowed values."""
from __future__ import annotations

from typing import Dict, List, Set

COLUMNS: List[str] = [
    "listing_id",
    "artwork_id",
    "listing_name",
    "artwork_title",
    "concept",
    "acquisition_mode",
    "style_preset",
    "orientation",
    "aspect_ratio",
    "generation_model",
    "artwork_count",
    "product_type",
    "listing_title",
    "description_notes",
    "tags",
    "price_eur",
    "mockup_preset",
    "delivery_type",
    "notes",
    "selection_policy",
]

ACQUISITION_MODES: Set[str] = {"ai", "public_domain", "graphic_poster"}
ORIENTATIONS: Set[str] = {"portrait", "landscape", "square"}
ASPECT_RATIOS: Set[str] = {"4:5", "3:2", "1:1", "2:3", "5:4"}
PRODUCT_TYPES: Set[str] = {"single", "bundle", "poster", "public_domain_pack", "graphic_poster", "pd_bundle"}
DELIVERY_TYPES: Set[str] = {"digital_files", "drive_pdf"}
SELECTION_POLICIES: Set[str] = {"first_success", "manual_review"}

STYLE_PRESETS: Set[str] = {
    "tonal_oil",
    "japandi",
    "botanical",
    "moody_coastal",
    "dark_academia",
    "graphic_poster",
    "custom",
}

MODEL_ALIASES: Dict[str, str] = {
    "cf-sdxl-lightning": "cf-sdxl-lightning",
    "cf-dreamshaper": "cf-dreamshaper",
    "cf-sdxl": "cf-sdxl",
    "nano-banana-pro": "nano-banana-pro",
    "nano-banana-2": "nano-banana-2",
    "sdxl": "cf-sdxl",
    "dreamshaper": "cf-dreamshaper",
    "lightning": "cf-sdxl-lightning",
    "gemini": "nano-banana-pro",
}

EXAMPLE_ROWS: List[Dict[str, str]] = [
    {
        "listing_id": "listing_owl_01",
        "artwork_id": "owl_a",
        "listing_name": "Moody Owl Print",
        "artwork_title": "Barn Owl Study",
        "concept": "moody gothic barn owl in ancient library candlelight",
        "acquisition_mode": "ai",
        "style_preset": "dark_academia",
        "orientation": "portrait",
        "aspect_ratio": "4:5",
        "generation_model": "cf-sdxl",
        "artwork_count": "1",
        "product_type": "single",
        "listing_title": "Moody Barn Owl Dark Academia Print",
        "description_notes": "Emphasise atmosphere and library setting",
        "tags": "owl,dark academia,library,printable wall art",
        "price_eur": "2.99",
        "mockup_preset": "",
        "delivery_type": "drive_pdf",
        "notes": "Example row",
        "selection_policy": "first_success",
    },
    {
        "listing_id": "listing_owl_01",
        "artwork_id": "owl_b",
        "listing_name": "Moody Owl Print",
        "artwork_title": "Owl Alternate Angle",
        "concept": "close portrait of barn owl feathers chiaroscuro",
        "acquisition_mode": "ai",
        "style_preset": "dark_academia",
        "orientation": "portrait",
        "aspect_ratio": "4:5",
        "generation_model": "cf-sdxl",
        "artwork_count": "1",
        "product_type": "bundle",
        "listing_title": "Moody Barn Owl Dark Academia Print",
        "description_notes": "Bundle companion piece",
        "tags": "owl,dark academia,printable wall art",
        "price_eur": "2.99",
        "mockup_preset": "",
        "delivery_type": "drive_pdf",
        "notes": "Same listing_id → one bundled listing",
        "selection_policy": "first_success",
    },
]

INSTRUCTIONS_TEXT = """Aethelgard Batch Production Template
====================================

ONE ROW = ONE ARTWORK REQUEST
Rows that share the same listing_id belong to one bundled listing.

QUOTA
- Maximum 20 artwork outputs per local calendar day.
- Total artwork count = sum of artwork_count across all rows.
- Quota is consumed when a valid batch is accepted (not on file upload).
- Provider retries do not consume extra quota.

REQUIRED FIELDS
- listing_id (always)
- concept (required for ai and graphic_poster)

ACQUISITION MODES
- ai
- public_domain
- graphic_poster
(Do not put batch inside batch.)

SELECTION POLICY
- first_success — use the first successful output when one artwork is requested
- manual_review — pause for human selection when multiple candidates exist
Default: manual_review when more than one candidate is requested for one artwork.

ETSY
- Batch processing may create Etsy DRAFT listings only.
- Never auto-publish.
- Human review is required before publish.

DELIVERY TYPES
- digital_files
- drive_pdf

Fill the Batch Input sheet, then upload in Artwork Studio → Batch Production.
"""
