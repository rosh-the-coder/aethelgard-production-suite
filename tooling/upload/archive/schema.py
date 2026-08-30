"""Normalized Archive Studio schema, source registry, and rights helpers."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

SOURCE_CLEVELAND = "cleveland"
SOURCE_RIJKSMUSEUM = "rijksmuseum"
SOURCE_SMITHSONIAN = "smithsonian"
SOURCE_LOC = "loc"
SOURCE_ARTIC = "artic"
SOURCE_MET = "met"
SOURCE_EUROPEANA = "europeana"

SOURCE_ORDER = [
    SOURCE_CLEVELAND,
    SOURCE_RIJKSMUSEUM,
    SOURCE_SMITHSONIAN,
    SOURCE_LOC,
    SOURCE_ARTIC,
    SOURCE_MET,
    SOURCE_EUROPEANA,
]

SOURCES: Dict[str, Dict[str, Any]] = {
    SOURCE_CLEVELAND: {
        "id": SOURCE_CLEVELAND,
        "name": "Cleveland Museum of Art",
        "short": "Cleveland",
        "homepage": "https://www.clevelandart.org/",
        "api_docs": "https://openaccess-api.clevelandart.org/",
        "auth": "none",
        "env_key": None,
        "rights_default": "cc0",
        "notes": "Open Access CC0. No API key. Filter cc0=1 + has_image=1.",
    },
    SOURCE_RIJKSMUSEUM: {
        "id": SOURCE_RIJKSMUSEUM,
        "name": "Rijksmuseum",
        "short": "Rijksmuseum",
        "homepage": "https://www.rijksmuseum.nl/",
        "api_docs": "https://data.rijksmuseum.nl/object-metadata/api/",
        "auth": "api_key",
        "env_key": "RIJKSMUSEUM_API_KEY",
        "rights_default": "open_access",
        "notes": "Requires RIJKSMUSEUM_API_KEY. Restrict to image-bearing objects; verify rights per record.",
    },
    SOURCE_SMITHSONIAN: {
        "id": SOURCE_SMITHSONIAN,
        "name": "Smithsonian Open Access",
        "short": "Smithsonian",
        "homepage": "https://www.si.edu/openaccess",
        "api_docs": "https://api.si.edu/openaccess/api/v1.0/search",
        "auth": "api_key_optional",
        "env_key": "SMITHSONIAN_API_KEY",
        "rights_default": "cc0",
        "notes": "Uses SMITHSONIAN_API_KEY or DEMO_KEY. Prefer CC0 / Open Access media only.",
    },
    SOURCE_LOC: {
        "id": SOURCE_LOC,
        "name": "Library of Congress",
        "short": "LoC",
        "homepage": "https://www.loc.gov/",
        "api_docs": "https://www.loc.gov/apis/",
        "auth": "none",
        "env_key": None,
        "rights_default": "unclear",
        "notes": "JSON search. Rights vary — never assume public domain. Filter on rights statements.",
    },
    SOURCE_ARTIC: {
        "id": SOURCE_ARTIC,
        "name": "Art Institute of Chicago",
        "short": "Art Institute",
        "homepage": "https://www.artic.edu/",
        "api_docs": "https://api.artic.edu/docs/",
        "auth": "none",
        "env_key": None,
        "rights_default": "public_domain",
        "notes": "IIIF images. Filter is_public_domain=true.",
    },
    SOURCE_MET: {
        "id": SOURCE_MET,
        "name": "The Met",
        "short": "Met",
        "homepage": "https://www.metmuseum.org/",
        "api_docs": "https://metmuseum.github.io/",
        "auth": "none",
        "env_key": None,
        "rights_default": "public_domain",
        "notes": "Open Access objects with isPublicDomain=true. Existing Art Studio Met path is unchanged.",
    },
    SOURCE_EUROPEANA: {
        "id": SOURCE_EUROPEANA,
        "name": "Europeana",
        "short": "Europeana",
        "homepage": "https://www.europeana.eu/",
        "api_docs": "https://pro.europeana.eu/page/search",
        "auth": "api_key",
        "env_key": "EUROPEANA_API_KEY",
        "rights_default": "unclear",
        "notes": "Requires EUROPEANA_API_KEY. Filter public-domain / CC0 rights URLs.",
    },
}

RIGHTS_PUBLIC_DOMAIN = "public_domain"
RIGHTS_CC0 = "cc0"
RIGHTS_OPEN_ACCESS = "open_access"
RIGHTS_UNCLEAR = "unclear"
RIGHTS_RESTRICTED = "restricted"

RIGHTS_VALUES = (
    RIGHTS_PUBLIC_DOMAIN,
    RIGHTS_CC0,
    RIGHTS_OPEN_ACCESS,
    RIGHTS_UNCLEAR,
    RIGHTS_RESTRICTED,
)

JOB_KINDS = (
    "search_ingest",
    "thumbnail_sync",
    "fullres_download",
    "image_prep",
    "drive_sync",
    "pipeline_handoff",
    "dedupe_scan",
    "rule_run",
)

JOB_STATUSES = ("queued", "running", "paused", "done", "failed", "cancelled")

PROCESSING_STATUSES = (
    "metadata",
    "thumb_cached",
    "fullres_ready",
    "prepped",
    "qc_flagged",
    "approved",
)

QC_FLAGS = (
    "missing_image",
    "insufficient_resolution",
    "wrong_orientation",
    "unclear_rights",
    "corrupted_download",
    "metadata_incomplete",
    "not_wall_art",
    "possible_duplicate",
)

IMAGE_HOST_ALLOWLIST = (
    "clevelandart.org",
    "artic.edu",
    "metmuseum.org",
    "images.metmuseum.org",
    "loc.gov",
    "tile.loc.gov",
    "rijksmuseum.nl",
    "lh3.googleusercontent.com",
    "si.edu",
    "ids.si.edu",
    "n2t.net",
    "europeana.eu",
    "europeanastatic.eu",
    "wikimedia.org",
    "wikipedia.org",
    "wikimedia.org",
    "upload.wikimedia.org",
    "iiif.si.edu",
    "edan.si.edu",
    "images.nga.gov",
)


@dataclass
class NormalizedRecord:
    source: str
    source_object_id: str
    source_url: str = ""
    source_image_url: str = ""
    thumbnail_url: str = ""
    title: str = ""
    artist: str = ""
    year: str = ""
    date_display: str = ""
    description: str = ""
    rights_status: str = RIGHTS_UNCLEAR
    licence_type: str = ""
    is_public_domain: bool = False
    media_type: str = ""
    medium: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    orientation: str = "unknown"
    categories: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    theme: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def classify_orientation(width: Optional[int], height: Optional[int]) -> str:
    if not width or not height:
        return "unknown"
    if width == height:
        return "square"
    return "landscape" if width > height else "portrait"


def classify_rights(text: str, *, is_public_domain: Optional[bool] = None) -> str:
    blob = (text or "").lower()
    if is_public_domain is True:
        if "cc0" in blob or "cc zero" in blob or "cc-zero" in blob or "zero/1.0" in blob:
            return RIGHTS_CC0
        return RIGHTS_PUBLIC_DOMAIN
    if "restricted" in blob or "in copyright" in blob or "all rights reserved" in blob:
        return RIGHTS_RESTRICTED
    if "cc0" in blob or "cc zero" in blob or "cc-zero" in blob or "zero/1.0" in blob:
        return RIGHTS_CC0
    if "public domain" in blob or "publicdomain/mark" in blob or "pdm" in blob:
        return RIGHTS_PUBLIC_DOMAIN
    if "open access" in blob or "no known copyright" in blob or "no restrictions" in blob:
        return RIGHTS_OPEN_ACCESS
    if is_public_domain is False:
        return RIGHTS_RESTRICTED
    return RIGHTS_UNCLEAR


def rights_is_clear_reuse(status: str) -> bool:
    return status in (RIGHTS_PUBLIC_DOMAIN, RIGHTS_CC0)


def first_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        for item in value:
            text = first_text(item)
            if text:
                return text
        return ""
    if isinstance(value, dict):
        for key in ("content", "title", "label", "value", "name", "text"):
            if key in value:
                text = first_text(value[key])
                if text:
                    return text
        return ""
    return str(value).strip()


def year_from_text(text: str) -> str:
    import re

    m = re.search(r"\b(1[0-9]{3}|20[0-2][0-9])\b", text or "")
    return m.group(1) if m else ""
