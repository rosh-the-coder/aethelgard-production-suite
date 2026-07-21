"""
Detect empty frame openings (white/cream mat areas) in mockup photos.
Returns perspective quads [TL, TR, BR, BL] in image pixel coordinates.
"""
from __future__ import annotations

import io
import base64
from typing import List, Tuple

import cv2
import numpy as np
from PIL import Image


def _order_quad_points(pts: np.ndarray) -> np.ndarray:
    pts = np.array(pts, dtype=np.float32).reshape(4, 2)
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).reshape(-1)
    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]
    tr = pts[np.argmin(diff)]
    bl = pts[np.argmax(diff)]
    return np.array([tl, tr, br, bl], dtype=np.float32)


def _bbox_iou(a: np.ndarray, b: np.ndarray) -> float:
    ax1, ay1 = a.min(axis=0)
    ax2, ay2 = a.max(axis=0)
    bx1, by1 = b.min(axis=0)
    bx2, by2 = b.max(axis=0)
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    area_a = max(1.0, (ax2 - ax1) * (ay2 - ay1))
    area_b = max(1.0, (bx2 - bx1) * (by2 - by1))
    return inter / (area_a + area_b - inter)


def _nms(candidates: list, iou_thresh: float = 0.38) -> list:
    candidates = sorted(candidates, key=lambda c: c["area"], reverse=True)
    kept = []
    for c in candidates:
        if all(_bbox_iou(c["quad"], k["quad"]) < iou_thresh for k in kept):
            kept.append(c)
    return kept


def _load_bgr(source) -> Tuple[np.ndarray, float]:
    """Load BGR array; downscale large images for speed. Returns (img, scale)."""
    if isinstance(source, str):
        img = cv2.imread(source)
        if img is None:
            raise ValueError(f"Could not read image: {source}")
    elif isinstance(source, Image.Image):
        rgb = np.array(source.convert("RGB"))
        img = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    elif isinstance(source, np.ndarray):
        img = source.copy()
    else:
        raise TypeError("source must be path, PIL Image, or ndarray")

    h, w = img.shape[:2]
    max_dim = 2400
    scale = 1.0
    if max(h, w) > max_dim:
        scale = max_dim / float(max(h, w))
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    return img, scale


def _mat_mask_white(img: np.ndarray) -> np.ndarray:
    b, g, r = cv2.split(img)
    rgb_min = cv2.min(cv2.min(r, g), b)
    rgb_max = cv2.max(cv2.max(r, g), b)
    rgb_delta = cv2.subtract(rgb_max, rgb_min)
    mask = cv2.inRange(rgb_min, 196, 255)
    mask = cv2.bitwise_and(mask, cv2.inRange(rgb_delta, 0, 32))
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.bitwise_and(mask, cv2.inRange(hsv, (0, 0, 205), (180, 45, 255)))
    return _refine_mask(mask)


def _mat_mask_cream(img: np.ndarray) -> np.ndarray:
    b, g, r = cv2.split(img)
    rgb_min = cv2.min(cv2.min(r, g), b)
    rgb_max = cv2.max(cv2.max(r, g), b)
    rgb_delta = cv2.subtract(rgb_max, rgb_min)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 0, 155), (180, 75, 255))
    mask = cv2.bitwise_and(mask, cv2.inRange(rgb_min, 125, 228))
    mask = cv2.bitwise_and(mask, cv2.inRange(rgb_delta, 0, 52))
    return _refine_mask(mask, erode_px=5)


def _refine_mask(mask: np.ndarray, erode_px: int = 4) -> np.ndarray:
    k_close = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    k_open = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k_close, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k_open, iterations=1)
    k_erode = cv2.getStructuringElement(cv2.MORPH_RECT, (erode_px, erode_px))
    eroded = cv2.erode(mask, k_erode, iterations=1)
    return cv2.dilate(eroded, k_erode, iterations=1)


