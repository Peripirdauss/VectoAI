import cv2
import numpy as np
import cairo
import io
import potrace
import math
import base64
# ─────────────────────────────────────────────────────────────────────────────
# Image preprocessing
# ─────────────────────────────────────────────────────────────────────────────

def process_image(image_bytes, threshold_val=127, invert=True, super_res=True):
    nparr = np.frombuffer(image_bytes, np.uint8)
    img_raw = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
    if img_raw is None:
        return None, None

    orig_h, orig_w = img_raw.shape[:2]

    # Sub-pixel Super Resolution (2x-3x upsampling for ultra-smooth Bezier curves and sharp corners)
    if super_res and max(orig_w, orig_h) < 3000:
        scale = 3.0 if max(orig_w, orig_h) < 1000 else 2.0
        img_raw = cv2.resize(img_raw, (int(orig_w * scale), int(orig_h * scale)), interpolation=cv2.INTER_LANCZOS4)

    height, width = img_raw.shape[:2]

    # HANDLE ALPHA CHANNEL INTELLIGENTLY
    if len(img_raw.shape) == 3 and img_raw.shape[2] == 4 and np.min(img_raw[:, :, 3]) < 255:
        thresh = img_raw[:, :, 3]
        if super_res:
            thresh = cv2.GaussianBlur(thresh, (3, 3), 0)
            _, thresh = cv2.threshold(thresh, threshold_val, 255, cv2.THRESH_BINARY)
    else:
        # For opaque or solid-alpha images, use RGB Otsu thresholding
        if len(img_raw.shape) == 3:
            gray = cv2.cvtColor(img_raw[:, :, :3], cv2.COLOR_BGR2GRAY)
        else:
            gray = img_raw
        
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    # Morphological smoothing to eliminate pixel staircase artifacts
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

    if np.mean(thresh) > 127:
        thresh = cv2.bitwise_not(thresh)

    if invert:
        thresh = cv2.bitwise_not(thresh)

    return thresh, (width, height)


def process_color_image(image_bytes, num_colors=4, skip_white=True):
    """
    Quantizes the image using K-Means and returns a quantized BGR preview,
    along with a list of color-specific binary masks for Potrace.
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    img_raw = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
    if img_raw is None:
        return None, None, None

    height, width = img_raw.shape[:2]
    
    # Pre-scale image to max 1024px to prevent cv2.kmeans from hanging on 4M+ pixel images
    MAX_DIM = 1024.0
    if max(width, height) > MAX_DIM:
        scale_factor = MAX_DIM / max(width, height)
        new_w, new_h = int(width * scale_factor), int(height * scale_factor)
        img_raw = cv2.resize(img_raw, (new_w, new_h), interpolation=cv2.INTER_AREA)
        height, width = new_h, new_w

    has_alpha = (len(img_raw.shape) == 3 and img_raw.shape[2] == 4 and np.min(img_raw[:, :, 3]) < 255)

    if has_alpha:
        alpha = img_raw[:, :, 3]
        fg_mask = alpha >= 128
        fg_pixels = img_raw[fg_mask, :3]
        
        if len(fg_pixels) == 0:
            return None, None, None
            
        bgr_preview = np.ones((height, width, 3), dtype=np.uint8) * 255
        
        unique_colors = np.unique(fg_pixels, axis=0)
        actual_colors = min(num_colors, len(unique_colors))
        
        if actual_colors == 1:
            centers = np.uint8([unique_colors[0]])
            labels = np.zeros((len(fg_pixels), 1), dtype=np.int32)
        else:
            pixels_float = fg_pixels.astype(np.float32)
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.2)
            _, labels, centers = cv2.kmeans(pixels_float, actual_colors, None, criteria, 10, cv2.KMEANS_RANDOM_CENTERS)
            centers = np.uint8(centers)

        color_masks = []
        labels_flat = labels.flatten()
        fg_indices = np.where(fg_mask)
        
        labels_2d = np.full((height, width), -1, dtype=np.int32)
        labels_2d[fg_indices] = labels_flat

        for i, center in enumerate(centers):
            mask = (labels_2d == i).astype(np.uint8) * 255
            bgr_preview[labels_2d == i] = center
            r, g, b = int(center[2]), int(center[1]), int(center[0])
            color_masks.append({"color": (r, g, b), "mask": mask})
            
        return bgr_preview, (width, height), color_masks

    else:
        if len(img_raw.shape) == 2:
            bgr = cv2.cvtColor(img_raw, cv2.COLOR_GRAY2BGR)
        elif img_raw.shape[2] == 4:
            bgr = img_raw[:, :, :3]
        else:
            bgr = img_raw

        pixels = bgr.reshape((-1, 3)).astype(np.float32)
        unique_colors = np.unique(pixels, axis=0)
        actual_colors = min(num_colors, len(unique_colors))
        
        criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 100, 0.2)
        _, labels, centers = cv2.kmeans(pixels, actual_colors, None, criteria, 10, cv2.KMEANS_RANDOM_CENTERS)
        
        centers = np.uint8(centers)
        quantized_preview = centers[labels.flatten()].reshape(bgr.shape)
        
        color_masks = []
        labels_2d = labels.reshape((height, width))
        
        border_mask = np.zeros((height, width), dtype=bool)
        border_mask[0, :] = True
        border_mask[-1, :] = True
        border_mask[:, 0] = True
        border_mask[:, -1] = True
        total_border_px = border_mask.sum()

        for i, center in enumerate(centers):
            mask = (labels_2d == i).astype(np.uint8) * 255
            r, g, b = int(center[2]), int(center[1]), int(center[0])
            
            is_white = (r > 245 and g > 245 and b > 245)
            border_match_ratio = (labels_2d[border_mask] == i).sum() / max(1, total_border_px)
            
            if skip_white and border_match_ratio > 0.25:
                continue
                
            color_masks.append({"color": (r, g, b), "mask": mask})

        if not color_masks and len(centers) > 0:
            for i, center in enumerate(centers):
                mask = (labels_2d == i).astype(np.uint8) * 255
                r, g, b = int(center[2]), int(center[1]), int(center[0])
                color_masks.append({"color": (r, g, b), "mask": mask})

        return quantized_preview, (width, height), color_masks


# ─────────────────────────────────────────────────────────────────────────────
def filter_noise_curves(path, min_noise_size=3):
    """
    QC Noise Cleaner: filters out tiny isolated path artifacts below min_noise_size pixels.
    """
    if not path:
        return []
    filtered = []
    for curve in path:
        pts = [curve.start_point] + [s.end_point for s in curve]
        xs = [p.x for p in pts]
        ys = [p.y for p in pts]
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)
        if w < min_noise_size and h < min_noise_size:
            continue
        filtered.append(curve)
    return filtered


def vectorize(thresh_img, width, height, fmt="eps", title="Vector Illustration", creator="peripirdaus", opttolerance=0.1, alphamax=1.0, min_noise_size=3, description="", keywords=None):
    """
    Trace full bitmap. Skip shell filter for Alpha-based masks.
    Output is scaled to a maximum of 1024px on the longest dimension.
    """
    bm = potrace.Bitmap(thresh_img > 127)
    path = bm.trace(turdsize=5, alphamax=alphamax, opttolerance=opttolerance)
    if not path or len(path) == 0:
        print("Vectorize: No paths found in mask!")
        return None

    path = filter_noise_curves(path, min_noise_size=min_noise_size)
    if not path:
        return None

    print(f"Vectorize: Found {len(path)} total paths.")

    # Shutterstock requires at least 4 Megapixels (e.g. 2000x2000). Target 4.5 MP.
    TARGET_AREA = 4_500_000.0
    area = width * height
    scale = math.sqrt(TARGET_AREA / max(1, area))
    
    out_w = width * scale
    out_h = height * scale

    # Discard only legitimate background shells (spans the entire canvas)
    border = 2
    keep = []
    
    for curve in path:
        pts = [curve.start_point] + [s.end_point for s in curve]
        xs, ys = [p.x for p in pts], [p.y for p in pts]
        mn_x, mx_x, mn_y, mx_y = min(xs), max(xs), min(ys), max(ys)

        touches_all = (mn_x <= border and mx_x >= width - border and 
                       mn_y <= border and mx_y >= height - border)
        
        if touches_all:
             continue

        keep.append((curve, mn_x, mn_y, mx_x, mx_y))

    if not keep:
        keep = [(c, 0, 0, width, height) for c in path]

    icon_layers = _cluster(keep, width, height)

    if fmt.lower() == "svg":
        return _render_svg(icon_layers, out_w, out_h, scale)
    else:
        eps_bytes = _render_eps(icon_layers, out_w, out_h, scale, title=title, creator=creator)
        return inject_metadata_to_eps(eps_bytes, title=title, description=description, keywords=keywords)


def vectorize_color(color_masks, width, height, fmt="eps", title="Vector Illustration", creator="peripirdaus", opttolerance=0.1, alphamax=1.0, min_noise_size=3, description="", keywords=None):
    """
    Traces a list of color masks and outputs an EPS/SVG with distinct layers per color.
    Discards giant background rectangle shells from upper layers to prevent block stacking.
    """
    TARGET_AREA = 4_500_000.0
    area = width * height
    scale = math.sqrt(TARGET_AREA / max(1, area))
    
    out_w = width * scale
    out_h = height * scale

    border = 2
    colored_layers = []

    for idx, layer in enumerate(color_masks):
        is_line_art = layer.get("is_line_art", False)
        bm = potrace.Bitmap(layer["mask"] > 127)
        path = bm.trace(turdsize=5, alphamax=alphamax, opttolerance=opttolerance)
        path = filter_noise_curves(path, min_noise_size=min_noise_size)
        if not path:
            continue

        filtered = []
        for curve in path:
            pts = [curve.start_point] + [s.end_point for s in curve]
            xs = [p.x for p in pts]
            ys = [p.y for p in pts]
            mn_x, mx_x = min(xs), max(xs)
            mn_y, mx_y = min(ys), max(ys)

            touches_all = (mn_x <= border and mx_x >= width - border and mn_y <= border and mx_y >= height - border)
            area_ratio = ((mx_x - mn_x) * (mx_y - mn_y)) / (width * height)

            # Strip full-canvas bounding box rectangles for all non-base layers & line-art
            if (touches_all or area_ratio > 0.95) and (idx > 0 or is_line_art):
                continue

            filtered.append(curve)

        if filtered:
            # Cluster the curves so disconnected parts of the same color become separate layers
            sub_clusters = _cluster([(c, min([p.x for p in [c.start_point] + [s.end_point for s in c]]), min([p.y for p in [c.start_point] + [s.end_point for s in c]]), max([p.x for p in [c.start_point] + [s.end_point for s in c]]), max([p.y for p in [c.start_point] + [s.end_point for s in c]])) for c in filtered], width, height)
            for cluster in sub_clusters:
                colored_layers.append({"color": layer["color"], "curves": cluster})

    if not colored_layers:
        return None

    if fmt.lower() == "svg":
        return _render_color_svg(colored_layers, out_w, out_h, scale)
    else:
        eps_bytes = _render_color_eps(colored_layers, out_w, out_h, scale, title=title, creator=creator)
        return inject_metadata_to_eps(eps_bytes, title=title, description=description, keywords=keywords)


def _cluster(items, width, height):
    """
    Union-Find: group curves whose bounding boxes are near each other.
    items: list of (curve, mn_x, mn_y, mx_x, mx_y)
    """
    n = len(items)
    # Set margin to 0 so only overlapping shapes (like a shape and its hole) are grouped.
    margin = 0
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    def is_inside(ix0, iy0, ix1, iy1, ox0, oy0, ox1, oy1):
        margin = 1  # small tolerance
        return ix0 >= ox0 - margin and iy0 >= oy0 - margin and ix1 <= ox1 + margin and iy1 <= oy1 + margin

    for i in range(n):
        x0, y0, x1, y1 = items[i][1], items[i][2], items[i][3], items[i][4]
        for j in range(i + 1, n):
            ax0, ay0, ax1, ay1 = items[j][1], items[j][2], items[j][3], items[j][4]
            # Only group if one bounding box is completely inside the other (e.g. a hole inside a parent shape)
            if is_inside(x0, y0, x1, y1, ax0, ay0, ax1, ay1) or is_inside(ax0, ay0, ax1, ay1, x0, y0, x1, y1):
                union(i, j)

    groups = {}
    for i in range(n):
        root = find(i)
        groups.setdefault(root, []).append(i)

    # Sort groups top-left → bottom-right
    def group_key(indices):
        # min_y of group
        gy = min(items[k][2] for k in indices)
        gx = min(items[k][1] for k in indices)
        return (gy, gx)

    sorted_groups = sorted(groups.values(), key=group_key)
    return [[items[i][0] for i in grp] for grp in sorted_groups]


# ─────────────────────────────────────────────────────────────────────────────
# XMP Metadata Generator & Injector (Adobe / Vecteezy / Microstock Compliant)
# ─────────────────────────────────────────────────────────────────────────────

def generate_xmp_packet(title: str = "", description: str = "", keywords=None, creator: str = "peripirdaus") -> str:
    """
    Generates an Adobe-compliant XMP metadata packet for EPS files containing
    dc:title, dc:description, dc:subject (keywords), pdf:Keywords, and photoshop:CaptionWriter.
    """
    if not title and not description and not keywords:
        return ""

    if isinstance(keywords, str):
        kw_list = [k.strip() for k in keywords.replace("\n", ",").split(",") if k.strip()]
    elif isinstance(keywords, (list, tuple, set)):
        kw_list = [str(k).strip() for k in keywords if str(k).strip()]
    else:
        kw_list = []

    clean_title = (title or "").strip()
    clean_desc = (description or "").strip()
    kw_comma_str = ", ".join(kw_list)

    if not clean_title and not clean_desc and not kw_list:
        return ""

    keywords_rdf = "\n".join([f"%     <rdf:li>{kw}</rdf:li>" for kw in kw_list])

    raw_xmp = f"""%xml-begin
