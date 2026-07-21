import os
import sys
import json
import math
from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_JSON = os.path.join(HERE, "templates.json")
# Etsy listing images look best at ~2000px wide; compositing at this size is 4× faster than 4K.
OUTPUT_MIN_WIDTH = 2048
COMPOSITE_MAX_WIDTH = 2048

from image_sanitize import sanitize_master, scan_image_quality, normalize_trim_pct

SIZE_TO_ASPECT = {
    "4x6": "2:3",
    "5x7": "5:7",
    "8x10": "4:5",
    "11x14": "11:14",
    "12x9": "4:3",
    "20x16": "5:4",
    "24x18": "4:3",
    "36x24": "3:2",
    "A2": "A2"
}

def find_coefficients(source_pts, target_pts):
    """
    Calculate perspective coefficients to map source points to target points.
    Solves A * x = B using Gaussian elimination with partial pivoting.
    """
    matrix = []
    for i in range(4):
        x_s, y_s = source_pts[i]
        x_t, y_t = target_pts[i]
        matrix.append([x_t, y_t, 1, 0, 0, 0, -x_t * x_s, -y_t * x_s, x_s])
        matrix.append([0, 0, 0, x_t, y_t, 1, -x_t * y_s, -y_t * y_s, y_s])
    
    n = 8
    for i in range(n):
        # Pivot search
        max_row = i
        for r in range(i + 1, n):
            if abs(matrix[r][i]) > abs(matrix[max_row][i]):
                max_row = r
        matrix[i], matrix[max_row] = matrix[max_row], matrix[i]
        
        # Elimination
        for r in range(i + 1, n):
            factor = matrix[r][i] / matrix[i][i]
            for c in range(i, n + 1):
                matrix[r][c] -= factor * matrix[i][c]
                
    # Back substitution
    coeffs = [0] * n
    for i in range(n - 1, -1, -1):
        sum_vals = sum(matrix[i][j] * coeffs[j] for j in range(i + 1, n))
        coeffs[i] = (matrix[i][n] - sum_vals) / matrix[i][i]
        
    return coeffs

def generate_zoom_gif(mockup_img, left, top, right, bottom, out_path):
    """
    Generate a slow-paced close-up pan GIF showing different angles/details of the artwork,
    preserving room lighting/textures.
    """
    try:
        # Determine center of the frame
        cx = (left + right) // 2
        cy = (top + bottom) // 2
        
        frame_w = right - left
        frame_h = bottom - top
        max_box = max(frame_w, frame_h)
        
        # Close-up box size (constant, zoomed in to 1.25x of the frame box size for detail)
        box_size = int(max_box * 1.25)
        
        # Bounds checking for max box size
        box_size = min(box_size, mockup_img.width, mockup_img.height)
        
        # Define a slow diagonal camera pan path (from bottom-left detail to top-right detail)
        # Shift the crop center slowly across 12% of the frame dimensions
        shift_w = int(frame_w * 0.12)
        shift_h = int(frame_h * 0.12)
        
        start_cx = cx - shift_w
        start_cy = cy + shift_h
        
        end_cx = cx + shift_w
        end_cy = cy - shift_h
        
        frames = []
        steps = 15  # Smooth pan — fewer frames for faster regen
        
        for i in range(steps):
            # Sinusoidal easing for ultra-smooth dolly glide acceleration and deceleration
            t = i / (steps - 1)
            import math
            ease_t = (1 - math.cos(t * math.pi)) / 2
            
            # Interpolate current camera center
            cur_cx = int(start_cx + (end_cx - start_cx) * ease_t)
            cur_cy = int(start_cy + (end_cy - start_cy) * ease_t)
            
            # Calculate crop box coordinates
            x1 = cur_cx - box_size // 2
            y1 = cur_cy - box_size // 2
            x2 = x1 + box_size
            y2 = y1 + box_size
            
            # Boundary checks
            if x1 < 0:
                x2 -= x1
                x1 = 0
            if y1 < 0:
                y2 -= y1
                y1 = 0
            if x2 > mockup_img.width:
                x1 -= (x2 - mockup_img.width)
                x2 = mockup_img.width
            if y2 > mockup_img.height:
                y1 -= (y2 - mockup_img.height)
                y2 = mockup_img.height
                
            cropped = mockup_img.crop((x1, y1, x2, y2))
            resized = cropped.resize((800, 800), Image.Resampling.LANCZOS)
            frames.append(resized)
            
        # Reverse animation to pan back smoothly to the starting position (seamless loop)
        looping_frames = frames + frames[-2:0:-1]
        
        # Save as animated GIF with 80ms delay (approx 12.5 FPS, slow-paced and premium)
        looping_frames[0].save(
            out_path,
            save_all=True,
            append_images=looping_frames[1:],
            duration=80,
            loop=0
        )
        print(f"  Successfully saved animated pan-and-scan GIF -> {out_path}")
        return True
    except Exception as e:
        print(f"  Warning: Zoom GIF generation failed: {e}")
        return False

