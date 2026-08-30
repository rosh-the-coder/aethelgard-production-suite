"""Quality-control flags for archive assets."""
from __future__ import annotations

from typing import List

from .schema import rights_is_clear_reuse

WALL_ART_NOISE = (
    "coin", "sculpture", "statue", "vessel", "jar", "bowl", "vase", "armor",
    "helmet", "sword", "dagger", "furniture", "chair", "table", "textile fragment",
    "shard", "fragment of", "architectural fragment",
)


def evaluate(asset: dict, *, min_width: int = 1200, min_height: int = 1200, expected_orientation: str = "") -> List[str]:
    flags: List[str] = []
    image = asset.get("source_image_url") or asset.get("local_file_path")
    if not image:
        flags.append("missing_image")
    width = int(asset.get("width") or 0)
    height = int(asset.get("height") or 0)
    if asset.get("local_file_path") or (width and height):
        if width and width < min_width and height and height < min_height:
            flags.append("insufficient_resolution")
        elif width and height and max(width, height) < min_width:
            flags.append("insufficient_resolution")
    if expected_orientation and asset.get("orientation") not in ("unknown", expected_orientation, ""):
        flags.append("wrong_orientation")
    if not rights_is_clear_reuse(asset.get("rights_status") or ""):
        flags.append("unclear_rights")
    title = (asset.get("title") or "").strip()
    artist = (asset.get("artist") or "").strip()
    if not title or title.lower() in ("untitled", "unknown"):
        flags.append("metadata_incomplete")
    elif not artist:
        flags.append("metadata_incomplete")
    blob = " ".join(
        [
            title,
            asset.get("medium") or "",
            asset.get("media_type") or "",
            " ".join(asset.get("tags") or []),
        ]
    ).lower()
    if any(term in blob for term in WALL_ART_NOISE):
        flags.append("not_wall_art")
    if asset.get("duplicate_of"):
        flags.append("possible_duplicate")
    # unique preserve order
    seen = set()
    out = []
    for flag in flags:
        if flag not in seen:
            seen.add(flag)
            out.append(flag)
    return out