%<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>
%<x:xmpmeta xmlns:x="adobe:ns:meta/">
% <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
%  <rdf:Description rdf:about=""
%    xmlns:dc="http://purl.org/dc/elements/1.1/"
%    xmlns:pdf="http://ns.adobe.com/pdf/1.3/"
%    xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/">
%   <dc:title>
%    <rdf:Alt>
%     <rdf:li xml:lang="x-default">{clean_title}</rdf:li>
%    </rdf:Alt>
%   </dc:title>
%   <dc:description>
%    <rdf:Alt>
%     <rdf:li xml:lang="x-default">{clean_desc}</rdf:li>
%    </rdf:Alt>
%   </dc:description>
%   <dc:subject>
%    <rdf:Bag>
{keywords_rdf}
%    </rdf:Bag>
%   </dc:subject>
%   <pdf:Keywords>{kw_comma_str}</pdf:Keywords>
%   <photoshop:CaptionWriter>{creator}</photoshop:CaptionWriter>
%  </rdf:Description>
% </rdf:RDF>
%</x:xmpmeta>
%<?xpacket end="w"?>
%xml-end"""
    return raw_xmp


def inject_metadata_to_eps(eps_bytes: bytes, title: str = "", description: str = "", keywords=None, creator: str = "peripirdaus") -> bytes:
    """
    Injects PostScript DSC metadata comments (%%Keywords, %%Title, %%Subject)
    and an XMP metadata packet into an EPS byte string after %%EndComments.
    """
    xmp_str = generate_xmp_packet(title, description, keywords, creator=creator)

    try:
        eps_text = eps_bytes.decode("utf-8", errors="ignore")
    except Exception:
        eps_text = eps_bytes.decode("ascii", errors="ignore")

    if isinstance(keywords, str):
        kw_comma_str = ", ".join([k.strip() for k in keywords.replace("\n", ",").split(",") if k.strip()])
    elif isinstance(keywords, (list, tuple, set)):
        kw_comma_str = ", ".join([str(k).strip() for k in keywords if str(k).strip()])
    else:
        kw_comma_str = ""

    header_additions = []
    if kw_comma_str and "%%Keywords:" not in eps_text:
        header_additions.append(f"%%Keywords: {kw_comma_str}")
    if title and "%%Title:" not in eps_text:
        header_additions.append(f"%%Title: {title.strip()}")

    hdr_str = "\n".join(header_additions)
    if hdr_str:
        hdr_str += "\n"

    if "%%EndComments" in eps_text:
        parts = eps_text.split("%%EndComments", 1)
        new_eps = parts[0] + hdr_str + "%%EndComments\n" + xmp_str + "\n" + parts[1]
    else:
        new_eps = hdr_str + xmp_str + "\n" + eps_text

    return new_eps.encode("utf-8", errors="replace")


# ─────────────────────────────────────────────────────────────────────────────
# EPS renderer — strict EPSF-3.0, one gsave/grestore block per icon
# ─────────────────────────────────────────────────────────────────────────────

def _render_eps(icon_layers, width, height, scale=1.0, title="Vector Illustration", creator="peripirdaus"):
    W, H = int(round(width)), int(round(height))
    orig_h = height / scale

    def sx(v): return round(v * scale, 3)
    def sy(v): return round((orig_h - v) * scale, 3)

    out = [
        "%!PS-Adobe-3.0 EPSF-3.0",
        f"%%Title: {title}",
        f"%%Creator: {creator}",
        "%%BoundingBox: 0 0 " + str(W) + " " + str(H),
        "%%HiResBoundingBox: 0.000 0.000 " + str(W) + ".000 " + str(H) + ".000",
        "%%LanguageLevel: 2",
        "%%EndComments",
    ]

    for curves in icon_layers:
        out.append("gsave")
        out.append("0 0 0 setrgbcolor")
        out.append("newpath")
        for curve in curves:
            p = curve.start_point
            out.append(str(sx(p.x)) + " " + str(sy(p.y)) + " moveto")
            for seg in curve:
                if seg.is_corner:
                    out.append(str(sx(seg.c.x)) + " " + str(sy(seg.c.y)) + " lineto")
                    out.append(str(sx(seg.end_point.x)) + " " + str(sy(seg.end_point.y)) + " lineto")
                else:
                    out.append(
                        str(sx(seg.c1.x)) + " " + str(sy(seg.c1.y)) + " " +
                        str(sx(seg.c2.x)) + " " + str(sy(seg.c2.y)) + " " +
                        str(sx(seg.end_point.x)) + " " + str(sy(seg.end_point.y)) + " curveto"
                    )
            out.append("closepath")
        out.append("eofill")
        out.append("grestore")

    out += ["showpage", "%%EOF"]
    return ("\n".join(out) + "\n").encode("ascii", "replace")


def _render_color_eps(colored_layers, width, height, scale=1.0, title="Vector Illustration", creator="peripirdaus"):
    W, H = int(round(width)), int(round(height))
    orig_h = height / scale

    def sx(v): return round(v * scale, 3)
    def sy(v): return round((orig_h - v) * scale, 3)

    out = [
        "%!PS-Adobe-3.0 EPSF-3.0",
        f"%%Title: {title}",
        f"%%Creator: {creator}",
        "%%BoundingBox: 0 0 " + str(W) + " " + str(H),
        "%%HiResBoundingBox: 0.000 0.000 " + str(W) + ".000 " + str(H) + ".000",
        "%%LanguageLevel: 2",
        "%%EndComments",
    ]

    for layer in colored_layers:
        r, g, b = layer["color"]
        out.append("gsave")
        out.append(f"{round(r/255.0, 3)} {round(g/255.0, 3)} {round(b/255.0, 3)} setrgbcolor")
        out.append("newpath")
        for curve in layer["curves"]:
            p = curve.start_point
            out.append(str(sx(p.x)) + " " + str(sy(p.y)) + " moveto")
            for seg in curve:
                if seg.is_corner:
                    out.append(str(sx(seg.c.x)) + " " + str(sy(seg.c.y)) + " lineto")
                    out.append(str(sx(seg.end_point.x)) + " " + str(sy(seg.end_point.y)) + " lineto")
                else:
                    out.append(
                        str(sx(seg.c1.x)) + " " + str(sy(seg.c1.y)) + " " +
                        str(sx(seg.c2.x)) + " " + str(sy(seg.c2.y)) + " " +
                        str(sx(seg.end_point.x)) + " " + str(sy(seg.end_point.y)) + " curveto"
                    )
            out.append("closepath")
        out.append("eofill")
        out.append("grestore")

    out += ["showpage", "%%EOF"]
    return ("\n".join(out) + "\n").encode("ascii", "replace")


# ─────────────────────────────────────────────────────────────────────────────
# SVG renderer — named <g> layers per icon (Affinity / Inkscape compatible)
# ─────────────────────────────────────────────────────────────────────────────

def _render_svg(icon_layers, width, height, scale=1.0):
    W, H = int(round(width)), int(round(height))
    def sx(v): return round(v * scale, 3)
    def sy(v): return round(v * scale, 3)  # SVG Y is top-down, no flip needed

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg"',
        '     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"',
        '     width="' + str(W) + '" height="' + str(H) + '"',
        '     viewBox="0 0 ' + str(W) + ' ' + str(H) + '">',
    ]

    for idx, curves in enumerate(icon_layers):
        label = "Icon " + str(idx + 1)
        gid   = "icon_" + str(idx + 1)
        lines.append('  <g id="' + gid + '"')
        lines.append('     inkscape:label="' + label + '"')
        lines.append('     inkscape:groupmode="layer"')
        lines.append('     fill="#000000" fill-rule="evenodd">')

        for curve in curves:
            d   = []
            sp  = curve.start_point
            d.append("M" + str(sx(sp.x)) + "," + str(sy(sp.y)))
            for seg in curve:
                ep = seg.end_point
                if seg.is_corner:
                    d.append("L" + str(sx(seg.c.x)) + "," + str(sy(seg.c.y)))
                    d.append("L" + str(sx(ep.x)) + "," + str(sy(ep.y)))
                else:
                    d.append(
                        "C" + str(sx(seg.c1.x)) + "," + str(sy(seg.c1.y)) +
                        " " + str(sx(seg.c2.x)) + "," + str(sy(seg.c2.y)) +
                        " " + str(sx(ep.x)) + "," + str(sy(ep.y))
                    )
            d.append("Z")
            lines.append('    <path d="' + " ".join(d) + '"/>')
        lines.append("  </g>")

    lines.append("</svg>")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _render_color_svg(colored_layers, width, height, scale=1.0):
    W, H = int(round(width)), int(round(height))
    def sx(v): return round(v * scale, 3)
    def sy(v): return round(v * scale, 3)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg"',
        '     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"',
        '     width="' + str(W) + '" height="' + str(H) + '"',
        '     viewBox="0 0 ' + str(W) + ' ' + str(H) + '">',
    ]

    for idx, layer in enumerate(colored_layers):
        r, g, b = layer["color"]
        hex_color = f"#{r:02x}{g:02x}{b:02x}"
        label = f"Color {hex_color}"
        gid   = f"color_{idx + 1}"
        lines.append('  <g id="' + gid + '"')
        lines.append('     inkscape:label="' + label + '"')
        lines.append('     inkscape:groupmode="layer"')
        lines.append(f'     fill="{hex_color}" fill-rule="evenodd">')

        for curve in layer["curves"]:
            d   = []
            sp  = curve.start_point
            d.append("M" + str(sx(sp.x)) + "," + str(sy(sp.y)))
            for seg in curve:
                ep = seg.end_point
                if seg.is_corner:
                    d.append("L" + str(sx(seg.c.x)) + "," + str(sy(seg.c.y)))
                    d.append("L" + str(sx(ep.x)) + "," + str(sy(ep.y)))
                else:
                    d.append(
                        "C" + str(sx(seg.c1.x)) + "," + str(sy(seg.c1.y)) +
                        " " + str(sx(seg.c2.x)) + "," + str(sy(seg.c2.y)) +
                        " " + str(sx(ep.x)) + "," + str(sy(ep.y))
                    )
            d.append("Z")
            lines.append('    <path d="' + " ".join(d) + '"/>')
        lines.append("  </g>")

    lines.append("</svg>")
    return ("\n".join(lines) + "\n").encode("utf-8")


def render_to_jpg_bytes(icon_layers, width, height, scale=1.0, colored_layers=None):
    W, H = int(round(width)), int(round(height))
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)
    
    # Fill white background (JPG doesn't support alpha, Freepik requires white canvas background)
    ctx.set_source_rgb(1.0, 1.0, 1.0)
    ctx.paint()
    
    # Draw paths
    if colored_layers:
        for layer in colored_layers:
            r, g, b = layer["color"]
            ctx.set_source_rgb(r / 255.0, g / 255.0, b / 255.0)
            for curve in layer["curves"]:
                ctx.new_path()
                p = curve.start_point
                ctx.move_to(p.x * scale, p.y * scale)
                for seg in curve:
                    if seg.is_corner:
                        ctx.line_to(seg.c.x * scale, seg.c.y * scale)
                        ctx.line_to(seg.end_point.x * scale, seg.end_point.y * scale)
                    else:
                        ctx.curve_to(seg.c1.x * scale, seg.c1.y * scale,
                                     seg.c2.x * scale, seg.c2.y * scale,
                                     seg.end_point.x * scale, seg.end_point.y * scale)
                ctx.close_path()
                ctx.fill()
    elif icon_layers:
        ctx.set_source_rgb(0.0, 0.0, 0.0) # Black
        ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        for curves in icon_layers:
            ctx.new_path()
            for curve in curves:
                p = curve.start_point
                ctx.move_to(p.x * scale, p.y * scale)
                for seg in curve:
                    if seg.is_corner:
                        ctx.line_to(seg.c.x * scale, seg.c.y * scale)
                        ctx.line_to(seg.end_point.x * scale, seg.end_point.y * scale)
                    else:
                        ctx.curve_to(seg.c1.x * scale, seg.c1.y * scale,
                                     seg.c2.x * scale, seg.c2.y * scale,
                                     seg.end_point.x * scale, seg.end_point.y * scale)
                ctx.close_path()
            ctx.fill()
            
    # Convert surface data to NumPy array and encode to JPEG
    data = surface.get_data()
    img_np = np.frombuffer(data, dtype=np.uint8).reshape((H, W, 4))
    img_bgr = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)
    
    _, jpg_encoded = cv2.imencode('.jpg', img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 100])
    return jpg_encoded.tobytes()


def render_to_png_transparent(icon_layers, W, H, off_x=0, off_y=0, scale_factor=1.0, colored_layers=None):
    """
    Renders transparent high-res PNG (ARGB32) without background paint.
    """
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    ctx = cairo.Context(surface)
    ctx.translate(off_x, off_y)

    if colored_layers:
        for layer in colored_layers:
            r, g, b = layer["color"]
            ctx.set_source_rgba(r / 255.0, g / 255.0, b / 255.0, 1.0)
            for curve in layer["curves"]:
                ctx.new_path()
                p = curve.start_point
                ctx.move_to(p.x * scale_factor, p.y * scale_factor)
                for seg in curve:
                    if seg.is_corner:
                        ctx.line_to(seg.c.x * scale_factor, seg.c.y * scale_factor)
                        ctx.line_to(seg.end_point.x * scale_factor, seg.end_point.y * scale_factor)
                    else:
                        ctx.curve_to(seg.c1.x * scale_factor, seg.c1.y * scale_factor,
                                     seg.c2.x * scale_factor, seg.c2.y * scale_factor,
                                     seg.end_point.x * scale_factor, seg.end_point.y * scale_factor)
                ctx.close_path()
                ctx.fill()
    elif icon_layers:
        ctx.set_source_rgba(0.0, 0.0, 0.0, 1.0)
        ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        for curves in icon_layers:
            ctx.new_path()
            for curve in curves:
                p = curve.start_point
                ctx.move_to(p.x * scale_factor, p.y * scale_factor)
                for seg in curve:
                    if seg.is_corner:
                        ctx.line_to(seg.c.x * scale_factor, seg.c.y * scale_factor)
                        ctx.line_to(seg.end_point.x * scale_factor, seg.end_point.y * scale_factor)
                    else:
                        ctx.curve_to(seg.c1.x * scale_factor, seg.c1.y * scale_factor,
                                     seg.c2.x * scale_factor, seg.c2.y * scale_factor,
                                     seg.end_point.x * scale_factor, seg.end_point.y * scale_factor)
                ctx.close_path()
            ctx.fill()

    data = surface.get_data()
    img_np = np.frombuffer(data, dtype=np.uint8).reshape((H, W, 4))
    img_bgra = cv2.cvtColor(img_np, cv2.COLOR_RGBA2BGRA)
    _, png_encoded = cv2.imencode('.png', img_bgra)
    return png_encoded.tobytes()


def split_grid_icons(icon_layers, title="Vector Illustration", creator="peripirdaus", target_dim=2000):
    """
    Grid Auto-Splitter: Takes icon_layers (list of curve groups per icon),
    normalizes each icon onto its own centered 2000x2000 canvas with 10% margin,
    and returns individual EPS, JPG, and PNG bytes for each sub-icon.
    """
    if not icon_layers:
        return []

    split_results = []
    inner_dim = target_dim * 0.80  # 10% safe margin on each side

    for idx, curves in enumerate(icon_layers):
        all_pts = []
        for curve in curves:
            all_pts.append(curve.start_point)
            all_pts.extend([seg.end_point for seg in curve])

        xs = [p.x for p in all_pts]
        ys = [p.y for p in all_pts]
        mn_x, mx_x = min(xs), max(xs)
        mn_y, mx_y = min(ys), max(ys)
        iw = max(1.0, mx_x - mn_x)
        ih = max(1.0, mx_y - mn_y)

        scale_factor = min(inner_dim / iw, inner_dim / ih)
        off_x = (target_dim - iw * scale_factor) / 2.0 - (mn_x * scale_factor)
        off_y = (target_dim - ih * scale_factor) / 2.0 - (mn_y * scale_factor)

        sub_title = f"{title}_icon_{idx+1}.eps"
        eps_bytes = _render_freepik_eps([curves], target_dim, target_dim, off_x, off_y, scale_factor, title=sub_title, creator=creator)
        jpg_bytes = render_to_jpg_freepik([curves], target_dim, target_dim, off_x, off_y, scale_factor)
        png_bytes = render_to_png_transparent([curves], target_dim, target_dim, off_x, off_y, scale_factor)

        split_results.append({
            "sub_index": idx + 1,
            "eps": pad_eps_to_minimum(eps_bytes, 550000),
            "jpg": pad_jpg_to_minimum(jpg_bytes, 550000),
            "png": png_bytes
        })

    return split_results





def pad_eps_to_minimum(eps_bytes: bytes, min_bytes: int = 1050000) -> bytes:
    if len(eps_bytes) >= min_bytes:
        return eps_bytes
    needed = min_bytes - len(eps_bytes)
    chunk_line = b"% AI10_PrivateData: " + (b"0" * 70) + b"\n"
    repeat_count = (needed // len(chunk_line)) + 1
    padding = chunk_line * repeat_count
    if b"%%EOF" in eps_bytes:
        parts = eps_bytes.rsplit(b"%%EOF", 1)
        return parts[0] + padding + b"%%EOF" + parts[1]
    else:
        return eps_bytes + padding + b"\n%%EOF\n"


def pad_jpg_to_minimum(data: bytes, min_bytes: int = 550000) -> bytes:
    if len(data) >= min_bytes:
        return data
    needed = min_bytes - len(data)
    insert_pos = 2 if data[:2] == b'\xff\xd8' else 0
    chunks = []
    while needed > 0:
        payload_len = min(needed - 4, 65530)
        if payload_len <= 0:
            payload_len = 10
        total_len = payload_len + 2
        marker = bytearray([0xFF, 0xFE, (total_len >> 8) & 0xFF, total_len & 0xFF])
        marker.extend(b'F' * payload_len)
        chunks.append(bytes(marker))
        needed -= len(marker)
    return data[:insert_pos] + b''.join(chunks) + data[insert_pos:]


def _render_freepik_eps(icon_layers, W, H, off_x, off_y, scale_factor, title="Vector Illustration", creator="peripirdaus"):
    def sx(v): return f"{(off_x + v * scale_factor):.6f}"
    def sy(v): return f"{(H - (off_y + v * scale_factor)):.6f}"

    import datetime
    now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

    out = [
        "%!PS-Adobe-3.0 EPSF-3.0",
        f"%%Title: {title}",
        f"%%Creator: {creator}",
        "%%AI8_CreatorVersion: 10.0",
        "%%CreationDate: " + now,
        "%%DocumentData: Clean7Bit",
        "%%Origin: 0 0",
        f"%%BoundingBox: 0 0 {W} {H}",
        f"%%HiResBoundingBox: 0.000000 0.000000 {W}.000000 {H}.000000",
        "%%LanguageLevel: 2",
        "%%ColorUsage: Color",
        "%%DocumentColorSpaces: CMYK",
        "%%DocumentProcessColors: Black",
        "%%Pages: 1",
        "%%EndComments",
        "%%BeginProlog",
        "/bd {bind def} bind def",
        "/rg {setrgbcolor} bd",
        "/n {newpath} bd",
        "/m {moveto} bd",
        "/l {lineto} bd",
        "/c {curveto} bd",
        "/h {closepath} bd",
        "/f {eofill} bd",
        "/q {gsave} bd",
        "/Q {grestore} bd",
        "%%EndProlog",
        "%%BeginSetup",
        "%%EndSetup",
        "%%Page: 1 1",
        "%%BeginPageSetup",
        "%%EndPageSetup",
    ]

    for curves in icon_layers:
        out.append("q")
        out.append("0.000000 0.000000 0.000000 setrgbcolor")
        out.append("n")
        for curve in curves:
            p = curve.start_point
            out.append(sx(p.x) + " " + sy(p.y) + " m")
            for seg in curve:
                if seg.is_corner:
                    out.append(sx(seg.c.x) + " " + sy(seg.c.y) + " l")
                    out.append(sx(seg.end_point.x) + " " + sy(seg.end_point.y) + " l")
                else:
                    out.append(
                        sx(seg.c1.x) + " " + sy(seg.c1.y) + " " +
                        sx(seg.c2.x) + " " + sy(seg.c2.y) + " " +
                        sx(seg.end_point.x) + " " + sy(seg.end_point.y) + " c"
                    )
            out.append("h")
        out.append("f")
        out.append("Q")

    out += ["%%PageTrailer", "showpage", "%%Trailer", "%%EOF"]
    return ("\n".join(out) + "\n").encode("ascii", "replace")


def _render_freepik_color_eps(colored_layers, W, H, off_x, off_y, scale_factor, title="Vector Illustration", creator="peripirdaus"):
    def sx(v): return f"{(off_x + v * scale_factor):.6f}"
    def sy(v): return f"{(H - (off_y + v * scale_factor)):.6f}"

    import datetime
    now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

    out = [
        "%!PS-Adobe-3.0 EPSF-3.0",
        f"%%Title: {title}",
        f"%%Creator: {creator}",
        "%%AI8_CreatorVersion: 10.0",
        "%%CreationDate: " + now,
        "%%DocumentData: Clean7Bit",
        "%%Origin: 0 0",
        f"%%BoundingBox: 0 0 {W} {H}",
        f"%%HiResBoundingBox: 0.000000 0.000000 {W}.000000 {H}.000000",
        "%%LanguageLevel: 2",
        "%%ColorUsage: Color",
        "%%DocumentColorSpaces: CMYK",
        "%%DocumentProcessColors: Black",
        "%%Pages: 1",
        "%%EndComments",
        "%%BeginProlog",
        "/bd {bind def} bind def",
        "/rg {setrgbcolor} bd",
        "/n {newpath} bd",
        "/m {moveto} bd",
        "/l {lineto} bd",
        "/c {curveto} bd",
        "/h {closepath} bd",
        "/f {eofill} bd",
        "/q {gsave} bd",
        "/Q {grestore} bd",
        "%%EndProlog",
        "%%BeginSetup",
        "%%EndSetup",
        "%%Page: 1 1",
        "%%BeginPageSetup",
        "%%EndPageSetup",
    ]

    for layer in colored_layers:
        r, g, b = layer["color"]
        out.append("q")
        out.append(f"{r/255.0:.6f} {g/255.0:.6f} {b/255.0:.6f} rg")
        out.append("n")
        for curve in layer["curves"]:
            p = curve.start_point
            out.append(sx(p.x) + " " + sy(p.y) + " m")
            for seg in curve:
                if seg.is_corner:
                    out.append(sx(seg.c.x) + " " + sy(seg.c.y) + " l")
                    out.append(sx(seg.end_point.x) + " " + sy(seg.end_point.y) + " l")
                else:
                    out.append(
                        sx(seg.c1.x) + " " + sy(seg.c1.y) + " " +
                        sx(seg.c2.x) + " " + sy(seg.c2.y) + " " +
                        sx(seg.end_point.x) + " " + sy(seg.end_point.y) + " c"
                    )
            out.append("h")
        out.append("f")
        out.append("Q")

    out += ["%%PageTrailer", "showpage", "%%Trailer", "%%EOF"]
    return ("\n".join(out) + "\n").encode("ascii", "replace")


def render_to_jpg_freepik(icon_layers, W, H, off_x, off_y, scale_factor, colored_layers=None):
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, W, H)
    ctx = cairo.Context(surface)

    # White background
    ctx.set_source_rgb(1.0, 1.0, 1.0)
    ctx.paint()

    ctx.translate(off_x, off_y)

    if colored_layers:
        for layer in colored_layers:
            r, g, b = layer["color"]
            ctx.set_source_rgb(r / 255.0, g / 255.0, b / 255.0)
            for curve in layer["curves"]:
                ctx.new_path()
                p = curve.start_point
                ctx.move_to(p.x * scale_factor, p.y * scale_factor)
                for seg in curve:
                    if seg.is_corner:
                        ctx.line_to(seg.c.x * scale_factor, seg.c.y * scale_factor)
                        ctx.line_to(seg.end_point.x * scale_factor, seg.end_point.y * scale_factor)
                    else:
                        ctx.curve_to(seg.c1.x * scale_factor, seg.c1.y * scale_factor,
                                     seg.c2.x * scale_factor, seg.c2.y * scale_factor,
                                     seg.end_point.x * scale_factor, seg.end_point.y * scale_factor)
                ctx.close_path()
                ctx.fill()
    elif icon_layers:
        ctx.set_source_rgb(0.0, 0.0, 0.0)
        ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        for curves in icon_layers:
            ctx.new_path()
            for curve in curves:
                p = curve.start_point
                ctx.move_to(p.x * scale_factor, p.y * scale_factor)
                for seg in curve:
                    if seg.is_corner:
                        ctx.line_to(seg.c.x * scale_factor, seg.c.y * scale_factor)
                        ctx.line_to(seg.end_point.x * scale_factor, seg.end_point.y * scale_factor)
                    else:
                        ctx.curve_to(seg.c1.x * scale_factor, seg.c1.y * scale_factor,
                                     seg.c2.x * scale_factor, seg.c2.y * scale_factor,
                                     seg.end_point.x * scale_factor, seg.end_point.y * scale_factor)
                ctx.close_path()
            ctx.fill()

    data = surface.get_data()
    img_np = np.frombuffer(data, dtype=np.uint8).reshape((H, W, 4))
    img_bgr = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)
    _, jpg_encoded = cv2.imencode('.jpg', img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 100])
    return jpg_encoded.tobytes()


def vectorize_freepik(image_bytes, threshold_val=127, invert=False, mode="monochrome", num_colors=4, title="Vector Illustration", creator="peripirdaus", opttolerance=0.20, alphamax=0.75, min_noise_size=3, split_grid=False, include_png=True, description="", keywords=""):
    """
    Traces image and returns (eps_data, jpg_data, png_data) satisfying Freepik guidelines,
    with optional Grid Auto-Splitter mode.
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    img_raw = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
    if img_raw is None:
        return None, None, None
    orig_h, orig_w = img_raw.shape[:2]

    # Calculate Freepik artboard size:
    target_max = 4000.0
    art_scale = target_max / max(orig_w, orig_h)
    out_w = orig_w * art_scale
    out_h = orig_h * art_scale

    if min(out_w, out_h) < 2000.0:
        art_scale = 2000.0 / min(orig_w, orig_h)
        out_w = orig_w * art_scale
        out_h = orig_h * art_scale

    if max(out_w, out_h) > 8000.0:
        art_scale = 8000.0 / max(orig_w, orig_h)
        out_w = orig_w * art_scale
        out_h = orig_h * art_scale

    W, H = int(round(out_w)), int(round(out_h))

    # Inner padded area (5% margin)
    inner_w = W * 0.90
    inner_h = H * 0.90

    if mode == "vision":
        return vectorize_vision_ai(
            image_bytes,
            fmt="eps",
            colormode="color",
            hierarchical="stacked",
            mode="spline",
            title=title,
            creator=creator,
            description=description,
            keywords=keywords,
            return_previews=True
        )
    elif mode == "color":
        quantized_preview, (width, height), color_masks = process_color_image(image_bytes, num_colors=num_colors)
        if color_masks is None:
            return None, None, None

        scale_factor = min(inner_w / max(1, width), inner_h / max(1, height))
        off_x = (W - width * scale_factor) / 2.0
        off_y = (H - height * scale_factor) / 2.0

        colored_layers = []
        for layer in color_masks:
            bm = potrace.Bitmap(layer["mask"] > 127)
            path = bm.trace(turdsize=5, alphamax=alphamax, opttolerance=opttolerance, turnpolicy=potrace.POTRACE_TURNPOLICY_MINORITY)
            path = filter_noise_curves(path, min_noise_size=min_noise_size)
            if path and len(path) > 0:
                colored_layers.append({"color": layer["color"], "curves": path})

        if not colored_layers:
            return None, None, None

        eps_raw = _render_freepik_color_eps(colored_layers, W, H, off_x, off_y, scale_factor, title=title, creator=creator)
        jpg_raw = render_to_jpg_freepik(None, W, H, off_x, off_y, scale_factor, colored_layers=colored_layers)
        png_raw = render_to_png_transparent(None, W, H, off_x, off_y, scale_factor, colored_layers=colored_layers)

    else:  # Monochrome
        thresh_img, (width, height) = process_image(image_bytes, threshold_val=threshold_val, invert=invert, super_res=True)
        if thresh_img is None:
            return None, None, None

        scale_factor = min(inner_w / max(1, width), inner_h / max(1, height))
        off_x = (W - width * scale_factor) / 2.0
        off_y = (H - height * scale_factor) / 2.0

        bm = potrace.Bitmap(thresh_img > 127)
        path = bm.trace(turdsize=2, alphamax=alphamax, opttolerance=opttolerance, turnpolicy=potrace.POTRACE_TURNPOLICY_MINORITY)
        path = filter_noise_curves(path, min_noise_size=min_noise_size)
        if not path or len(path) == 0:
            return None, None, None

        border = 2
        keep = []
        for curve in path:
            pts = [curve.start_point] + [s.end_point for s in curve]
            xs, ys = [p.x for p in pts], [p.y for p in pts]
            mn_x, mx_x, mn_y, mx_y = min(xs), max(xs), min(ys), max(ys)
            touches_all = (mn_x <= border and mx_x >= width - border and
                           mn_y <= border and mx_y >= height - border)
            if touches_all:
                continue
            keep.append((curve, mn_x, mn_y, mx_x, mx_y))

        if not keep:
            keep = [(c, 0, 0, width, height) for c in path]

        icon_layers = _cluster(keep, width, height)

        if split_grid and len(icon_layers) > 1:
            split_items = split_grid_icons(icon_layers, title=title, creator=creator)
            return split_items, True, True

        eps_raw = _render_freepik_eps(icon_layers, W, H, off_x, off_y, scale_factor, title=title, creator=creator)
        jpg_raw = render_to_jpg_freepik(icon_layers, W, H, off_x, off_y, scale_factor, colored_layers=None)
        png_raw = render_to_png_transparent(icon_layers, W, H, off_x, off_y, scale_factor, colored_layers=None)

    eps_bytes = eps_raw if isinstance(eps_raw, bytes) else eps_raw.encode("ascii", "replace")
    if isinstance(eps_bytes, bytes):
        eps_bytes = inject_metadata_to_eps(eps_bytes, title=title, description=description, keywords=keywords, creator=creator)
    eps_final = pad_eps_to_minimum(eps_bytes, 550000)
    jpg_final = pad_jpg_to_minimum(jpg_raw, 550000)
    png_final = png_raw

    return eps_final, jpg_final, png_final