def gather_run_prints(piece_dir, prints_dir, count=3):
    """
    Gather up to `count` unique print images for multi-frame mockup rendering.
    Prioritizes:
      1. Candidate variations from the run's _candidates directory (faithful/signature/wildcard)
      2. Sibling finalized prints in the same run
      3. Active piece JPEGs
      4. Duplicate active print only as last resort
    """
    run_prints = []
    parent_dir = os.path.dirname(piece_dir)

    def add(path):
        if path and os.path.exists(path) and path not in run_prints:
            run_prints.append(path)

    label_rank = {"faithful": 0, "signature": 1, "wildcard": 2}

    def label_score(path):
        base = os.path.basename(path).lower()
        for label, rank in label_rank.items():
            if label in base:
                return rank
        return 99

    # 1. Candidate variations — best for gallery-wall previews of one generation run
    candidates_dir = os.path.join(parent_dir, "_candidates")
    if os.path.exists(candidates_dir):
        cands = [
            os.path.join(candidates_dir, f)
            for f in os.listdir(candidates_dir)
            if f.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
        ]
        cands.sort(key=lambda p: (label_score(p), p))
        for c in cands:
            add(c)
            if len(run_prints) >= count:
                return run_prints[:count]

    # 2. Sibling finalized pieces in the same run
    if os.path.exists(parent_dir):
        for name in sorted(os.listdir(parent_dir)):
            if name.startswith("_"):
                continue
            sib_path = os.path.join(parent_dir, name)
            if not os.path.isdir(sib_path) or sib_path == piece_dir:
                continue
            found = False
            for sub in os.listdir(sib_path):
                sub_p = os.path.join(sib_path, sub)
                if not os.path.isdir(sub_p):
                    continue
                if "print" in sub.lower() or sub.lower() == "prints":
                    jpgs = [
                        os.path.join(sub_p, f)
                        for f in os.listdir(sub_p)
                        if f.lower().endswith((".jpg", ".jpeg", ".png"))
                    ]
                    if jpgs:
                        jpgs.sort(key=lambda p: ("8x10" in p or "8x10" in os.path.basename(p)), reverse=True)
                        add(jpgs[0])
                        found = True
                        break
            if not found:
                master = os.path.join(sib_path, "master.png")
                if os.path.exists(master):
                    add(master)
            if len(run_prints) >= count:
                return run_prints[:count]

    # 3. Active piece prints — prefer upscaled master over cropped JPEGs
    master = os.path.join(piece_dir, "master.png")
    if os.path.exists(master):
        add(master)

    active_jpgs = []
    if prints_dir and os.path.exists(prints_dir):
        active_jpgs = [
            os.path.join(prints_dir, f)
            for f in os.listdir(prints_dir)
            if f.lower().endswith((".jpg", ".jpeg", ".png"))
        ]
        active_jpgs.sort(key=lambda p: ("8x10" in p or "8x10" in os.path.basename(p)), reverse=True)
        if active_jpgs:
            add(active_jpgs[0])

    # 4. Fallback — duplicate active print to fill remaining slots
    while len(run_prints) < count:
        if active_jpgs:
            run_prints.append(active_jpgs[0])
        elif run_prints:
            run_prints.append(run_prints[0])
        else:
            break

    return run_prints[:count]


def list_bundle_images(piece_dir, max_count=200):
    """All images in the run available for gallery-wall assignment."""
    images = []
    seen = set()
    parent_dir = os.path.dirname(piece_dir)

    def add(path, label=""):
        if not path or not os.path.exists(path):
            return
        norm = os.path.normcase(os.path.abspath(path))
        if norm in seen:
            return
        seen.add(norm)
        images.append({
            "path": path,
            "name": os.path.basename(path),
            "label": label or os.path.basename(os.path.dirname(path)),
        })

    candidates_dir = os.path.join(parent_dir, "_candidates")
    if os.path.exists(candidates_dir):
        for fname in sorted(os.listdir(candidates_dir)):
            if fname.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                add(os.path.join(candidates_dir, fname), "candidate")

    if os.path.exists(parent_dir):
        for name in sorted(os.listdir(parent_dir)):
            if name.startswith("_"):
                continue
            sib_path = os.path.join(parent_dir, name)
            if not os.path.isdir(sib_path):
                continue
            add(os.path.join(sib_path, "master.png"), name)
            for sub in os.listdir(sib_path):
                sub_p = os.path.join(sib_path, sub)
                if os.path.isdir(sub_p) and ("print" in sub.lower() or sub.lower() == "prints"):
                    for fname in sorted(os.listdir(sub_p)):
                        if fname.lower().endswith((".jpg", ".jpeg", ".png")):
                            add(os.path.join(sub_p, fname), name)

    add(os.path.join(piece_dir, "master.png"), os.path.basename(piece_dir))
    prints_dir = None
    for sub in os.listdir(piece_dir):
        sub_p = os.path.join(piece_dir, sub)
        if os.path.isdir(sub_p) and ("print" in sub.lower() or sub.lower() == "prints"):
            prints_dir = sub_p
            break
    if prints_dir:
        for fname in sorted(os.listdir(prints_dir)):
            if fname.lower().endswith((".jpg", ".jpeg", ".png")):
                add(os.path.join(prints_dir, fname), os.path.basename(piece_dir))

    bundle_dir = meta_bundle_dir(piece_dir)
    if bundle_dir:
        for root, _dirs, files in os.walk(bundle_dir):
            for fname in sorted(files):
                if fname.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    add(os.path.join(root, fname), "bundle")

    return images[:max_count]


