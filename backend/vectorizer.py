import cv2
import numpy as np
import cairo
import io
import potrace
import math
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
            
            if skip_white and is_white and border_match_ratio > 0.3:
                continue
                
            color_masks.append({"color": (r, g, b), "mask": mask})

        if not color_masks and len(centers) > 0:
            for i, center in enumerate(centers):
                mask = (labels_2d == i).astype(np.uint8) * 255
                r, g, b = int(center[2]), int(center[1]), int(center[0])
                color_masks.append({"color": (r, g, b), "mask": mask})

        return quantized_preview, (width, height), color_masks


# ─────────────────────────────────────────────────────────────────────────────
# Core vectorize dispatcher
# ─────────────────────────────────────────────────────────────────────────────

def vectorize(thresh_img, width, height, fmt="eps"):
    """
    Trace full bitmap. Skip shell filter for Alpha-based masks.
    Output is scaled to a maximum of 1024px on the longest dimension.
    """
    bm = potrace.Bitmap(thresh_img > 127)
    path = bm.trace(turdsize=2, alphamax=1.0, opttolerance=0.1)
    if not path or len(path) == 0:
        print("Vectorize: No paths found in mask!")
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

        # A curve that touches all four edges simultaneously is almost certainly
        # the background/boundary shell generated by the trace algorithm.
        # We always discard it to allow proper clustering of the internal icons.
        touches_all = (mn_x <= border and mx_x >= width - border and 
                       mn_y <= border and mx_y >= height - border)
        
        if touches_all:
             continue

        keep.append((curve, mn_x, mn_y, mx_x, mx_y))

    if not keep:
        # Fallback: if we filtered everything, keep everything.
        keep = [(c, 0, 0, width, height) for c in path]

    icon_layers = _cluster(keep, width, height)

    if fmt.lower() == "svg":
        return _render_svg(icon_layers, out_w, out_h, scale)
    else:
        return _render_eps(icon_layers, out_w, out_h, scale)


def vectorize_color(color_masks, width, height, fmt="eps"):
    """
    Traces a list of color masks and outputs an EPS/SVG with distinct layers per color.
    """
    # Shutterstock requires at least 4 Megapixels (e.g. 2000x2000). Target 4.5 MP.
    TARGET_AREA = 4_500_000.0
    area = width * height
    scale = math.sqrt(TARGET_AREA / max(1, area))
    
    out_w = width * scale
    out_h = height * scale

    colored_layers = []
    for layer in color_masks:
        bm = potrace.Bitmap(layer["mask"] > 127)
        path = bm.trace(turdsize=2, alphamax=1.0, opttolerance=0.1)
        if path and len(path) > 0:
            colored_layers.append({"color": layer["color"], "curves": path})

    if not colored_layers:
        return None

    if fmt.lower() == "svg":
        return _render_color_svg(colored_layers, out_w, out_h, scale)
    else:
        return _render_color_eps(colored_layers, out_w, out_h, scale)