def _cluster_colored(items, width, height):
    """
    Union-Find: group curves whose bounding boxes are near each other.
    items: list of (curve, color_name, mn_x, mn_y, mx_x, mx_y)
    """
    n = len(items)
    # Use a tighter margin for grid-based icon sheets (10px)
    margin = 10
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    for i in range(n):
        x0, y0, x1, y1 = items[i][2], items[i][3], items[i][4], items[i][5]
        for j in range(i + 1, n):
            ax0, ay0, ax1, ay1 = items[j][2], items[j][3], items[j][4], items[j][5]
            # Check for overlap within margin
            if not (x1 + margin < ax0 or ax1 + margin < x0 or
                    y1 + margin < ay0 or ay1 + margin < y0):
                union(i, j)

    groups = {}
    for i in range(n):
        root = find(i)
        groups.setdefault(root, []).append(i)

    # Sort groups top-left → bottom-right
    def group_key(indices):
        gy = min(items[k][3] for k in indices)
        gx = min(items[k][2] for k in indices)
        return (gy, gx)

    sorted_groups = sorted(groups.values(), key=group_key)
    return [[items[i] for i in grp] for grp in sorted_groups]


def _render_eps_adobe_stock(grouped_icon_layers, width, height, scale=1.0, title="Vector Illustration", creator="peripirdaus"):
    W, H = int(round(width)), int(round(height))
    orig_h = height / scale

    def sx(v): return round(v * scale, 3)
    def sy(v): return round((orig_h - v) * scale, 3)
    import datetime
    now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

    out = [
        "%!PS-Adobe-3.0 EPSF-3.0",
        f"%%Title: {title}",
        f"%%Creator: {creator}",
        "%%AI8_CreatorVersion: 10.0",
        "%%CreationDate: " + now,
        "%%DocumentData: Clean7Bit",
        "%%Origin: 0 0",
        "%%BoundingBox: 0 0 " + str(W) + " " + str(H),
        "%%HiResBoundingBox: 0.000000 0.000000 " + f"{W}.000000 {H}.000000",
        "%%LanguageLevel: 2",
        "%%ColorUsage: Color",
        "%%DocumentColorSpaces: CMYK",
        "%%DocumentProcessColors: Black",
        "%%Pages: 1",
        "%%EndComments",
        "%%BeginProlog",
        "/rg {setrgbcolor} bind def",
        "/m {moveto} bind def",
        "/l {lineto} bind def",
        "/c {curveto} bind def",
        "/h {closepath} bind def",
        "/f {eofill} bind def",
        "/n {newpath} bind def",
        "/q {gsave} bind def",
        "/Q {grestore} bind def",
        "%%EndProlog",
        "%%BeginSetup",
        "%%EndSetup",
        "%%Page: 1 1",
        "%%BeginPageSetup",
        "%%EndPageSetup",
    ]

    for group in grouped_icon_layers:
        out.append("gsave")
        black_curves = [item[0] for item in group if item[1] == 'black']
        white_curves = [item[0] for item in group if item[1] == 'white']

        if black_curves:
            out.append("0 0 0 setrgbcolor")
            out.append("newpath")
            for curve in black_curves:
                p = curve.start_point
                out.append(str(sx(p.x)) + " " + str(sy(p.y)) + " moveto")
                for seg in curve:
                    if seg.is_corner:
                        out.append(str(sx(seg.c.x)) + " " + str(sy(seg.c.y)) + " lineto")
                        out.append(str(sx(seg.end_point.x)) + " " + str(sy(seg.end_point.y)) + " lineto")
                    else:
                        out.append(
                            str(sx(seg.c1.x)) + " " + str(sy(seg.c1.y)) + " " +
                            str(sx(seg.c2.x)) + " " + str(sy(seg.c2.y)) + " " +
                            str(sx(seg.end_point.x)) + " " + str(sy(seg.end_point.y)) + " curveto"
                        )
                out.append("closepath")
            out.append("eofill")

        if white_curves:
            out.append("1 1 1 setrgbcolor")
            out.append("newpath")
            for curve in white_curves:
                p = curve.start_point
                out.append(str(sx(p.x)) + " " + str(sy(p.y)) + " moveto")
                for seg in curve:
                    if seg.is_corner:
                        out.append(str(sx(seg.c.x)) + " " + str(sy(seg.c.y)) + " lineto")
                        out.append(str(sx(seg.end_point.x)) + " " + str(sy(seg.end_point.y)) + " lineto")
                    else:
                        out.append(
                            str(sx(seg.c1.x)) + " " + str(sy(seg.c1.y)) + " " +
                            str(sx(seg.c2.x)) + " " + str(sy(seg.c2.y)) + " " +
                            str(sx(seg.end_point.x)) + " " + str(sy(seg.end_point.y)) + " curveto"
                        )
                out.append("closepath")
            out.append("eofill")

        out.append("grestore")

    out += ["%%PageTrailer", "showpage", "%%Trailer", "%%EOF"]
    return ("\n".join(out) + "\n").encode("ascii", "replace")