def meta_bundle_dir(piece_dir):
    meta_path = os.path.join(piece_dir, "meta.json")
    if not os.path.exists(meta_path):
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        bundle = meta.get("bundle_dir") or meta.get("bundle_images_dir")
        if bundle and os.path.isdir(bundle):
            return bundle
    except Exception:
        pass
    for name in ("bundle", "bundle_images", "images"):
        candidate = os.path.join(os.path.dirname(piece_dir), name)
        if os.path.isdir(candidate):
            return candidate
    return None


def image_aspect(path):
    with Image.open(path) as im:
        w, h = im.size
    return w / float(h) if h else 1.0


def quad_bounds(quad):
    xs = [p[0] for p in quad]
    ys = [p[1] for p in quad]
    return min(xs), min(ys), max(xs), max(ys)


def quad_frame_aspect(quad):
    left, top, right, bottom = quad_bounds(quad)
    fw = max(1.0, right - left)
    fh = max(1.0, bottom - top)
    return fw / fh


def fit_print_cover_crop(print_img, quad, pan_x=0.0, pan_y=0.0, zoom=1.0):
    """
    Crop print to cover the frame opening aspect — no stretch before perspective warp.
    pan_x/pan_y: -1..1 within crop slack. zoom: 1 = minimum cover, >1 zooms in.
    """
    pw, ph = print_img.size
    target_aspect = quad_frame_aspect(quad)
    src_aspect = pw / float(ph) if ph else 1.0

    if src_aspect > target_aspect:
        crop_h = ph
        crop_w = max(1, int(round(ph * target_aspect)))
    else:
        crop_w = pw
        crop_h = max(1, int(round(pw / target_aspect)))

    zoom = max(0.35, float(zoom))
    crop_w = max(1, min(pw, int(round(crop_w / zoom))))
    crop_h = max(1, min(ph, int(round(crop_h / zoom))))

    slack_x = max(0, pw - crop_w)
    slack_y = max(0, ph - crop_h)
    pan_x = max(-1.0, min(1.0, float(pan_x)))
    pan_y = max(-1.0, min(1.0, float(pan_y)))
    x0 = int((pw - crop_w) / 2 + pan_x * slack_x / 2)
    y0 = int((ph - crop_h) / 2 + pan_y * slack_y / 2)
    x0 = max(0, min(pw - crop_w, x0))
    y0 = max(0, min(ph - crop_h, y0))
    return print_img.crop((x0, y0, x0 + crop_w, y0 + crop_h))


def normalize_placement(placement):
    if not placement:
        return {"pan_x": 0.0, "pan_y": 0.0, "zoom": 1.0}
    return {
        "pan_x": float(placement.get("pan_x", 0.0)),
        "pan_y": float(placement.get("pan_y", 0.0)),
        "zoom": max(0.35, float(placement.get("zoom", 1.0))),
    }


def assign_prints_to_quads(print_paths, quads):
    """Match images to frame openings by aspect ratio (portrait→portrait, etc.)."""
    n = len(quads)
    if n == 0:
        return []
    pool = [p for p in print_paths if p]
    if not pool:
        return []
    while len(pool) < n:
        pool.append(pool[len(pool) % len(print_paths)])

    frame_aspects = [quad_frame_aspect(q) for q in quads]
    img_aspects = [image_aspect(p) for p in pool]
    used = set()
    assignments = [None] * n
    order = sorted(range(n), key=lambda i: abs(math.log(frame_aspects[i])), reverse=True)

    for fi in order:
        best_j = None
        best_score = 1e9
        for j, _path in enumerate(pool):
            if j in used:
                continue
            score = abs(math.log(img_aspects[j] / frame_aspects[fi]))
            if score < best_score:
                best_score = score
                best_j = j
        if best_j is None:
            best_j = fi % len(pool)
        used.add(best_j)
        assignments[fi] = pool[best_j]

    for i in range(n):
        if assignments[i] is None:
            assignments[i] = pool[i % len(pool)]
    return assignments