def _collect_candidates(img: np.ndarray, mask: np.ndarray, min_area: float, max_area: float) -> list:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < min_area or area > max_area:
            continue
        quad, rw, rh, aspect = _contour_to_quad(cnt)
        if min(rw, rh) < 12 or aspect < 0.30:
            continue
        box = cv2.boundingRect(cnt)
        if area / max(1.0, box[2] * box[3]) < 0.45:
            continue
        if _mean_brightness_inside(img, quad) < 168:
            continue
        candidates.append({
            "quad": quad,
            "area": area,
            "centroid": quad.mean(axis=0),
            "span_x": float(quad[:, 0].max() - quad[:, 0].min()),
        })
    return candidates


def _mean_brightness_inside(img: np.ndarray, quad: np.ndarray) -> float:
    h, w = img.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    cv2.fillConvexPoly(mask, quad.astype(np.int32), 255)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    vals = gray[mask == 255]
    if vals.size == 0:
        return 0.0
    return float(vals.mean())


def _warp_quad_patch(img: np.ndarray, quad: np.ndarray, out_w: int = 280, out_h: int = 350) -> np.ndarray:
    src = quad.astype(np.float32)
    dst = np.array([[0, 0], [out_w, 0], [out_w, out_h], [0, out_h]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(img, matrix, (out_w, out_h))


def _map_patch_point_to_image(pt, quad: np.ndarray, out_w: int, out_h: int) -> np.ndarray:
    src = quad.astype(np.float32)
    dst = np.array([[0, 0], [out_w, 0], [out_w, out_h], [0, out_h]], dtype=np.float32)
    inv = cv2.getPerspectiveTransform(dst, src)
    p = np.array([[[float(pt[0]), float(pt[1])]]], dtype=np.float32)
    mapped = cv2.perspectiveTransform(p, inv)[0, 0]
    return mapped


def _estimate_mat_inset_ratio(patch_bgr: np.ndarray) -> float:
    """
    Find inner art opening inside a white mat by detecting the mat lip shadow.
    Returns inset fraction (0.0 = none, 0.12 = 12% shrink toward center).
    """
    gray = cv2.cvtColor(patch_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    h, w = gray.shape
    if h < 40 or w < 40:
        return 0.0

    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    lap = cv2.Laplacian(blur, cv2.CV_32F)
    lap = np.abs(lap)

    def scan_edge(axis: str) -> float | None:
        depth = int((h if axis in ("top", "bottom") else w) * 0.22)
        depth = max(8, depth)
        scores = []
        positions = []
        if axis == "top":
            for y in range(2, depth):
                scores.append(float(lap[y, int(w * 0.15) : int(w * 0.85)].mean()))
                positions.append(y / h)
        elif axis == "bottom":
            for y in range(h - depth, h - 2):
                scores.append(float(lap[y, int(w * 0.15) : int(w * 0.85)].mean()))
                positions.append((h - y) / h)
        elif axis == "left":
            for x in range(2, depth):
                scores.append(float(lap[int(h * 0.15) : int(h * 0.85), x].mean()))
                positions.append(x / w)
        else:  # right
            for x in range(w - depth, w - 2):
                scores.append(float(lap[int(h * 0.15) : int(h * 0.85), x].mean()))
                positions.append((w - x) / w)
        if not scores:
            return None
        peak = int(np.argmax(scores))
        if scores[peak] < 2.5:
            return None
        return positions[peak]

    edges = [scan_edge(a) for a in ("top", "bottom", "left", "right")]
    valid = [e for e in edges if e is not None and 0.02 < e < 0.22]
    if len(valid) < 3:
        return 0.0
    inset = float(np.median(valid))
    # Consistent mat lips on at least 3 sides
    if np.std(valid) > 0.04:
        return 0.0
    return max(0.0, min(0.18, inset * 0.92))


def _inset_quad(quad: np.ndarray, ratio: float) -> np.ndarray:
    if ratio <= 0.001:
        return quad
    cx = float(quad[:, 0].mean())
    cy = float(quad[:, 1].mean())
    out = []
    for p in quad:
        out.append([p[0] + (cx - p[0]) * ratio, p[1] + (cy - p[1]) * ratio])
    return np.array(out, dtype=np.float32)


def refine_quad_to_art_opening(img: np.ndarray, quad: np.ndarray) -> np.ndarray:
    """Shrink detection from outer mat to inner art area when a mat lip is visible."""
    out_w, out_h = 280, 350
    patch = _warp_quad_patch(img, quad, out_w, out_h)
    inset = _estimate_mat_inset_ratio(patch)
    if inset < 0.025:
        return quad
    return _inset_quad(quad, inset)


def _contour_to_quad(cnt) -> Tuple[np.ndarray, float, float]:
    """Fit a perspective quad + aspect ratio from contour."""
    rect = cv2.minAreaRect(cnt)
    (rw, rh) = rect[1]
    if rw < rh:
        rw, rh = rh, rw
    aspect = (rh / rw) if rw > 0 else 0.0
    quad = cv2.boxPoints(rect).astype(np.float32)
    quad = _order_quad_points(quad)
    return quad, rw, rh, aspect


def detect_frame_quads(source, min_frames: int = 1, max_frames: int = 36) -> List[List[List[int]]]:
    """
    Detect frame opening quads in a mockup image.
    Returns list of quads as [[x,y], ...] × 4 corners (TL, TR, BR, BL).
    """
    img, scale = _load_bgr(source)
    img_area = img.shape[0] * img.shape[1]
    min_area = img_area * 0.00045
    max_area = img_area * 0.48

    candidates = []
    for mask_fn in (_mat_mask_white, _mat_mask_cream):
        candidates.extend(_collect_candidates(img, mask_fn(img), min_area, max_area))

    candidates = _nms(candidates, iou_thresh=0.40)

    img_w = img.shape[1]
    # Drop wall-bleed mega blobs (merged plaster + mats)
    filtered = []
    for c in candidates:
        if c["area"] > img_area * 0.18 and c.get("span_x", 0) > img_w * 0.62:
            continue
        filtered.append(c)
    candidates = filtered or candidates

    if candidates:
        areas = sorted([c["area"] for c in candidates], reverse=True)
        max_a, second_a = areas[0], areas[1] if len(areas) > 1 else 0
        large = sorted(
            [c for c in candidates if c["area"] > img_area * 0.08],
            key=lambda c: c["area"],
            reverse=True,
        )
        # Single frame + one false blob (linen, reflection)
        if len(large) == 2 and large[0]["area"] > large[1]["area"] * 1.42:
            candidates = [large[0]]
        elif max_a > img_area * 0.10 and second_a < max_a * 0.38:
            candidates = [c for c in candidates if c["area"] >= max_a * 0.48]
        elif len(candidates) >= 3:
            median_a = areas[len(areas) // 2]
            floor = max(min_area * 1.2, median_a * 0.22)
            candidates = [c for c in candidates if c["area"] >= floor]

    # Reading order: banded rows then left-to-right
    row_h = img.shape[0] * 0.07
    candidates.sort(key=lambda c: (int(c["centroid"][1] / row_h), c["centroid"][0]))

    if len(candidates) > max_frames:
        candidates = candidates[:max_frames]

    if len(candidates) < min_frames:
        return []

    inv = 1.0 / scale if scale else 1.0
    out = []
    for c in candidates:
        q = c["quad"]
        q = refine_quad_to_art_opening(img, q)
        q = (q * inv).astype(np.int32)
        out.append([[int(p[0]), int(p[1])] for p in q])
    return out


def detect_from_base64(image_b64: str) -> dict:
    raw = base64.b64decode(image_b64)
    pil = Image.open(io.BytesIO(raw)).convert("RGB")
    quads = detect_frame_quads(pil)
    return {"success": len(quads) > 0, "count": len(quads), "quads": quads}


if __name__ == "__main__":
    import os
    import sys

    here = os.path.dirname(os.path.abspath(__file__))
    name = sys.argv[1] if len(sys.argv) > 1 else "japandi_single_shelf_pampas_4x5_b.png"
    path = os.path.join(here, "templates", name)
    quads = detect_frame_quads(path)
    print(f"{name}: {len(quads)} frames")