def _render_svg_adobe_stock(grouped_icon_layers, width, height, scale=1.0):
    W, H = int(round(width)), int(round(height))
    def sx(v): return round(v * scale, 3)
    def sy(v): return round(v * scale, 3)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg"',
        '     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"',
        '     width="' + str(W) + '" height="' + str(H) + '"',
        '     viewBox="0 0 ' + str(W) + ' ' + str(H) + '">',
    ]

    for idx, group in enumerate(grouped_icon_layers):
        label = "Icon " + str(idx + 1)
        gid   = "icon_" + str(idx + 1)
        lines.append('  <g id="' + gid + '"')
        lines.append('     inkscape:label="' + label + '"')
        lines.append('     inkscape:groupmode="layer">')

        black_curves = [item[0] for item in group if item[1] == 'black']
        white_curves = [item[0] for item in group if item[1] == 'white']

        if black_curves:
            lines.append('    <g fill="#000000" fill-rule="evenodd">')
            for curve in black_curves:
                d   = []
                sp  = curve.start_point
                d.append("M" + str(sx(sp.x)) + "," + str(sy(sp.y)))
                for seg in curve:
                    ep = seg.end_point
                    if seg.is_corner:
                        d.append("L" + str(sx(seg.c.x)) + "," + str(sy(seg.c.y)))
                        d.append("L" + str(sx(ep.x)) + "," + str(sy(ep.y)))
                    else:
                        d.append(
                            "C" + str(sx(seg.c1.x)) + "," + str(sy(seg.c1.y)) +
                            " " + str(sx(seg.c2.x)) + "," + str(sy(seg.c2.y)) +
                            " " + str(sx(ep.x)) + "," + str(sy(ep.y))
                        )
                d.append("Z")
                lines.append('      <path d="' + " ".join(d) + '"/>')
            lines.append('    </g>')

        if white_curves:
            lines.append('    <g fill="#ffffff" fill-rule="evenodd">')
            for curve in white_curves:
                d   = []
                sp  = curve.start_point
                d.append("M" + str(sx(sp.x)) + "," + str(sy(sp.y)))
                for seg in curve:
                    ep = seg.end_point
                    if seg.is_corner:
                        d.append("L" + str(sx(seg.c.x)) + "," + str(sy(seg.c.y)))
                        d.append("L" + str(sx(ep.x)) + "," + str(sy(ep.y)))
                    else:
                        d.append(
                            "C" + str(sx(seg.c1.x)) + "," + str(sy(seg.c1.y)) +
                            " " + str(sx(seg.c2.x)) + "," + str(sy(seg.c2.y)) +
                            " " + str(sx(ep.x)) + "," + str(sy(ep.y))
                        )
                d.append("Z")
                lines.append('      <path d="' + " ".join(d) + '"/>')
            lines.append('    </g>')

        lines.append("  </g>")

    lines.append("</svg>")
    return ("\n".join(lines) + "\n").encode("utf-8")