def resolve_print_path(piece_dir, image_ref):
    if not image_ref:
        return None
    if os.path.isabs(image_ref) and os.path.exists(image_ref):
        return image_ref
    candidate = os.path.join(piece_dir, image_ref)
    if os.path.exists(candidate):
        return candidate
    parent = os.path.dirname(piece_dir)
    candidate = os.path.join(parent, image_ref)
    if os.path.exists(candidate):
        return candidate
    for img in list_bundle_images(piece_dir, max_count=500):
        if img["path"] == image_ref or img["name"] == image_ref:
            return img["path"]
        if os.path.basename(img["path"]) == os.path.basename(str(image_ref)):
            return img["path"]
    return None


def inset_quad(quad, inset=2.5):
    """Positive inset shrinks; negative inset expands the quad outward."""
    cx = sum(p[0] for p in quad) / 4.0
    cy = sum(p[1] for p in quad) / 4.0
    out = []
    for x, y in quad:
        dx, dy = x - cx, y - cy
        dist = (dx * dx + dy * dy) ** 0.5 or 1.0
        out.append((x - inset * dx / dist, y - inset * dy / dist))
    return out


def masked_mean_luminance(lum_img, mask):
    bbox = mask.getbbox()
    if not bbox:
        return 220.0
    patch_lum = lum_img.crop(bbox)
    patch_mask = mask.crop(bbox)
    hist = patch_lum.histogram(mask=patch_mask)
    total = sum(hist)
    if total <= 0:
        return 220.0
    return sum(i * hist[i] for i in range(256)) / total


def build_antialiased_mask(size, quad, edge_expand=4.0, ss=4):
    """Supersampled polygon mask — clean edges without stair-steps."""
    w, h = size
    sw, sh = w * ss, h * ss
    big_quad = [(p[0] * ss, p[1] * ss) for p in quad]
    expanded = inset_quad([tuple(p) for p in big_quad], inset=-edge_expand * ss)
    mask = Image.new("L", (sw, sh), 0)
    ImageDraw.Draw(mask).polygon(expanded, fill=255)
    return mask.resize((w, h), Image.Resampling.LANCZOS)


def build_luminance_ratio_map(scene, quad, size, gain=4.5):
    """Boosted luminance map for Multiply blend (Photoshop clipped multiply layer)."""
    lum = scene.convert("L")
    inner = build_antialiased_mask(size, quad, edge_expand=-1.0, ss=2)
    mean = masked_mean_luminance(lum, inner)
    if mean < 1:
        mean = 220.0

    def ratio_value(p):
        boosted = mean + (p - mean) * gain
        return max(35, min(255, int(boosted)))

    boosted = lum.point(ratio_value)
    return Image.merge("RGB", (boosted, boosted, boosted))


def extract_specular_layer(scene_rgb, quad, size, blur_radius=22, boost=2.4):
    """Glass glare / window reflections from empty template → Screen on top of art."""
    mask = build_antialiased_mask(size, quad, edge_expand=0, ss=2)
    baseline = scene_rgb.filter(ImageFilter.GaussianBlur(blur_radius))
    spec = Image.merge("RGB", [
        ImageChops.subtract(ch, bch)
        for ch, bch in zip(scene_rgb.split(), baseline.split())
    ])
    spec = spec.point(lambda p: min(255, int(p * boost)))
    black = Image.new("RGB", size, (0, 0, 0))
    return Image.composite(spec, black, mask)


def integrate_art_into_frame(warped_art, scene, quad, size):
    """
    Photoshop layer stack (bottom → top), clipped to frame:
      1. Warped art
      2. Multiply @ 100% with boosted scene luminance (shadows / light falloff)
      3. Soft-light pass (multiply + screen mix with scene) @ 35%
      4. Screen specular / glass reflections from template @ 100%
      5. Mat contact shadow ring
    """
    scene = scene.convert("RGB")
    warped = warped_art.convert("RGB")
    mask = build_antialiased_mask(size, quad, edge_expand=5.0, ss=4)

    ratio_rgb = build_luminance_ratio_map(scene, quad, size, gain=4.8)
    # Neutral multiply at mask boundary — prevents dark fringe where art meets mat
    inner_safe = build_antialiased_mask(size, quad, edge_expand=-2.5, ss=3)
    neutral = Image.new("RGB", size, (255, 255, 255))
    ratio_rgb = Image.composite(ratio_rgb, neutral, inner_safe)

    # Multiply — full strength, not partial opacity
    lit = ImageChops.multiply(warped, ratio_rgb)

    # Soft-light approximation: blend multiply & screen with scene for depth
    sl_mult = ImageChops.multiply(lit, scene)
    sl_scr = ImageChops.screen(lit, scene)
    soft = Image.blend(sl_mult, sl_scr, 0.42)
    lit = Image.blend(lit, soft, 0.38)

    # Glass / glare highlights from pristine template on top
    spec = extract_specular_layer(scene, quad, size)
    lit = ImageChops.screen(lit, spec)

    lit = add_mat_contact_shadow(lit, scene, quad, size, strength=0.18)
    return lit, mask