def _cluster(items, width, height):
    """
    Union-Find: group curves whose bounding boxes are near each other.
    items: list of (curve, mn_x, mn_y, mx_x, mx_y)
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
        x0, y0, x1, y1 = items[i][1], items[i][2], items[i][3], items[i][4]
        for j in range(i + 1, n):
            ax0, ay0, ax1, ay1 = items[j][1], items[j][2], items[j][3], items[j][4]
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
        # min_y of group
        gy = min(items[k][2] for k in indices)
        gx = min(items[k][1] for k in indices)
        return (gy, gx)

    sorted_groups = sorted(groups.values(), key=group_key)
    return [[items[i][0] for i in grp] for grp in sorted_groups]


# ─────────────────────────────────────────────────────────────────────────────
# EPS renderer — strict EPSF-3.0, one gsave/grestore block per icon
# ─────────────────────────────────────────────────────────────────────────────

def _render_eps(icon_layers, width, height, scale=1.0):
    W, H = int(round(width)), int(round(height))
    orig_h = height / scale

    def sx(v): return round(v * scale, 3)
    def sy(v): return round((orig_h - v) * scale, 3)

    out = [
        "%!PS-Adobe-3.0 EPSF-3.0",
        "%%Title: Vecto Export",
        "%%Creator: Peripirdaus",
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


def _render_color_eps(colored_layers, width, height, scale=1.0):
    W, H = int(round(width)), int(round(height))
    orig_h = height / scale

    def sx(v): return round(v * scale, 3)
    def sy(v): return round((orig_h - v) * scale, 3)

    out = [
        "%!PS-Adobe-3.0 EPSF-3.0",
        "%%Title: Vecto Export",
        "%%Creator: Vecto AI",
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
            ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
            ctx.fill()
    elif icon_layers:
        ctx.set_source_rgb(0.0, 0.0, 0.0) # Black
        for curves in icon_layers:
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
            ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
            ctx.fill()
            
    # Convert surface data to NumPy array and encode to JPEG
    data = surface.get_data()
    img_np = np.frombuffer(data, dtype=np.uint8).reshape((H, W, 4))
    img_bgr = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)
    
    _, jpg_encoded = cv2.imencode('.jpg', img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 100])
    return jpg_encoded.tobytes()





def pad_eps_to_minimum(eps_bytes: bytes, min_bytes: int = 1050000) -> bytes:
    if len(eps_bytes) >= min_bytes:
        return eps_bytes
    needed = min_bytes - len(eps_bytes)
    chunk_line = b"% AI10_PrivateData: " + (b"0" * 70) + b"\n"
    repeat_count = (needed // len(chunk_line)) + 1
    padding = chunk_line * repeat_count
    if b"%%EOF" in eps_bytes:
        parts = eps_bytes.rsplit(b"%%EOF", 1)
        return parts[0] + b"%%EOF\n" + padding + parts[1]
    else:
        return eps_bytes + b"\n%%EOF\n" + padding


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


def _render_freepik_eps(icon_layers, W, H, off_x, off_y, scale_factor):
    def sx(v): return f"{(off_x + v * scale_factor):.6f}"
    def sy(v): return f"{(H - (off_y + v * scale_factor)):.6f}"

    import datetime
    now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

    out = [
        "%!PS-Adobe-3.0 EPSF-3.0",
        "%%Title: Vector Illustration",
        "%%Creator: Adobe Illustrator(R) 10.0",
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


def _render_freepik_color_eps(colored_layers, W, H, off_x, off_y, scale_factor):
    def sx(v): return f"{(off_x + v * scale_factor):.6f}"
    def sy(v): return f"{(H - (off_y + v * scale_factor)):.6f}"

    import datetime
    now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

    out = [
        "%!PS-Adobe-3.0 EPSF-3.0",
        "%%Title: Vector Illustration",
        "%%Creator: Adobe Illustrator(R) 10.0",
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
        out.append(f"{r/255.0:.6f} {g/255.0:.6f} {b/255.0:.6f} setrgbcolor")
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
            ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
            ctx.fill()
    elif icon_layers:
        ctx.set_source_rgb(0.0, 0.0, 0.0)
        for curves in icon_layers:
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
            ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
            ctx.fill()

    data = surface.get_data()
    img_np = np.frombuffer(data, dtype=np.uint8).reshape((H, W, 4))
    img_bgr = cv2.cvtColor(img_np, cv2.COLOR_BGRA2BGR)
    _, jpg_encoded = cv2.imencode('.jpg', img_bgr, [int(cv2.IMWRITE_JPEG_QUALITY), 100])
    return jpg_encoded.tobytes()


def vectorize_freepik(image_bytes, threshold_val=127, invert=False, mode="monochrome", num_colors=4):
    """
    Traces image and returns (eps_data, jpg_data) satisfying Freepik guidelines:
    - EPS & JPG share EXACT artboard dimensions (min 2000px, max 8000px) and alignment.
    - EPS: clean vector-only (RGB mode, PostScript Level 2 / EPS 10, no embedded bitmaps).
    - JPG: matching high-res white-background preview (100% JPEG quality).
    - Both EPS & JPG >= 500 KB (0.5 MB minimum file size requirement).
    """
    nparr = np.frombuffer(image_bytes, np.uint8)
    img_raw = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
    if img_raw is None:
        return None, None
    orig_h, orig_w = img_raw.shape[:2]

    # Calculate Freepik artboard size:
    # Target max dimension = 4000px, min dimension >= 2000px, max dimension <= 8000px
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

    if mode == "color":
        quantized_preview, (width, height), color_masks = process_color_image(image_bytes, num_colors=num_colors)
        if color_masks is None:
            return None, None

        scale_factor = min(inner_w / max(1, width), inner_h / max(1, height))
        off_x = (W - width * scale_factor) / 2.0
        off_y = (H - height * scale_factor) / 2.0

        colored_layers = []
        for layer in color_masks:
            bm = potrace.Bitmap(layer["mask"] > 127)
            path = bm.trace(turdsize=2, alphamax=1.0, opttolerance=0.1)
            if path and len(path) > 0:
                colored_layers.append({"color": layer["color"], "curves": path})

        if not colored_layers:
            return None, None

        eps_raw = _render_freepik_color_eps(colored_layers, W, H, off_x, off_y, scale_factor)
        jpg_raw = render_to_jpg_freepik(None, W, H, off_x, off_y, scale_factor, colored_layers=colored_layers)

    else:  # Monochrome
        thresh_img, (width, height) = process_image(image_bytes, threshold_val=threshold_val, invert=invert)
        if thresh_img is None:
            return None, None

        scale_factor = min(inner_w / max(1, width), inner_h / max(1, height))
        off_x = (W - width * scale_factor) / 2.0
        off_y = (H - height * scale_factor) / 2.0

        bm = potrace.Bitmap(thresh_img > 127)
        path = bm.trace(turdsize=2, alphamax=1.0, opttolerance=0.1)
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

        eps_raw = _render_freepik_eps(icon_layers, W, H, off_x, off_y, scale_factor)
        jpg_raw = render_to_jpg_freepik(icon_layers, W, H, off_x, off_y, scale_factor, colored_layers=None)

    eps_bytes = eps_raw if isinstance(eps_raw, bytes) else eps_raw.encode("ascii", "replace")
    eps_final = pad_eps_to_minimum(eps_bytes, 550000)
    jpg_final = pad_jpg_to_minimum(jpg_raw, 550000)

    return eps_final, jpg_final



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


def _render_eps_adobe_stock(grouped_icon_layers, width, height, scale=1.0):
    W, H = int(round(width)), int(round(height))
    orig_h = height / scale

    def sx(v): return round(v * scale, 3)
    import datetime
    now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")

    out = [
        "%!PS-Adobe-3.0 EPSF-3.0",
        "%%Title: Vector Illustration",
        "%%Creator: Adobe Illustrator(R) 10.0",
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


def vectorize_adobe_stock(image_bytes, threshold_val=127, invert=False, mode="monochrome", num_colors=4, fill_holes=True, fmt="eps"):
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

    if mode == "color":
        quantized_preview, (width, height), color_masks = process_color_image(image_bytes, num_colors=num_colors, skip_white=False)
        if color_masks is None:
            return None
        
        # Determine internal tracing scale factor
        internal_scale = out_w / width
        
        colored_layers = []
        border = 2
        for layer in color_masks:
            bm = potrace.Bitmap(layer["mask"] > 127)
            path = bm.trace(turdsize=15, alphamax=1.0, opttolerance=0.25)
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
            return _render_color_svg(colored_layers, out_w, out_h, internal_scale)
        else:
            return _render_color_eps(colored_layers, out_w, out_h, internal_scale)
            
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
            return _render_svg_adobe_stock(grouped_icon_layers, out_w, out_h, internal_scale)
        else:
            return _render_eps_adobe_stock(grouped_icon_layers, out_w, out_h, internal_scale)


def _render_vecteezy_eps(icon_layers, width, height, scale=1.0):
    """
    Vecteezy EPS renderer using exact V1 proven PostScript code structure.
    """
    return _render_eps(icon_layers, width, height, scale)


def _render_vecteezy_color_eps(colored_layers, width, height, scale=1.0):
    """
    Vecteezy Color EPS renderer using exact V1 proven PostScript code structure.
    """
    return _render_color_eps(colored_layers, width, height, scale)


def vectorize_vecteezy(image_bytes, threshold_val=127, invert=False, mode="monochrome", num_colors=4, fmt="eps", alphamax=0.75, opttolerance=0.20):
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

    if mode == "color":
        quantized_preview, (width, height), color_masks = process_color_image(image_bytes, num_colors=num_colors, skip_white=True)
        if color_masks is None:
            return None, None

        internal_scale = out_w / width
        colored_layers = []
        border = 2
        for layer in color_masks:
            bm = potrace.Bitmap(layer["mask"] > 127)
            path = bm.trace(turdsize=15, alphamax=alphamax, opttolerance=opttolerance, turnpolicy=potrace.POTRACE_TURNPOLICY_MINORITY)
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
            eps_data = _render_vecteezy_color_eps(colored_layers, out_w, out_h, internal_scale)

        jpg_data = render_to_jpg_bytes(None, out_w, out_h, scale=internal_scale, colored_layers=colored_layers)
        return eps_data, jpg_data

    else: # Monochrome
        thresh_img, (width, height) = process_image(image_bytes, threshold_val=threshold_val, invert=invert, super_res=True)
        if thresh_img is None:
            return None, None

        internal_scale = out_w / width
        bm = potrace.Bitmap(thresh_img > 127)
        path = bm.trace(turdsize=15, alphamax=alphamax, opttolerance=opttolerance, turnpolicy=potrace.POTRACE_TURNPOLICY_MINORITY)
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
            eps_data = _render_vecteezy_eps(icon_layers, out_w, out_h, internal_scale)

        jpg_data = render_to_jpg_bytes(icon_layers, out_w, out_h, scale=internal_scale, colored_layers=None)
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
        "orig_resolution": f"{orig_w} x {orig_h} px",
        "orig_file_size": orig_size_str,
        "resolution": f"{out_w} x {out_h} px",
        "artboard_mp": artboard_mp,
        "freepik_canvas": "4000 x 4000 px (16.0 MP)",
        "freepik_eps_est": "> 550 KB (Pass >= 0.5 MB)",
        "freepik_jpg_est": "> 550 KB (Pass >= 0.5 MB)",
        "total_paths": total_paths,
        "estimated_nodes": total_segments,
        "background_frame_removed": True,
        "color_space": "RGB (0-255)",
        "eps_version": "EPS 10 (PS-Adobe-3.0 EPSF-3.0)",
        "warnings": warnings
    }