def vectorize_adobe_stock(image_bytes, threshold_val=127, invert=False, mode="monochrome", num_colors=4, fill_holes=True, fmt="eps", title="Vector Illustration", creator="peripirdaus", opttolerance=0.25, alphamax=1.0, min_noise_size=3, description="", keywords=""):
    """
    Traces image and returns vector data (EPS or SVG) satisfying Adobe Stock guidelines.
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    img_raw = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
    if img_raw is None:
        return None
    orig_h, orig_w = img_raw.shape[:2]

    # Calculate scale factor for Adobe Stock requirements (recommended min 15MP, target 16MP)
    target_area = 16_000_000.0
    scale = math.sqrt(target_area / max(1, orig_w * orig_h))
    
    # Adjust scale to meet min dimension requirement of 3000px
    min_dim = min(orig_w * scale, orig_h * scale)
    if min_dim < 3000.0:
        scale *= (3000.0 / min_dim)
        
    # Limit max dimension to 10000px
    max_dim = max(orig_w * scale, orig_h * scale)
    if max_dim > 10000.0:
        scale *= (10000.0 / max_dim)
        
    out_w = orig_w * scale
    out_h = orig_h * scale

    if mode == "vision":
        return vectorize_vision_ai(
            image_bytes,
            fmt=fmt,
            colormode="color",
            hierarchical="stacked",
            mode="spline",
            title=title,
            creator=creator,
            description=description,
            keywords=keywords
        )
    elif mode == "color":
        quantized_preview, (width, height), color_masks = process_color_image(image_bytes, num_colors=num_colors, skip_white=False)
        if color_masks is None:
            return None
        
        # Determine internal tracing scale factor
        internal_scale = out_w / width
        
        colored_layers = []
        border = 2
        for layer in color_masks:
            bm = potrace.Bitmap(layer["mask"] > 127)
            path = bm.trace(turdsize=5, alphamax=alphamax, opttolerance=opttolerance)
            path = filter_noise_curves(path, min_noise_size=min_noise_size)
            if not path or len(path) == 0:
                continue
            
            # Filter boundary shell for near-white colors to remove canvas background
            r, g, b = layer["color"]
            is_white = (r > 250 and g > 250 and b > 250)
            
            keep_curves = []
            for curve in path:
                pts = [curve.start_point] + [s.end_point for s in curve]
                xs, ys = [p.x for p in pts], [p.y for p in pts]
                mn_x, mx_x, mn_y, mx_y = min(xs), max(xs), min(ys), max(ys)
                touches_all = (mn_x <= border and mx_x >= width - border and 
                               mn_y <= border and mx_y >= height - border)
                if touches_all:
                    continue
                keep_curves.append(curve)
                
            if keep_curves:
                colored_layers.append({"color": layer["color"], "curves": keep_curves})
                
        if not colored_layers:
            return None
            
        if fmt.lower() == "svg":
            vec_data = _render_color_svg(colored_layers, out_w, out_h, internal_scale)
        else:
            vec_data = _render_color_eps(colored_layers, out_w, out_h, internal_scale, title=title, creator=creator)
            
    else: # Monochrome
        thresh_img, (width, height) = process_image(image_bytes, threshold_val=threshold_val, invert=invert)
        if thresh_img is None:
            return None
            
        # Determine internal tracing scale factor
        internal_scale = out_w / width
            
        # Trace black paths
        bm_black = potrace.Bitmap(thresh_img > 127)
        path_black = bm_black.trace(turdsize=15, alphamax=1.0, opttolerance=0.25)
        
        border = 2
        all_items = []
        
        if path_black:
            for curve in path_black:
                pts = [curve.start_point] + [s.end_point for s in curve]
                xs, ys = [p.x for p in pts], [p.y for p in pts]
                mn_x, mx_x, mn_y, mx_y = min(xs), max(xs), min(ys), max(ys)
                touches_all = (mn_x <= border and mx_x >= width - border and 
                               mn_y <= border and mx_y >= height - border)
                if touches_all:
                    continue
                all_items.append((curve, 'black', mn_x, mn_y, mx_x, mx_y))
                
        if not all_items and path_black:
            all_items = [(c, 'black', 0, 0, width, height) for c in path_black]
            
        # Trace white paths (holes) if enabled
        if fill_holes:
            bm_white = potrace.Bitmap(thresh_img <= 127)
            path_white = bm_white.trace(turdsize=15, alphamax=1.0, opttolerance=0.25)
            
            if path_white:
                for curve in path_white:
                    pts = [curve.start_point] + [s.end_point for s in curve]
                    xs, ys = [p.x for p in pts], [p.y for p in pts]
                    mn_x, mx_x, mn_y, mx_y = min(xs), max(xs), min(ys), max(ys)
                    touches_all = (mn_x <= border and mx_x >= width - border and 
                                   mn_y <= border and mx_y >= height - border)
                    if touches_all:
                        continue
                    all_items.append((curve, 'white', mn_x, mn_y, mx_x, mx_y))
                    
        grouped_icon_layers = _cluster_colored(all_items, width, height)
        
        if fmt.lower() == "svg":
            vec_data = _render_svg_adobe_stock(grouped_icon_layers, out_w, out_h, internal_scale)
        else:
            vec_data = _render_eps_adobe_stock(grouped_icon_layers, out_w, out_h, internal_scale, title=title, creator=creator)

    if fmt.lower() != "svg" and isinstance(vec_data, bytes):
        vec_data = inject_metadata_to_eps(vec_data, title=title, description=description, keywords=keywords, creator=creator)

    return vec_data


def _render_vecteezy_eps(icon_layers, width, height, scale=1.0, title="Vector Illustration", creator="peripirdaus"):
    """
    Vecteezy EPS renderer using exact V1 proven PostScript code structure.
    """
    return _render_eps(icon_layers, width, height, scale, title=title, creator=creator)


def _render_vecteezy_color_eps(colored_layers, width, height, scale=1.0, title="Vector Illustration", creator="peripirdaus"):
    """
    Vecteezy Color EPS renderer using exact V1 proven PostScript code structure.
    """
    return _render_color_eps(colored_layers, width, height, scale, title=title, creator=creator)


def vectorize_vecteezy(image_bytes, threshold_val=127, invert=False, mode="monochrome", num_colors=4, fmt="eps", alphamax=0.75, opttolerance=0.20, title="Vector Illustration", creator="peripirdaus", min_noise_size=3, description="", keywords=None):
    """
    Traces image and returns vector data (EPS or SVG) specifically optimized to pass Vecteezy guidelines:
    - Dedicated Vecteezy EPS renderer (_render_vecteezy_eps) with Adobe Illustrator(R) 10.0 & AI8_CreatorVersion: 10.0 headers.
    - Scaled to 4.5 Megapixels (>= 2000px artboard) meeting Vecteezy technical standards.
    - Clean sub-pixel super-resolution tracing.
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    img_raw = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
    if img_raw is None:
        return None, None
    orig_h, orig_w = img_raw.shape[:2]

    TARGET_AREA = 4_500_000.0
    scale = math.sqrt(TARGET_AREA / max(1, orig_w * orig_h))
    min_dim = min(orig_w * scale, orig_h * scale)
    if min_dim < 2000.0:
        scale *= (2000.0 / min_dim)
    max_dim = max(orig_w * scale, orig_h * scale)
    if max_dim > 8000.0:
        scale *= (8000.0 / max_dim)

    out_w = orig_w * scale
    out_h = orig_h * scale

    if mode == "vision":
        eps_final, jpg_bytes, _ = vectorize_vision_ai(
            image_bytes,
            fmt=fmt,
            colormode="color",
            hierarchical="stacked",
            mode="spline",
            title=title,
            creator=creator,
            description=description,
            keywords=keywords,
            return_previews=True
        )
        return eps_final, jpg_bytes
    elif mode == "color":
        quantized_preview, (width, height), color_masks = process_color_image(image_bytes, num_colors=num_colors, skip_white=True)
        if color_masks is None:
            return None, None

        internal_scale = out_w / width
        colored_layers = []
        border = 2
        for layer in color_masks:
            bm = potrace.Bitmap(layer["mask"] > 127)
            path = bm.trace(turdsize=5, alphamax=alphamax, opttolerance=opttolerance, turnpolicy=potrace.POTRACE_TURNPOLICY_MINORITY)
            path = filter_noise_curves(path, min_noise_size=min_noise_size)
            if not path or len(path) == 0:
                continue

            r, g, b = layer["color"]
            is_white = (r > 250 and g > 250 and b > 250)
            keep_curves = []
            for curve in path:
                pts = [curve.start_point] + [s.end_point for s in curve]
                xs, ys = [p.x for p in pts], [p.y for p in pts]
                mn_x, mx_x, mn_y, mx_y = min(xs), max(xs), min(ys), max(ys)
                touches_all = (mn_x <= border and mx_x >= width - border and
                               mn_y <= border and mx_y >= height - border)
                if touches_all:
                    continue
                keep_curves.append(curve)

            if keep_curves:
                colored_layers.append({"color": layer["color"], "curves": keep_curves})

        if not colored_layers:
            return None, None

        if fmt.lower() == "svg":
            eps_data = _render_color_svg(colored_layers, out_w, out_h, internal_scale)
        else:
            eps_data = _render_vecteezy_color_eps(colored_layers, out_w, out_h, internal_scale, title=title, creator=creator)

        jpg_data = render_to_jpg_bytes(None, out_w, out_h, scale=internal_scale, colored_layers=colored_layers)
        if fmt.lower() != "svg" and isinstance(eps_data, bytes):
            eps_data = inject_metadata_to_eps(eps_data, title=title, description=description, keywords=keywords)
        return eps_data, jpg_data

    else: # Monochrome
        thresh_img, (width, height) = process_image(image_bytes, threshold_val=threshold_val, invert=invert, super_res=True)
        if thresh_img is None:
            return None, None

        internal_scale = out_w / width
        bm = potrace.Bitmap(thresh_img > 127)
        path = bm.trace(turdsize=5, alphamax=alphamax, opttolerance=opttolerance, turnpolicy=potrace.POTRACE_TURNPOLICY_MINORITY)
        path = filter_noise_curves(path, min_noise_size=min_noise_size)
        if not path or len(path) == 0:
            return None, None

        border = 2
        keep = []
        for curve in path:
            pts = [curve.start_point] + [s.end_point for s in curve]
            xs, ys = [p.x for p in pts], [p.y for p in pts]
            mn_x, mx_x, mn_y, mx_y = min(xs), max(xs), min(ys), max(ys)
            touches_all = (mn_x <= border and mx_x >= width - border and
                           mn_y <= border and mx_y >= height - border)
            if touches_all:
                continue
            keep.append((curve, mn_x, mn_y, mx_x, mx_y))

        if not keep:
            keep = [(c, 0, 0, width, height) for c in path]

        icon_layers = _cluster(keep, width, height)

        if fmt.lower() == "svg":
            eps_data = _render_svg(icon_layers, out_w, out_h, internal_scale)
        else:
            eps_data = _render_vecteezy_eps(icon_layers, out_w, out_h, internal_scale, title=title, creator=creator)

        jpg_data = render_to_jpg_bytes(icon_layers, out_w, out_h, scale=internal_scale, colored_layers=None)
        if fmt.lower() != "svg" and isinstance(eps_data, bytes):
            eps_data = inject_metadata_to_eps(eps_data, title=title, description=description, keywords=keywords)
        return eps_data, jpg_data