def sample_mat_color(base_img, quad):
    """Average color inside the frame opening — used as warp fill to avoid black halos."""
    mask = Image.new("L", base_img.size, 0)
    ImageDraw.Draw(mask).polygon([tuple(p) for p in quad], fill=255)
    cropped = Image.composite(base_img.convert("RGB"), Image.new("RGB", base_img.size, (250, 248, 245)), mask)
    thumb = cropped.resize((32, 32), Image.Resampling.BILINEAR)
    hist = thumb.histogram()
    pixels = len(thumb.get_flattened_data()) // 3
    if pixels <= 0:
        return (250, 248, 245)
    r = sum(i * hist[i] for i in range(256)) // pixels
    g = sum(i * hist[256 + i] for i in range(256)) // pixels
    b = sum(i * hist[512 + i] for i in range(256)) // pixels
    return (r, g, b)


def build_hard_mask(size, quad, edge_expand=5.0):
    """Hard-edged mask; antialiasing comes from supersampling, not feather blur."""
    expanded = inset_quad([tuple(p) for p in quad], inset=-edge_expand)
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).polygon(expanded, fill=255)
    return mask


def erode_mask(mask, radius=2):
    if radius <= 0:
        return mask
    size = radius * 2 + 1
    return mask.filter(ImageFilter.MinFilter(size))


def ring_mask(outer, inner):
    return ImageChops.subtract(outer, inner)


def add_mat_contact_shadow(warped, base, quad, size, strength=0.3):
    """Subtle inner-ring darken where mat meets art (ambient occlusion)."""
    outer = build_antialiased_mask(size, quad, edge_expand=3.0, ss=3)
    inner = build_antialiased_mask(size, quad, edge_expand=-2.5, ss=3)
    ring = ring_mask(outer, inner)
    if strength <= 0:
        return warped
    gray = Image.new("RGB", size, (int(255 * (1 - strength)),) * 3)
    darkened = ImageChops.multiply(warped.convert("RGB"), gray)
    return Image.composite(darkened, warped.convert("RGB"), ring)


def harden_mask(mask, threshold=200):
    return mask.point(lambda p: 255 if p >= threshold else 0)


def build_frame_mask(size, quad, edge_expand=2.0, feather=0.5):
    """Legacy soft mask — prefer build_hard_mask for print compositing."""
    expanded = inset_quad([tuple(p) for p in quad], inset=-edge_expand)
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).polygon(expanded, fill=255)
    if feather > 0:
        mask = feather_mask(mask, radius=feather)
    return mask


def feather_mask(mask, radius=2):
    if radius <= 0:
        return mask
    return mask.filter(ImageFilter.GaussianBlur(radius))


def quad_crop_box(quad, img_size, pad_ratio=0.12):
    """Tight crop around one frame opening — gallery walls composite locally, not full canvas."""
    left, top, right, bottom = quad_bounds(quad)
    w, h = img_size
    frame_w = max(1.0, right - left)
    frame_h = max(1.0, bottom - top)
    pad_x = max(20, frame_w * pad_ratio)
    pad_y = max(20, frame_h * pad_ratio)
    x0 = max(0, int(left - pad_x))
    y0 = max(0, int(top - pad_y))
    x1 = min(w, int(right + pad_x))
    y1 = min(h, int(bottom + pad_y))
    return x0, y0, x1, y1


def offset_quad(quad, x0, y0):
    return [(p[0] - x0, p[1] - y0) for p in quad]


def ensure_print_resolution(print_img, quad, headroom=1.6):
    left, top, right, bottom = quad_bounds(quad)
    tw, th = right - left, bottom - top
    pw, ph = print_img.size
    scale = max(tw / pw, th / ph, 1.0) * headroom
    if scale > 1.02:
        print_img = print_img.resize(
            (int(pw * scale), int(ph * scale)),
            Image.Resampling.LANCZOS,
        )
    return print_img


def prepare_print_image(path, trim_pct=0.0):
    with Image.open(path) as raw:
        img = raw.convert("RGB")
    out, _warnings = sanitize_master(img, trim_pct)
    return out


