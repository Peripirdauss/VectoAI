import os
import sys
import time
import math
import cv2
import datetime
import numpy as np

sys.path.insert(0, r"c:\Users\thesa\Documents\Gravity\vecto\vecto")
from backend.vectorizer import (
    render_to_jpg_freepik,
    render_to_png_transparent,
    render_to_psd,
    inject_metadata_to_eps
)

DOWNLOAD_DIR = r"c:\Users\thesa\Documents\Gravity\vecto\vecto\download"

def chaikin_smooth(pts, iterations=2):
    if len(pts) < 3:
        return pts
    curr = pts.copy()
    for _ in range(iterations):
        smoothed = []
        n = len(curr)
        for i in range(n):
            p0 = curr[i]
            p1 = curr[(i + 1) % n]
            q = [0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1]]
            r = [0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1]]
            smoothed.append(q)
            smoothed.append(r)
        curr = np.array(smoothed, dtype=np.float32)
    return curr

def fill_all_interior_holes_solid(binary_mask):
    contours, hierarchy = cv2.findContours(binary_mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if not contours or hierarchy is None:
        return binary_mask

    filled_mask = binary_mask.copy()
    hierarchy = hierarchy[0]

    for i, cnt in enumerate(contours):
        if hierarchy[i][3] != -1:
            cv2.drawContours(filled_mask, [cnt], -1, 255, -1)

    return filled_mask

class CurvePoint:
    def __init__(self, x, y):
        self.x = x
        self.y = y

class BezierSegment:
    def __init__(self, p0, p1, p2, p3):
        self.end_point = CurvePoint(p3[0], p3[1])
        self.c1 = CurvePoint(p1[0], p1[1])
        self.c2 = CurvePoint(p2[0], p2[1])
        self.c = (p1[0], p1[1])
        self.is_corner = False

class VectorCurve:
    def __init__(self, pts):
        self.start_point = CurvePoint(pts[0][0], pts[0][1])
        self.segments = []
        n = len(pts)
        for i in range(0, n - 1, 2):
            p0 = pts[i]
            p1 = pts[(i + 1) % n]
            p2 = pts[(i + 2) % n]
            p3 = pts[(i + 3) % n] if (i + 3) < n else pts[0]
            self.segments.append(BezierSegment(p0, p1, p2, p3))

    def __iter__(self):
        return iter(self.segments)

def render_master_eps(colored_layers, width, height, scale, title="Master Vector", creator="peripirdaus"):
    eps = []
    eps.append("%!PS-Adobe-3.0 EPSF-3.0")
    eps.append(f"%%BoundingBox: 0 0 {width} {height}")
    eps.append(f"%%HiResBoundingBox: 0 0 {width:.4f} {height:.4f}")
    eps.append(f"%%Title: {title}")
    eps.append(f"%%Creator: {creator}")
    eps.append("%%LanguageLevel: 2")
    eps.append("%%EndComments\n")
    eps.append("/m { moveto } bind def")
    eps.append("/l { lineto } bind def")
    eps.append("/c { curveto } bind def")
    eps.append("/f { fill } bind def")
    eps.append("/rgb { setrgbcolor } bind def\n")

    for layer_idx, layer in enumerate(colored_layers, 1):
        r, g, b = layer["color"]
        eps.append(f"% --- Group Layer #{layer_idx}: RGB({r},{g},{b}) ---")
        eps.append(f"{r/255.0:.4f} {g/255.0:.4f} {b/255.0:.4f} rgb")
        eps.append("newpath")

        for curve in layer["curves"]:
            sp = curve.start_point
            eps.append(f"{sp.x * scale:.3f} {(height - sp.y * scale):.3f} m")
            for seg in curve.segments:
                ep = seg.end_point
                c1 = seg.c1
                c2 = seg.c2
                eps.append(f"{c1.x * scale:.3f} {(height - c1.y * scale):.3f} {c2.x * scale:.3f} {(height - c2.y * scale):.3f} {ep.x * scale:.3f} {(height - ep.y * scale):.3f} c")
            eps.append("closepath")
        eps.append("f\n")

    eps.append("%%EOF")
    return "\n".join(eps).encode("ascii", "replace")

def regularize_crisp_geometry(pts, epsilon=1.2):
    if len(pts) < 3:
        return pts

    cnt_pts = pts.reshape(-1, 1, 2).astype(np.int32)
    approx = cv2.approxPolyDP(cnt_pts, epsilon=epsilon, closed=True)
    clean_pts = approx.reshape(-1, 2).astype(np.float32)

    if len(clean_pts) < 3:
        clean_pts = pts

    n = len(clean_pts)
    smoothed = []
    for i in range(n):
        p0 = clean_pts[i]
        p1 = clean_pts[(i + 1) % n]
        q = [0.75 * p0[0] + 0.25 * p1[0], 0.75 * p0[1] + 0.25 * p1[1]]
        r = [0.25 * p0[0] + 0.75 * p1[0], 0.25 * p0[1] + 0.75 * p1[1]]
        smoothed.append(q)
        smoothed.append(r)

    return np.array(smoothed, dtype=np.float32)

def run_unlimited_pass(pass_num):
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    NEW_OUTPUT_DIR = os.path.join(DOWNLOAD_DIR, f"HASIL_TRAINING_UNLIMITED_PASS{pass_num}_{timestamp_str}")
    os.makedirs(NEW_OUTPUT_DIR, exist_ok=True)

    files = [f for f in os.listdir(DOWNLOAD_DIR) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
    files.sort()

    print(f"\n==================================================================")
    print(f"   UNLIMITED PERPETUAL TRAINING LOOP PASS #{pass_num}")
    print(f"   Engine: Perfect Color & Smooth Shape Engine (0% Neon, 0% Fringes)")
    print(f"   NEW Output Folder: {NEW_OUTPUT_DIR}")
    print(f"   Total Target Images: {len(files)}")
    print(f"==================================================================\n", flush=True)

    color_scale = 0.75 + (pass_num % 3) * 0.1

    for idx, filename in enumerate(files, 1):
        filepath = os.path.join(DOWNLOAD_DIR, filename)
        clean_base = filename.split("_2026")[0]
        safe_base = "".join([c for c in clean_base if c.isalnum() or c in ("_", "-")])
        clean_filename = f"{idx:02d}_{safe_base}"
        title_str = safe_base.replace("_", " ").title()

        print(f"[Pass #{pass_num} | {idx:02d}/{len(files):02d}] Unlimited Training: {filename} -> {clean_filename}...", flush=True)
        start_t = time.time()

        try:
            with open(filepath, "rb") as f:
                image_bytes = f.read()

            nparr = np.frombuffer(image_bytes, np.uint8)
            img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img_bgr is None:
                continue

            h, w = img_bgr.shape[:2]
            MAX_DIM = 1600.0
            if max(w, h) > MAX_DIM:
                scale_proc = MAX_DIM / max(w, h)
                proc_w, proc_h = int(w * scale_proc), int(h * scale_proc)
                bgr_proc = cv2.resize(img_bgr, (proc_w, proc_h), interpolation=cv2.INTER_AREA)
            else:
                proc_w, proc_h = w, h
                bgr_proc = img_bgr.copy()

            smoothed_bgr = cv2.bilateralFilter(bgr_proc, d=7, sigmaColor=35, sigmaSpace=35)
            gray = cv2.cvtColor(smoothed_bgr, cv2.COLOR_BGR2GRAY)

            thresh_dark = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 4)
            kernel_small = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
            micro_accents = cv2.morphologyEx(thresh_dark, cv2.MORPH_OPEN, kernel_small)

            num_colors = 16
            lab = cv2.cvtColor(smoothed_bgr, cv2.COLOR_BGR2LAB)
            pixels = lab.reshape((-1, 3)).astype(np.float32)

            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.01)
            _, labels, centers_lab = cv2.kmeans(pixels, num_colors, None, criteria, 10, cv2.KMEANS_PP_CENTERS)
            labels_2d = labels.reshape((proc_h, proc_w))

            centers_lab_3d = centers_lab.reshape((1, -1, 3)).astype(np.uint8)
            centers_bgr = cv2.cvtColor(centers_lab_3d, cv2.COLOR_LAB2BGR).reshape((-1, 3))

            kernel_clean = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
            colored_layers = []

            for i in range(num_colors):
                raw_mask = (labels_2d == i).astype(np.uint8) * 255
                pixel_cnt = np.sum(raw_mask > 0)
                if pixel_cnt < 20:
                    continue

                bgr_color = centers_bgr[i]
                r, g, b = int(bgr_color[2]), int(bgr_color[1]), int(bgr_color[0])

                clean_mask = cv2.morphologyEx(raw_mask, cv2.MORPH_OPEN, kernel_clean)
                solid_mask = fill_all_interior_holes_solid(clean_mask)
                smooth_mask = cv2.GaussianBlur(solid_mask, (5, 5), 0)
                _, final_mask = cv2.threshold(smooth_mask, 127, 255, cv2.THRESH_BINARY)

                contours, hierarchy = cv2.findContours(final_mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_TC89_KCOS)
                if not contours:
                    continue

                layer_curves = []
                for cnt in contours:
                    if len(cnt) < 4:
                        continue
                    cnt_area = cv2.contourArea(cnt)
                    if cnt_area < 8:
                        continue

                    approx = cv2.approxPolyDP(cnt, epsilon=0.4, closed=True)
                    if len(approx) < 3:
                        continue

                    pts = approx.reshape(-1, 2).astype(np.float32)
                    smoothed_pts = chaikin_smooth(pts, iterations=2)
                    layer_curves.append(VectorCurve(smoothed_pts))

                if layer_curves:
                    colored_layers.append({
                        "color": (r, g, b),
                        "curves": layer_curves,
                        "area": pixel_cnt,
                        "is_micro": False
                    })

            if np.sum(micro_accents > 0) > 10:
                contours_micro, _ = cv2.findContours(micro_accents, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_TC89_KCOS)
                micro_curves = []
                for cnt in contours_micro:
                    if len(cnt) < 3:
                        continue
                    cnt_area = cv2.contourArea(cnt)
                    if 2 <= cnt_area <= 150:
                        approx = cv2.approxPolyDP(cnt, epsilon=0.4, closed=True)
                        if len(approx) < 3:
                            continue
                        pts = approx.reshape(-1, 2).astype(np.float32)
                        smoothed_pts = chaikin_smooth(pts, iterations=2)
                        micro_curves.append(VectorCurve(smoothed_pts))

                if micro_curves:
                    colored_layers.append({
                        "color": (40, 45, 55),
                        "curves": micro_curves,
                        "area": 1,
                        "is_micro": True
                    })

            colored_layers.sort(key=lambda item: (not item.get("is_micro", False), item["area"]), reverse=True)

            if not colored_layers:
                continue

            TARGET_AREA = 4_500_000.0
            scale = math.sqrt(TARGET_AREA / max(1, proc_w * proc_h))
            W, H = int(round(proc_w * scale)), int(round(proc_h * scale))
            internal_scale = W / max(1, proc_w)

            eps_bytes = render_master_eps(colored_layers, W, H, internal_scale, title=title_str, creator="peripirdaus")
            jpg_bytes = render_to_jpg_freepik(None, W, H, 0, 0, internal_scale, colored_layers=colored_layers)
            png_bytes = render_to_png_transparent(None, W, H, 0, 0, internal_scale, colored_layers=colored_layers)

            desc_str = f"{title_str} unlimited goal vector pass {pass_num} illustration"
            kw_str = "vector, unlimited training, perfect color, smooth shape, stock, repeat"

            eps_final = eps_bytes if isinstance(eps_bytes, bytes) else eps_bytes.encode("ascii", "replace")
            if isinstance(eps_final, bytes):
                eps_final = inject_metadata_to_eps(eps_final, title=title_str, description=desc_str, keywords=kw_str)

            elapsed = round(time.time() - start_t, 2)

            if eps_final and jpg_bytes:
                eps_path = os.path.join(NEW_OUTPUT_DIR, f"{clean_filename}.eps")
                jpg_path = os.path.join(NEW_OUTPUT_DIR, f"{clean_filename}.jpg")
                png_path = os.path.join(NEW_OUTPUT_DIR, f"{clean_filename}.png")

                with open(eps_path, "wb") as f:
                    f.write(eps_final)
                with open(jpg_path, "wb") as f:
                    f.write(jpg_bytes)
                if png_bytes:
                    with open(png_path, "wb") as f:
                        f.write(png_bytes)

                eps_kb = round(len(eps_final) / 1024, 1)
                jpg_kb = round(len(jpg_bytes) / 1024, 1)

                print(f"   -> UNLIMITED PASS #{pass_num} SUCCESS! EPS: {eps_kb} KB | JPG: {jpg_kb} KB ({elapsed}s)", flush=True)

        except Exception as e:
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    print("STARTING UNLIMITED PERPETUAL GOAL TRAINING PIPELINE...", flush=True)
    pass_counter = 1
    while True:
        try:
            run_unlimited_pass(pass_counter)
            pass_counter += 1
            time.sleep(2)
        except Exception as err:
            print(f"Error in pass {pass_counter}: {err}", flush=True)
            time.sleep(5)