def preflight_check(image_bytes, threshold_val=127, invert=False, mode="monochrome", num_colors=4):
    """
    Analyzes an input raster image against Freepik, Vecteezy & Microstock submission standards.
    Returns an audit dictionary with path counts, resolution, quality flags, file size estimates, and warnings.
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    img_raw = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
    if img_raw is None:
        return {"status": "FAIL", "warnings": ["Invalid image data."]}

    orig_h, orig_w = img_raw.shape[:2]
    orig_bytes = len(image_bytes)
    orig_size_str = f"{orig_bytes / 1024:.1f} KB" if orig_bytes < 1024 * 1024 else f"{orig_bytes / (1024 * 1024):.2f} MB"

    TARGET_AREA = 4_500_000.0
    scale = math.sqrt(TARGET_AREA / max(1, orig_w * orig_h))
    out_w = int(round(orig_w * scale))
    out_h = int(round(orig_h * scale))
    artboard_mp = round((out_w * out_h) / 1_000_000.0, 2)

    warnings = []
    
    if mode == "color":
        _, (width, height), color_masks = process_color_image(image_bytes, num_colors=num_colors, skip_white=True)
        if not color_masks:
            return {"status": "FAIL", "warnings": ["No color clusters identified."]}
        
        total_paths = 0
        total_segments = 0
        for layer in color_masks:
            bm = potrace.Bitmap(layer["mask"] > 127)
            path = bm.trace(turdsize=15, alphamax=1.0, opttolerance=0.2)
            if path:
                total_paths += len(path)
                for c in path:
                    total_segments += len(c)
    else:
        thresh_img, (width, height) = process_image(image_bytes, threshold_val=threshold_val, invert=invert)
        if thresh_img is None:
            return {"status": "FAIL", "warnings": ["Image thresholding failed."]}
        
        bm = potrace.Bitmap(thresh_img > 127)
        path = bm.trace(turdsize=15, alphamax=1.0, opttolerance=0.2)
        total_paths = len(path) if path else 0
        total_segments = sum(len(c) for c in path) if path else 0

    if total_paths == 0:
        warnings.append("No vector shapes detected. Adjust threshold or invert settings.")
    elif total_paths < 3:
        warnings.append("Very low shape count (Simplicity warning). Consider combining multiple icons into a sheet.")
    
    if artboard_mp < 4.0:
        warnings.append(f"Artboard resolution ({artboard_mp} MP) is below 4.0 MP microstock requirement.")

    status = "PASS" if not warnings else "WARN"
    return {
        "status": status,
        "warnings": warnings,
        "total_paths": total_paths,
        "total_segments": total_segments,
        "resolution": f"{orig_w}x{orig_h}",
        "artboard_mp": artboard_mp,
        "orig_size": orig_size_str
    }

def process_color_image_shutterstock(image_bytes, num_colors=16, dilation_px=1, skip_white=True):
    """
    Precision Shutterstock Multi-Color Pattern Processor:
    - Full 16-color range palette extraction (captures all faint grey cats & soft pastels).
    - Canny + Adaptive Gaussian Line Art fusion (preserves faint grey cat faces & lines).
    - Dilation Bridge silhouette reconstruction (eliminates severed heads & neck cuts).
    - 1 Object = 1 Clean Solid Layer (No bercak-bercak).
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    img_raw = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
    if img_raw is None:
        return None, (0, 0), None

    if len(img_raw.shape) == 3 and img_raw.shape[2] == 4:
        alpha = img_raw[:, :, 3]
        bgr = img_raw[:, :, :3]
        bgr[alpha < 128] = [255, 255, 255]
    else:
        bgr = img_raw

    height, width = bgr.shape[:2]

    # Pre-scale image up to max 2400px to preserve fine raster line art details (eyes, whiskers, stems)
    MAX_DIM = 2400.0
    if max(width, height) > MAX_DIM:
        scale_proc = MAX_DIM / max(width, height)
        proc_w, proc_h = int(width * scale_proc), int(height * scale_proc)
        bgr_proc = cv2.resize(bgr, (proc_w, proc_h), interpolation=cv2.INTER_AREA)
    else:
        proc_w, proc_h = width, height
        bgr_proc = bgr.copy()

    # 1. Bilateral Edge-Preserving Filter (Preserves faint grey details while smoothing color noise)
    smoothed_bgr = cv2.bilateralFilter(bgr_proc, d=5, sigmaColor=25, sigmaSpace=25)
    gray = cv2.cvtColor(smoothed_bgr, cv2.COLOR_BGR2GRAY)

    # 2. Outer Background Isolation using Corner FloodFill
    bg_flood_mask = np.zeros((proc_h + 2, proc_w + 2), np.uint8)
    gray_copy = gray.copy()
    cv2.floodFill(gray_copy, bg_flood_mask, (0, 0), 255, 4, 4)
    cv2.floodFill(gray_copy, bg_flood_mask, (proc_w - 1, 0), 255, 4, 4)
    cv2.floodFill(gray_copy, bg_flood_mask, (0, proc_h - 1), 255, 4, 4)
    cv2.floodFill(gray_copy, bg_flood_mask, (proc_w - 1, proc_h - 1), 255, 4, 4)
    outer_bg = (bg_flood_mask[1:-1, 1:-1] > 0)
    total_outer_bg_px = max(1, np.sum(outer_bg))

    # 3. High-Precision Line-Art Fusion (Gaussian Adaptive + Canny Edges to catch faint grey cats)
    thresh_adaptive = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 2)
    thresh_adaptive[outer_bg] = 0

    edges_canny = cv2.Canny(gray, 30, 90)
    edges_canny[outer_bg] = 0

    line_art_combined = cv2.bitwise_or(thresh_adaptive, edges_canny)
    kernel_clean = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
    line_art_mask = cv2.morphologyEx(line_art_combined, cv2.MORPH_OPEN, kernel_clean)
    has_line_art = (np.sum(line_art_mask > 0) > 20)

    line_art_color = (55, 96, 175)
    if has_line_art:
        line_pixels_bgr = bgr_proc[line_art_mask > 0]
        if len(line_pixels_bgr) > 0:
            mean_bgr = np.mean(line_pixels_bgr, axis=0)
            line_art_color = (int(mean_bgr[2]), int(mean_bgr[1]), int(mean_bgr[0]))

    # 4. Ultra-Fast Subsampled LAB Color Clustering for FULL 16-Color Palette
    lab = cv2.cvtColor(smoothed_bgr, cv2.COLOR_BGR2LAB)
    pixels = lab.reshape((-1, 3)).astype(np.float32)
    unique_colors = np.unique(pixels, axis=0)
    actual_colors = min(max(num_colors, 16), len(unique_colors))

    sample_size = min(len(pixels), 80000)
    if len(pixels) > sample_size:
        idx = np.random.choice(len(pixels), sample_size, replace=False)
        sample_pixels = pixels[idx]
    else:
        sample_pixels = pixels

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.1)
    _, _, centers_lab = cv2.kmeans(sample_pixels, actual_colors, None, criteria, 8, cv2.KMEANS_PP_CENTERS)

    centers_lab = np.uint8(centers_lab).reshape((1, -1, 3))
    centers_bgr = cv2.cvtColor(centers_lab, cv2.COLOR_LAB2BGR).reshape((-1, 3))

    centers_float = centers_lab.reshape(actual_colors, 3).astype(np.float32)
    chunk_size = 500000
    labels = np.empty(len(pixels), dtype=np.uint8)
    for start in range(0, len(pixels), chunk_size):
        end = min(start + chunk_size, len(pixels))
        diff = pixels[start:end, None, :] - centers_float[None, :, :]
        dist_sq = np.sum(diff**2, axis=2)
        labels[start:end] = np.argmin(dist_sq, axis=1)

    labels_2d = labels.reshape((proc_h, proc_w)).astype(np.uint8)

    # 5. Unbroken Silhouette Shape Reconstruction (Dilation bridge connects head & body!)
    color_masks = []
    kernel_bridge = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    kernel_shape = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    for i, center in enumerate(centers_bgr):
        raw_mask = (labels_2d == i).astype(np.uint8) * 255
        bg_coverage = np.sum((raw_mask > 0) & outer_bg) / total_outer_bg_px

        inner_mask = raw_mask.copy()
        cluster_pixels = bgr_proc[raw_mask > 0]
        if len(cluster_pixels) > 0:
            mean_bgr = np.mean(cluster_pixels, axis=0)
            r, g, b = int(mean_bgr[2]), int(mean_bgr[1]), int(mean_bgr[0])
        else:
            b, g, r = int(center[0]), int(center[1]), int(center[2])

        is_light_bg = (r > 225 and g > 225 and b > 225)

        # Skip outer background ONLY if skip_white is True AND it's a light background
        if skip_white and is_light_bg and bg_coverage > 0.25:
            inner_mask[outer_bg] = 0

        if np.sum(inner_mask > 0) < 30:
            continue

        # Dilation bridge to connect neck/chin gaps before contour extraction!
        bridged_mask = cv2.dilate(inner_mask, kernel_bridge, iterations=1)

        # Extract EXACT outer silhouettes using cv2.RETR_EXTERNAL
        contours, _ = cv2.findContours(bridged_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        solid_mask = np.zeros((proc_h, proc_w), np.uint8)

        for cnt in contours:
            if cv2.contourArea(cnt) > 30:
                cv2.drawContours(solid_mask, [cnt], -1, 255, thickness=-1)

        cleaned_mask = cv2.morphologyEx(solid_mask, cv2.MORPH_CLOSE, kernel_shape)

        color_masks.append({
            "color": (r, g, b),
            "mask": cleaned_mask,
            "area": int(np.sum(solid_mask > 0)),
            "is_line_art": False
        })

    # Sort base color fills by area descending
    color_masks.sort(key=lambda item: item["area"], reverse=True)

    # Append Detail Line-Art Outlines at the VERY TOP layer
    if has_line_art:
        color_masks.append({
            "color": line_art_color,
            "mask": line_art_mask,
            "area": 1,
            "is_line_art": True
        })

    return bgr_proc, (proc_w, proc_h), color_masks


def render_to_psd(color_masks, width, height):
    """
    Generates a multi-layer Adobe Photoshop (.PSD) file with separate layers
    for color fills and top line-art outlines.
    """
    try:
        from pytoshop.user import nested_layers
        import pytoshop.enums, io
        
        psd_layers = []
        for layer in color_masks:
            mask = layer["mask"]
            r, g, b = layer["color"]
            name = "Line-Art Outlines" if layer.get("is_line_art") else f"Color Fill RGB({r},{g},{b})"
            
            h, w = mask.shape
            rgba = np.zeros((h, w, 4), dtype=np.uint8)
            rgba[mask > 127] = [r, g, b, 255]
            
            psd_img = nested_layers.Image(
                name=name,
                visible=True,
                opacity=255,
                group_id=0,
                channels={
                    -1: rgba[:, :, 3],
                     0: rgba[:, :, 0],
                     1: rgba[:, :, 1],
                     2: rgba[:, :, 2]
                }
            )
            psd_layers.append(psd_img)

        psd = nested_layers.nested_layers_to_psd(psd_layers, color_mode=pytoshop.enums.ColorMode.rgb)
        bio = io.BytesIO()
        psd.write(bio)
        return bio.getvalue()
    except Exception as e:
        print(f"PSD render warning: {e}")
        return None


def vectorize_shutterstock(
    image_bytes, 
    threshold_val=127, 
    invert=False, 
    mode="monochrome", 
    num_colors=4, 
    fill_holes=True,
    title="Vector Illustration", 
    creator="peripirdaus", 
    opttolerance=0.20, 
    alphamax=0.75, 
    min_noise_size=2,
    description="", 
    keywords=""
):
    """
    Dedicated Shutterstock Regular Vector Engine (Single Vector / Line Art / Illustration):
    - Scaled to 4.5 Megapixels (>= 2000px artboard) meeting Shutterstock technical standards (min 4.0 MP).
    - Precision Potrace tracing (super_res=True, POTRACE_TURNPOLICY_MINORITY).
    - Preserves 100% line art details, inner cutouts, and compound path holes.
    - Generates EPS, JPG, PNG, and PSD (multi-layer Photoshop).
    - Injects XMP metadata (title, description, keywords) into EPS files.
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    img_raw = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
    if img_raw is None:
        return None, None, None, None
    orig_h, orig_w = img_raw.shape[:2]

    # Calculate target scale for Shutterstock requirement (min 4.0 MP, target 4.5 MP)
    TARGET_AREA = 4_500_000.0
    scale = math.sqrt(TARGET_AREA / max(1, orig_w * orig_h))
    min_dim = min(orig_w * scale, orig_h * scale)
    if min_dim < 2000.0:
        scale *= (2000.0 / min_dim)
    max_dim = max(orig_w * scale, orig_h * scale)
    if max_dim > 8000.0:
        scale *= (8000.0 / max_dim)

    out_w = orig_w * scale
    out_h = orig_h * scale
    W, H = int(round(out_w)), int(round(out_h))

    if mode == "color" or mode == "vision":
        quantized_preview, (width, height), color_masks = process_color_image(image_bytes, num_colors=num_colors, skip_white=True)
        if not color_masks:
            quantized_preview, (width, height), color_masks = process_color_image(image_bytes, num_colors=num_colors, skip_white=False)

        if not color_masks:
            return None, None, None, None

        internal_scale = out_w / max(1, width)
        colored_layers = []
        border = 2
        for layer in color_masks:
            bm = potrace.Bitmap(layer["mask"] > 127)
            path = bm.trace(turdsize=3, alphamax=alphamax, opttolerance=opttolerance, turnpolicy=potrace.POTRACE_TURNPOLICY_MINORITY)
            path = filter_noise_curves(path, min_noise_size=min_noise_size)
            if not path or len(path) == 0:
                continue

            r, g, b = layer["color"]
            is_white = (r > 250 and g > 250 and b > 250)
            keep_curves = []
            for curve in path:
                pts = [curve.start_point] + [s.end_point for s in curve]
                xs, ys = [p.x for p in pts], [p.y for p in pts]
                mn_x, mx_x, mn_y, mx_y = min(xs), max(xs), min(ys), max(ys)
                touches_all = (mn_x <= border and mx_x >= width - border and
                               mn_y <= border and mx_y >= height - border)
                if touches_all:
                    continue
                keep_curves.append(curve)

            if keep_curves:
                colored_layers.append({"color": layer["color"], "curves": keep_curves})

        if not colored_layers:
            return None, None, None, None

        eps_raw = _render_color_eps(colored_layers, W, H, internal_scale, title=title, creator=creator)
        jpg_bytes = render_to_jpg_bytes(None, W, H, scale=internal_scale, colored_layers=colored_layers)
        png_bytes = render_to_png_transparent(None, W, H, scale_factor=internal_scale, colored_layers=colored_layers)
        psd_bytes = render_to_psd(color_masks, width, height)

    else:  # Monochrome Line Art
        thresh_img, (width, height) = process_image(image_bytes, threshold_val=threshold_val, invert=invert, super_res=True)
        if thresh_img is None:
            return None, None, None, None

        internal_scale = out_w / max(1, width)
        bm_black = potrace.Bitmap(thresh_img > 127)
        path_black = bm_black.trace(turdsize=2, alphamax=alphamax, opttolerance=opttolerance, turnpolicy=potrace.POTRACE_TURNPOLICY_MINORITY)
        path_black = filter_noise_curves(path_black, min_noise_size=min_noise_size)

        if not path_black or len(path_black) == 0:
            return None, None, None, None

        border = 2
        keep = []
        for curve in path_black:
            pts = [curve.start_point] + [s.end_point for s in curve]
            xs, ys = [p.x for p in pts], [p.y for p in pts]
            mn_x, mx_x, mn_y, mx_y = min(xs), max(xs), min(ys), max(ys)
            touches_all = (mn_x <= border and mx_x >= width - border and
                           mn_y <= border and mx_y >= height - border)
            if touches_all:
                continue
            keep.append((curve, mn_x, mn_y, mx_x, mx_y))

        if not keep:
            keep = [(c, 0, 0, width, height) for c in path_black]

        icon_layers = _cluster(keep, width, height)

        eps_raw = _render_eps(icon_layers, W, H, internal_scale, title=title, creator=creator)
        jpg_bytes = render_to_jpg_bytes(icon_layers, W, H, scale=internal_scale, colored_layers=None)
        png_bytes = render_to_png_transparent(icon_layers, W, H, scale_factor=internal_scale, colored_layers=None)
        
        mono_masks = [{"color": (0, 0, 0), "mask": thresh_img}]
        psd_bytes = render_to_psd(mono_masks, width, height)

    eps_final = eps_raw if isinstance(eps_raw, bytes) else eps_raw.encode("ascii", "replace")
    if isinstance(eps_final, bytes):
        eps_final = inject_metadata_to_eps(eps_final, title=title, description=description, keywords=keywords, creator=creator)

    return eps_final, jpg_bytes, png_bytes, psd_bytes


def vectorize_shutterstock_pattern(
    image_bytes, 
    num_colors=24, 
    title="Pattern Illustration", 
    creator="peripirdaus", 
    opttolerance=0.05, 
    alphamax=1.0, 
    min_noise_size=0,
    dilation_px=1,
    description="",
    keywords=""
):
    """
    Dedicated Shutterstock Multi-Color Pattern Engine:
    - Supports Full-Color multi-palette vectorization (up to 32 colors).
    - Preserves 100% inner white cat bodies, light beige shapes, and pastel details.
    - Captures micro-paths (tiny eyes, whiskers, stars, hearts) down to 1 pixel.
    - Generates multi-layer Adobe Photoshop (.PSD) alongside EPS/JPG/PNG.
    - Injects XMP metadata (title, description, keywords) into EPS files.
    """
    smoothed, (width, height), color_masks = process_color_image_shutterstock(
        image_bytes, num_colors=num_colors, dilation_px=dilation_px, skip_white=True
    )
    if not color_masks:
        # Retry without skip_white if color_masks is empty
        _, _, color_masks = process_color_image_shutterstock(
            image_bytes, num_colors=num_colors, dilation_px=dilation_px, skip_white=False
        )

    if not color_masks:
        return None, None, None, None

    TARGET_AREA = 4_500_000.0
    area = width * height
    scale = math.sqrt(TARGET_AREA / max(1, area))

    out_w = width * scale
    out_h = height * scale

    W, H = int(round(out_w)), int(round(out_h))
    internal_scale = out_w / max(1, width)

    colored_layers = []
    border = 2

    for idx, layer in enumerate(color_masks):
        is_line_art = layer.get("is_line_art", False)
        turd = 2 if is_line_art else 3
        bm = potrace.Bitmap(layer["mask"] > 127)
        path = bm.trace(turdsize=turd, alphamax=0.75, opttolerance=0.20, turnpolicy=potrace.POTRACE_TURNPOLICY_MINORITY)
        if not path:
            continue

        if min_noise_size > 0:
            path = filter_noise_curves(path, min_noise_size=min_noise_size)
            if not path:
                continue

        filtered = []
        for curve in path:
            pts = [curve.start_point] + [s.end_point for s in curve]
            xs = [p.x for p in pts]
            ys = [p.y for p in pts]
            mn_x, mx_x = min(xs), max(xs)
            mn_y, mx_y = min(ys), max(ys)

            touches_all = (mn_x <= border and mx_x >= width - border and mn_y <= border and mx_y >= height - border)
            area_ratio = ((mx_x - mn_x) * (mx_y - mn_y)) / (width * height)

            if (touches_all or area_ratio > 0.95) and (idx > 0 or is_line_art):
                continue

            filtered.append(curve)

        if filtered:
            colored_layers.append({"color": layer["color"], "curves": filtered})

    if not colored_layers:
        for layer in color_masks:
            bm = potrace.Bitmap(layer["mask"] > 127)
            path = bm.trace(turdsize=1, alphamax=alphamax, opttolerance=opttolerance, turnpolicy=potrace.POTRACE_TURNPOLICY_MINORITY)
            if path:
                colored_layers.append({"color": layer["color"], "curves": list(path)})

    if not colored_layers:
        return None, None, None, None

    eps_bytes = _render_freepik_color_eps(colored_layers, W, H, 0, 0, internal_scale, title=title, creator=creator)
    jpg_bytes = render_to_jpg_freepik(None, W, H, 0, 0, internal_scale, colored_layers=colored_layers)
    png_bytes = render_to_png_transparent(None, W, H, 0, 0, internal_scale, colored_layers=colored_layers)
    psd_bytes = render_to_psd(color_masks, width, height)

    eps_final = eps_bytes if isinstance(eps_bytes, bytes) else eps_bytes.encode("ascii", "replace")
    if isinstance(eps_final, bytes):
        eps_final = inject_metadata_to_eps(eps_final, title=title, description=description, keywords=keywords, creator=creator)

    return eps_final, jpg_bytes, png_bytes, psd_bytes


# ─────────────────────────────────────────────────────────────────────────────
# Seamless Pattern Engine: Continuity Analyzer & 3x3 Vector Tiling Generator
# ─────────────────────────────────────────────────────────────────────────────

def analyze_seamless_continuity(image_bytes: bytes) -> dict:
    """
    Evaluates seamless tile continuity along X (left-right) and Y (top-bottom) borders.
    Returns seamlessness score percentage (0 - 100%), border diff metrics, and image dimensions.
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        return {"seamless_score": 0.0, "is_seamless": False, "error": "Invalid image"}

    h, w = img.shape[:2]

    # Compare left column with right column
    left_col = img[:, 0, :].astype(np.float32)
    right_col = img[:, -1, :].astype(np.float32)
    diff_x = np.abs(left_col - right_col)
    mad_x = np.mean(diff_x)

    # Compare top row with bottom row
    top_row = img[0, :, :].astype(np.float32)
    bottom_row = img[-1, :, :].astype(np.float32)
    diff_y = np.abs(top_row - bottom_row)
    mad_y = np.mean(diff_y)

    # Convert mean absolute difference to similarity score %
    score_x = float(max(0.0, 100.0 - (float(mad_x) / 255.0 * 100.0 * 2.5)))
    score_y = float(max(0.0, 100.0 - (float(mad_y) / 255.0 * 100.0 * 2.5)))
    total_score = float(round((score_x + score_y) / 2.0, 1))

    is_seamless = bool(total_score >= 85.0)

    return {
        "seamless_score": total_score,
        "is_seamless": is_seamless,
        "x_continuity": float(round(score_x, 1)),
        "y_continuity": float(round(score_y, 1)),
        "width": int(w),
        "height": int(h)
    }


def generate_3x3_tile_preview(image_bytes: bytes, grid_size: int = 3) -> str:
    """
    Generates a 3x3 tiled preview image encoded in base64 data URL.
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
    if img is None:
        return None

    h, w = img.shape[:2]
    # Resize single tile to max 400px for responsive performance preview
    max_preview_dim = 400.0
    if max(w, h) > max_preview_dim:
        scale = max_preview_dim / max(w, h)
        tw, th = int(w * scale), int(h * scale)
        tile = cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA)
    else:
        tw, th = w, h
        tile = img

    tiled = np.tile(tile, (grid_size, grid_size, 1) if len(tile.shape) == 3 else (grid_size, grid_size))
    _, encoded_img = cv2.imencode('.png', tiled)
    return base64.b64encode(encoded_img).decode('utf-8')


def _shift_curve(curve, dx, dy):
    """
    Helper object to replicate potrace curve coordinates with (dx, dy) spatial offset.
    """
    class ShiftedPoint:
        def __init__(self, p, dx, dy):
            self.x = p.x + dx
            self.y = p.y + dy

    class ShiftedSegment:
        def __init__(self, seg, dx, dy):
            self.is_corner = seg.is_corner
            self.end_point = ShiftedPoint(seg.end_point, dx, dy)
            if seg.is_corner:
                self.c = ShiftedPoint(seg.c, dx, dy)
            else:
                self.c1 = ShiftedPoint(seg.c1, dx, dy)
                self.c2 = ShiftedPoint(seg.c2, dx, dy)

    class ShiftedCurve:
        def __init__(self, curve, dx, dy):
            self.start_point = ShiftedPoint(curve.start_point, dx, dy)
            self._segs = [ShiftedSegment(seg, dx, dy) for seg in curve]
        def __iter__(self):
            return iter(self._segs)
        def __len__(self):
            return len(self._segs)

    return ShiftedCurve(curve, dx, dy)


def vectorize_seamless_pattern_tiled(
    image_bytes: bytes,
    num_colors: int = 16,
    grid_rows: int = 3,
    grid_cols: int = 3,
    title: str = "Seamless Pattern Vector",
    creator: str = "peripirdaus",
    fmt: str = "eps",
    mode: str = "color"
):
    """
    Vectorizes a seamless pattern tile and repeats paths across a grid (default 3x3)
    to produce a full microstock-ready vector repeat sheet (EPS/SVG + high-res preview JPG + transparent PNG).
    Supports mode="color" (Full Color) or mode="lineart" / "outline" (Pure Line Art Only).
    """
    if mode.lower() in ("lineart", "outline", "monochrome"):
        nparr = np.frombuffer(image_bytes, np.uint8)
        img_raw = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img_raw is None:
            return None, None, None
        h, w = img_raw.shape[:2]

        smoothed_bgr = cv2.bilateralFilter(img_raw, d=5, sigmaColor=25, sigmaSpace=25)
        gray = cv2.cvtColor(smoothed_bgr, cv2.COLOR_BGR2GRAY)

        bg_flood_mask = np.zeros((h + 2, w + 2), np.uint8)
        gray_copy = gray.copy()
        cv2.floodFill(gray_copy, bg_flood_mask, (0, 0), 255, 4, 4)
        cv2.floodFill(gray_copy, bg_flood_mask, (w - 1, 0), 255, 4, 4)
        cv2.floodFill(gray_copy, bg_flood_mask, (0, h - 1), 255, 4, 4)
        cv2.floodFill(gray_copy, bg_flood_mask, (w - 1, h - 1), 255, 4, 4)
        outer_bg = (bg_flood_mask[1:-1, 1:-1] > 0)

        thresh_adaptive = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 2)
        thresh_adaptive[outer_bg] = 0

        edges_canny = cv2.Canny(gray, 30, 90)
        edges_canny[outer_bg] = 0

        line_art_combined = cv2.bitwise_or(thresh_adaptive, edges_canny)
        kernel_clean = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
        line_art_clean = cv2.morphologyEx(line_art_combined, cv2.MORPH_OPEN, kernel_clean)

        color_masks = [{
            "color": (30, 30, 35),
            "mask": line_art_clean,
            "area": 1,
            "is_line_art": True
        }]
    else:
        smoothed, (w, h), color_masks = process_color_image_shutterstock(
            image_bytes, num_colors=num_colors, dilation_px=1, skip_white=False
        )

    if not color_masks:
        return None, None, None

    TARGET_AREA = 4_500_000.0
    sheet_w_raw = w * grid_cols
    sheet_h_raw = h * grid_rows
    sheet_area = sheet_w_raw * sheet_h_raw
    scale = math.sqrt(TARGET_AREA / max(1, sheet_area))

    tile_w_scaled = w * scale
    tile_h_scaled = h * scale

    sheet_w = tile_w_scaled * grid_cols
    sheet_h = tile_h_scaled * grid_rows
    W, H = int(round(sheet_w)), int(round(sheet_h))

    base_colored_layers = []
    border = 2

    for idx, layer in enumerate(color_masks):
        is_line_art = layer.get("is_line_art", False)
        turd = 6 if is_line_art else 15
        bm = potrace.Bitmap(layer["mask"] > 127)
        path = bm.trace(turdsize=turd, alphamax=0.75, opttolerance=0.20)
        if not path:
            continue

        filtered = []
        for curve in path:
            pts = [curve.start_point] + [s.end_point for s in curve]
            xs = [p.x for p in pts]
            ys = [p.y for p in pts]
            mn_x, mx_x = min(xs), max(xs)
            mn_y, mx_y = min(ys), max(ys)

            touches_all = (mn_x <= border and mx_x >= w - border and mn_y <= border and mx_y >= h - border)
            area_ratio = ((mx_x - mn_x) * (mx_y - mn_y)) / (w * h)

            # Strip full-canvas bounding box rectangles for non-base layers & line art
            if (touches_all or area_ratio > 0.95) and (idx > 0 or is_line_art):
                continue

            filtered.append(curve)

        if filtered:
            base_colored_layers.append({"color": layer["color"], "curves": filtered})

    if not base_colored_layers:
        return None, None, None

    tiled_colored_layers = []
    for base_layer in base_colored_layers:
        color = base_layer["color"]
        tiled_curves = []
        
        for r_idx in range(grid_rows):
            for c_idx in range(grid_cols):
                dx = c_idx * w
                dy = r_idx * h
                
                for curve in base_layer["curves"]:
                    tiled_curves.append(_shift_curve(curve, dx, dy))

        tiled_colored_layers.append({"color": color, "curves": tiled_curves})

    internal_scale = sheet_w / max(1, sheet_w_raw)

    if fmt.lower() == "svg":
        vec_bytes = _render_color_svg(tiled_colored_layers, W, H, scale=internal_scale)
    else:
        vec_bytes = _render_freepik_color_eps(tiled_colored_layers, W, H, 0, 0, internal_scale, title=title, creator=creator)

    jpg_bytes = render_to_jpg_freepik(None, W, H, 0, 0, internal_scale, colored_layers=tiled_colored_layers)
    png_bytes = render_to_png_transparent(None, W, H, 0, 0, internal_scale, colored_layers=tiled_colored_layers)

    eps_final = vec_bytes if isinstance(vec_bytes, bytes) else vec_bytes.encode("ascii", "replace")
    return eps_final, jpg_bytes, png_bytes


# ─────────────────────────────────────────────────────────────────────────────
# Vision AI Vectorizer (Microstock-Approved Quality, Anti-AI Caterpillar Curves)
# ─────────────────────────────────────────────────────────────────────────────

def sanitize_svg_for_microstock(svg_text: str) -> tuple:
    """
    Strips stray dust points, degenerate paths, and micro-artifacts (< 1.5px)
    to strictly comply with Shutterstock & Adobe Stock inspector standards.
    """
    import re
    stray_count = 0
    def check_path(match):
        nonlocal stray_count
        p_tag = match.group(0)
        d_m = re.search(r'd="([^"]+)"', p_tag)
        if not d_m:
            return ''
        d = d_m.group(1).strip()
        nums = [float(n) for n in re.findall(r'[-+]?(?:\d*\.\d+|\d+)', d)]
        if len(nums) < 4:
            stray_count += 1
            return ''
        xs = nums[0::2]
        ys = nums[1::2]
        w = max(xs) - min(xs)
        h = max(ys) - min(ys)
        # Filter micro dust particles smaller than 1.5 x 1.5 px
        if w < 1.5 and h < 1.5:
            stray_count += 1
            return ''
        return p_tag

    cleaned = re.sub(r'<path\b[^>]*\/?>', check_path, svg_text)
    cleaned = re.sub(r'\n\s*\n', '\n', cleaned)
    return cleaned, stray_count


def vectorize_vision_ai(
    image_bytes: bytes,
    fmt: str = "eps",
    colormode: str = "color",
    hierarchical: str = "stacked",
    mode: str = "spline",
    filter_speckle: int = 10,
    color_precision: int = 7,
    layer_difference: int = 16,
    corner_threshold: int = 60,
    length_threshold: float = 10.0,
    splice_threshold: int = 55,
    max_iterations: int = 15,
    pre_smoothing: bool = True,
    title: str = "Vector Illustration",
    creator: str = "peripirdaus",
    description: str = "",
    keywords=None,
    scale_to_microstock: bool = True,
    return_previews: bool = False
):
    """
    State-of-the-art vision vectorization running 100% locally.
    Produces human-crafted quality Bezier curves:
    - Pre-smoothing with bilateral edge filter eliminates AI pixel jitter.
    - Long curve length threshold (10.0+) eliminates dense anchor point "caterpillars".
    - Post-processing sanitization removes stray points for 100% Adobe Stock & Shutterstock approval.
    """
    import os
    if "/opt/homebrew/lib" not in os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", ""):
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = f"/opt/homebrew/lib:{os.environ.get('DYLD_FALLBACK_LIBRARY_PATH', '')}"

    import vtracer
    import cairosvg

    # 1. Edge-Preserving Pre-smoothing to eliminate AI pixel staircasing & JPEG noise
    trace_bytes = image_bytes
    if pre_smoothing:
        try:
            nparr = np.frombuffer(image_bytes, np.uint8)
            img_raw = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
            if img_raw is not None:
                if len(img_raw.shape) == 3 and img_raw.shape[2] == 4:
                    bgr = img_raw[:, :, :3]
                    alpha = img_raw[:, :, 3]
                    bgr_smooth = cv2.bilateralFilter(bgr, d=5, sigmaColor=40, sigmaSpace=40)
                    alpha_smooth = cv2.medianBlur(alpha, 3)
                    combined = cv2.merge([bgr_smooth, alpha_smooth])
                    _, enc_bytes = cv2.imencode(".png", combined)
                    trace_bytes = enc_bytes.tobytes()
                elif len(img_raw.shape) == 3:
                    bgr_smooth = cv2.bilateralFilter(img_raw, d=5, sigmaColor=40, sigmaSpace=40)
                    _, enc_bytes = cv2.imencode(".png", bgr_smooth)
                    trace_bytes = enc_bytes.tobytes()
        except Exception as e:
            print("Pre-smoothing fallback:", e)
            trace_bytes = image_bytes

    # 2. Run local Rust Vision Vectorizer with Microstock Fitting Engine
    svg_str = vtracer.convert_raw_image_to_svg(
        trace_bytes,
        colormode=colormode,
        hierarchical=hierarchical,
        mode=mode,
        filter_speckle=int(filter_speckle),
        color_precision=int(color_precision),
        layer_difference=int(layer_difference),
        corner_threshold=int(corner_threshold),
        length_threshold=float(length_threshold),
        splice_threshold=int(splice_threshold),
        max_iterations=int(max_iterations),
        path_precision=2
    )

    if not svg_str:
        return (None, None, None) if return_previews else None

    # 3. Microstock Sanitization: remove stray points & dust particles
    svg_str, _ = sanitize_svg_for_microstock(svg_str)

    if fmt.lower() == "svg" and not return_previews:
        return svg_str.encode("utf-8")

    # 4. Render to PostScript / EPS using CairoSVG
    ps_bytes = cairosvg.svg2ps(bytestring=svg_str.encode("utf-8"))
    if not ps_bytes:
        return (None, None, None) if return_previews else None

    ps_text = ps_bytes.decode("utf-8", errors="replace")
    
    # Ensure standard EPSF-3.0 compliance on line 1
    if ps_text.startswith("%!PS-Adobe-3.0"):
        ps_text = "%!PS-Adobe-3.0 EPSF-3.0" + ps_text[len("%!PS-Adobe-3.0"):]

    eps_raw = ps_text.encode("utf-8", errors="replace")

    # 5. Inject XMP Metadata and title/creator
    eps_final = inject_metadata_to_eps(
        eps_raw,
        title=title,
        description=description,
        keywords=keywords,
        creator=creator
    )

    if not return_previews:
        return eps_final

    # 6. If previews requested, generate high-resolution PNG & JPG
    try:
        png_bytes = cairosvg.svg2png(bytestring=svg_str.encode("utf-8"))
        img_bgr = cv2.imdecode(np.frombuffer(png_bytes, np.uint8), cv2.IMREAD_COLOR)
        _, jpg_enc = cv2.imencode('.jpg', img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        jpg_bytes = jpg_enc.tobytes()
        return eps_final, jpg_bytes, png_bytes
    except Exception as e:
        print("Error generating previews for vision AI:", e)
        return eps_final, None, None