def best_composite_source(piece_dir, prints_dir, aspect=None):
    """Prefer upscaled master.png — much sharper than cropped print JPEGs."""
    master = os.path.join(piece_dir, "master.png")
    if os.path.exists(master):
        return master
    if not prints_dir or not os.path.isdir(prints_dir):
        return None
    matches = []
    for file in os.listdir(prints_dir):
        if not file.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        full = os.path.join(prints_dir, file)
        size_name = file.rsplit(".", 1)[0]
        if aspect and SIZE_TO_ASPECT.get(size_name) != aspect:
            continue
        matches.append(full)
    if not matches:
        matches = [
            os.path.join(prints_dir, f)
            for f in os.listdir(prints_dir)
            if f.lower().endswith((".jpg", ".jpeg", ".png"))
        ]
    if not matches:
        return None
    matches.sort(key=lambda p: os.path.getsize(p), reverse=True)
    return matches[0]


def scale_template_for_output(template_img):
    """Normalize template to listing resolution — downscale 4K templates for speed."""
    w, h = template_img.size
    if w > COMPOSITE_MAX_WIDTH:
        scale = COMPOSITE_MAX_WIDTH / float(w)
        new_size = (COMPOSITE_MAX_WIDTH, int(round(h * scale)))
        return template_img.resize(new_size, Image.Resampling.LANCZOS), scale
    if w >= OUTPUT_MIN_WIDTH:
        return template_img, 1.0
    scale = OUTPUT_MIN_WIDTH / float(w)
    new_size = (int(round(w * scale)), int(round(h * scale)))
    return template_img.resize(new_size, Image.Resampling.LANCZOS), scale


def scale_quad(quad, scale):
    return [(p[0] * scale, p[1] * scale) for p in quad]


def scale_box(box, scale):
    return [int(round(v * scale)) for v in box]


def ensure_listing_resolution(img):
    w, h = img.size
    if w >= OUTPUT_MIN_WIDTH:
        return img
    scale = OUTPUT_MIN_WIDTH / float(w)
    return img.resize((OUTPUT_MIN_WIDTH, int(round(h * scale))), Image.Resampling.LANCZOS)


def is_template_calibrated(template: dict) -> bool:
    """Only composited templates the user has calibrated in Mockup Studio."""
    if template.get("needs_calibration"):
        return False
    if template.get("calibrated") is True:
        return True
    # Legacy templates saved before flags existed — treat as calibrated if quads exist
    if template.get("quad") or template.get("quads"):
        return not template.get("needs_calibration", False)
    return template.get("calibrated", False)


def choose_supersample(base_img, preferred=2, max_work_dim=5500):
    """2× supersample for clean warp edges at composite resolution."""
    max_dim = max(base_img.size)
    for ss in (preferred, 1):
        if max_dim * ss <= max_work_dim:
            return ss
    return 1


def composite_warp(print_img, base_img, quad, lighting_ref=None, supersample=None, placement=None):
    """Warp print onto template with optional supersampling for sharp edges."""
    if lighting_ref is None:
        lighting_ref = base_img
    if supersample is None:
        supersample = choose_supersample(base_img)
    pf = normalize_placement(placement)
    print_img = fit_print_cover_crop(
        print_img, quad, pan_x=pf["pan_x"], pan_y=pf["pan_y"], zoom=pf["zoom"]
    )
    if supersample > 1:
        sw, sh = base_img.size[0] * supersample, base_img.size[1] * supersample
        big_base = base_img.resize((sw, sh), Image.Resampling.LANCZOS)
        big_light = lighting_ref.resize((sw, sh), Image.Resampling.LANCZOS)
        big_quad = [(p[0] * supersample, p[1] * supersample) for p in quad]
        result, bounds = _composite_warp_core(print_img, big_base, big_quad, big_light)
        result = result.resize(base_img.size, Image.Resampling.LANCZOS)
        bounds = tuple(int(b / supersample) for b in bounds)
        return result, bounds
    return _composite_warp_core(print_img, base_img, quad, lighting_ref)


def composite_warp_into(result_img, print_img, quad, lighting_ref, supersample=None, placement=None):
    """Composite one frame into a gallery canvas using a local crop (much faster than full-canvas warps)."""
    w, h = result_img.size
    x0, y0, x1, y1 = quad_crop_box(quad, (w, h))
    base_crop = result_img.crop((x0, y0, x1, y1))
    light_crop = lighting_ref.crop((x0, y0, x1, y1))
    quad_local = offset_quad(quad, x0, y0)
    if supersample is None:
        supersample = choose_supersample(base_crop, preferred=2, max_work_dim=2400)
    merged, _ = composite_warp(
        print_img, base_crop, quad_local, lighting_ref=light_crop,
        supersample=supersample, placement=placement,
    )
    result_img.paste(merged, (x0, y0))
    return result_img


def _composite_warp_core(print_img, base_img, quad, lighting_ref):
    size = base_img.size
    warp_quad = inset_quad([tuple(p) for p in quad], inset=-4.0)
    mat_fill = sample_mat_color(lighting_ref, quad)

    print_img = ensure_print_resolution(print_img, warp_quad, headroom=2.0)
    w_print, h_print = print_img.size
    scale_up = 1.08
    ow, oh = max(1, int(w_print * scale_up)), max(1, int(h_print * scale_up))
    print_img = print_img.resize((ow, oh), Image.Resampling.LANCZOS)

    source_pts = [(0, 0), (ow, 0), (ow, oh), (0, oh)]
    coeffs = find_coefficients(source_pts, warp_quad)
    try:
        warped = print_img.transform(
            size,
            Image.Transform.PERSPECTIVE,
            coeffs,
            Image.Resampling.BICUBIC,
            fillcolor=mat_fill,
        )
    except TypeError:
        warped = print_img.transform(
            size,
            Image.Transform.PERSPECTIVE,
            coeffs,
            Image.Resampling.BICUBIC,
        )
        inside_mask = Image.new("L", size, 0)
        ImageDraw.Draw(inside_mask).polygon(warp_quad, fill=255)
        warped = Image.composite(
            warped.convert("RGB"),
            Image.new("RGB", size, mat_fill),
            inside_mask,
        )

    integrated, comp_mask = integrate_art_into_frame(warped, lighting_ref, quad, size)
    result = Image.composite(integrated, base_img.convert("RGB"), comp_mask)
    return result, quad_bounds(quad)


def generate_mockups_for_piece(piece_dir):
    meta_path = os.path.join(piece_dir, "meta.json")
    if not os.path.exists(meta_path):
        print(f"Error: meta.json not found in {piece_dir}")
        return False
        
    with open(meta_path, "r", encoding="utf-8") as f:
        meta = json.load(f)
        
    orientation = meta.get("orientation", "portrait")
    trim_pct = meta.get("trim_margin", 0)
    quality_warnings = []
    
    master_path = os.path.join(piece_dir, "master.png")
    if os.path.exists(master_path):
        with Image.open(master_path) as m:
            quality_warnings.extend(scan_image_quality(m.convert("RGB")))
    
    if not os.path.exists(TEMPLATES_JSON):
        print(f"Error: templates.json not found at {TEMPLATES_JSON}")
        return False
        
    with open(TEMPLATES_JSON, "r", encoding="utf-8") as f:
        templates = json.load(f)
        
    prints_dir = None
    for name in os.listdir(piece_dir):
        sub = os.path.join(piece_dir, name)
        if os.path.isdir(sub) and ("print" in name.lower() or name == "prints"):
            jpgs = [f for f in os.listdir(sub) if f.lower().endswith(".jpg")]
            if jpgs:
                prints_dir = sub
                break
                
    if not prints_dir:
        print(f"Error: Could not find prints folder containing JPEGs in {piece_dir}")
        return False
        
    # Deduce style tags to select matching mockups
    style_tag = "neutral"
    run_dir = meta.get("run_dir", "")
    run_name = os.path.basename(run_dir).lower() if run_dir else ""
    
    if "plaster" in run_name or "japandi" in run_name:
        style_tag = "japandi"
    elif "academia" in run_name or "gothic" in run_name or "moody" in run_name:
        style_tag = "dark_academia"
    elif "mushroom" in run_name or "specimen" in run_name or "botanical" in run_name:
        style_tag = "botanical"

    print(f"Deduced run style: '{style_tag}' for mockup filtering.")

    # Filter templates by style tag if template has tags configured
    filtered_templates = []
    for t in templates:
        t_tags = t.get("tags", [])
        if not t_tags or style_tag in t_tags or "neutral" in t_tags:
            filtered_templates.append(t)
            
    # Fallback if filter returns empty
    if not filtered_templates:
        filtered_templates = templates

    # Prefer calibrated templates; diagram blanks are not used
    filtered_templates = sorted(
        filtered_templates,
        key=lambda t: (1 if t.get("name", "").startswith("blank_") else 0, t.get("name", "")),
    )
        
    generated_count = 0
    primary_mockup_img = None
    primary_box = None

    # Remove stale composites so only calibrated templates reappear
    for fname in os.listdir(piece_dir):
        if fname.lower().startswith("mockup_") and fname.lower().endswith((".jpg", ".jpeg")):
            try:
                os.remove(os.path.join(piece_dir, fname))
            except OSError:
                pass
    
    for template in filtered_templates:
        if not is_template_calibrated(template):
            print(f"Skipping uncalibrated template {template['name']} (calibrate in Mockup Studio first).")
            continue
        if template.get("orientation") != orientation:
            continue
            
        template_img_path = os.path.join(HERE, template["image"])
        if not os.path.exists(template_img_path):
            print(f"Warning: Template image {template_img_path} not found. Skipping.")
            continue
            
        aspect = template.get("aspect")
        source_file = best_composite_source(piece_dir, prints_dir, aspect)
        if not source_file and "quads" not in template:
            print(f"Warning: No source image found for template {template['name']}. Skipping.")
            continue
            
        print(f"Compositing onto mockup {template['name']}...")
        
        try:
            with Image.open(template_img_path) as raw_tpl:
                template_img, tpl_scale = scale_template_for_output(raw_tpl.convert("RGB"))
            lighting_ref = template_img.copy()
            
            # Check if this is a multi-frame / gallery wall template
            if "quads" in template:
                quads = [scale_quad([tuple(pt) for pt in q], tpl_scale) for q in template["quads"]]
                frame_count = len(quads)
                use_region = frame_count >= 4
                tpl_name = template["name"]

                saved = meta.get("mockup_placements", {}).get(tpl_name, {})
                saved_frames = saved.get("frames", [])
                pool_paths = [img["path"] for img in list_bundle_images(piece_dir, max_count=500)]
                if not pool_paths:
                    pool_paths = gather_run_prints(piece_dir, prints_dir, frame_count)
                auto_paths = assign_prints_to_quads(pool_paths, quads)

                result_img = template_img.copy()
                for idx, quad in enumerate(quads):
                    frame_placement = saved_frames[idx] if idx < len(saved_frames) else {}
                    image_ref = frame_placement.get("image") if frame_placement else None
                    print_path = resolve_print_path(piece_dir, image_ref) if image_ref else None
                    if not print_path:
                        print_path = auto_paths[idx] if idx < len(auto_paths) else pool_paths[0]

                    print_img = prepare_print_image(print_path, trim_pct)
                    placement = normalize_placement(frame_placement)
                    if use_region:
                        composite_warp_into(
                            result_img, print_img, quad, lighting_ref=lighting_ref, placement=placement
                        )
                    else:
                        result_img, _ = composite_warp(
                            print_img, result_img, quad, lighting_ref=lighting_ref, placement=placement
                        )
                    progress = {
                        "template": template["name"],
                        "frame": idx + 1,
                        "total": frame_count,
                    }
                    print(f"__MOCKUP_PROGRESS__{json.dumps(progress)}", flush=True)
                    print(f"  Frame {idx + 1}/{frame_count} composited", flush=True)
                    
                box = scale_box(template["box"], tpl_scale)
                left_b, top_b, right_b, bottom_b = box
                
            else:
                if "quad" in template:
                    quad = scale_quad([tuple(p) for p in template["quad"]], tpl_scale)
                else:
                    left, top, right, bottom = scale_box(template["box"], tpl_scale)
                    quad = [
                        (left, top),
                        (right, top),
                        (right, bottom),
                        (left, bottom)
                    ]
                print_img = prepare_print_image(source_file, trim_pct)
                result_img, bounds = composite_warp(
                    print_img, template_img, quad, lighting_ref=lighting_ref
                )
                left_b, top_b, right_b, bottom_b = bounds

            result_img = ensure_listing_resolution(result_img)
                
            mockup_out_name = f"mockup_{template['name']}.jpg"
            mockup_out_path = os.path.join(piece_dir, mockup_out_name)
            result_img.save(mockup_out_path, "JPEG", quality=95, subsampling=0)
            print(f"  Saved mockup -> {mockup_out_path}")
            
            if primary_mockup_img is None:
                primary_mockup_img = result_img
                primary_box = (left_b, top_b, right_b, bottom_b)
                
            generated_count += 1
            
        except Exception as e:
            print(f"Error generating mockup for template {template['name']}: {e}")
            
    # Zoom GIF is slow — only rebuild when enabled in piece prefs
    include_zoom = meta.get("mockup_prefs", {}).get("include_zoom_gif", True)
    if primary_mockup_img is not None and primary_box is not None and include_zoom:
        gif_out_path = os.path.join(piece_dir, "mockup_zoom.gif")
        generate_zoom_gif(primary_mockup_img, primary_box[0], primary_box[1], primary_box[2], primary_box[3], gif_out_path)

    print(f"Mockup generation complete for {os.path.basename(piece_dir)}. Generated {generated_count} mockups.")
    summary = {
        "success": generated_count > 0,
        "generated": generated_count,
        "warnings": quality_warnings,
    }
    summary_path = os.path.join(piece_dir, "mockup_summary.json")
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print("__MOCKUP_RESULT__" + json.dumps(summary))
    return generated_count > 0

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python generate_mockups.py <piece_directory_path>")
        sys.exit(1)
        
    piece_path = sys.argv[1]
    if not os.path.isabs(piece_path):
        piece_path = os.path.abspath(piece_path)
        
    generate_mockups_for_piece(piece_path)
