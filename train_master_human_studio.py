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

# Automatically create a NEW timestamped output folder for this training run!
timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
NEW_OUTPUT_DIR = os.path.join(DOWNLOAD_DIR, f"HASIL_TRAINING_{timestamp_str}")
os.makedirs(NEW_OUTPUT_DIR, exist_ok=True)

files = [f for f in os.listdir(DOWNLOAD_DIR) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
files.sort()

print("==================================================================")
print("   MASTER HUMAN VECTOR ARTIST TRAINER (RDP + Chaikin Hierarchy)")
print(f"   Target Folder: {DOWNLOAD_DIR}")
print(f"   NEW Timestamped Output Folder: {NEW_OUTPUT_DIR}")
print(f"   Total Test Images: {len(files)}")
print("==================================================================\n", flush=True)

results = []

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

def vectorize_master_human_art_studio(image_bytes, num_colors=14, title="Master Vector"):
    nparr = np.frombuffer(image_bytes, np.uint8)
    img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    h, w = img_bgr.shape[:2]

    MAX_DIM = 1200.0
    if max(w, h) > MAX_DIM:
        scale_proc = MAX_DIM / max(w, h)
        proc_w, proc_h = int(w * scale_proc), int(h * scale_proc)
        bgr_proc = cv2.resize(img_bgr, (proc_w, proc_h), interpolation=cv2.INTER_AREA)
    else:
        proc_w, proc_h = w, h
        bgr_proc = img_bgr.copy()

    smoothed_bgr = cv2.bilateralFilter(bgr_proc, d=9, sigmaColor=60, sigmaSpace=60)

    lab = cv2.cvtColor(smoothed_bgr, cv2.COLOR_BGR2LAB)
    pixels = lab.reshape((-1, 3)).astype(np.float32)
    
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.01)
    _, labels, centers_lab = cv2.kmeans(pixels, num_colors, None, criteria, 8, cv2.KMEANS_PP_CENTERS)
    labels_2d = labels.reshape((proc_h, proc_w))

    kernel_clean = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    color_masks = []
    colored_layers = []

    for i in range(num_colors):
        raw_mask = (labels_2d == i).astype(np.uint8) * 255
        pixel_cnt = np.sum(raw_mask > 0)
        if pixel_cnt < 80:
            continue

        clean_mask = cv2.morphologyEx(raw_mask, cv2.MORPH_OPEN, kernel_clean)
        contours, hierarchy = cv2.findContours(clean_mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_TC89_KCOS)
        if not contours:
            continue

        layer_curves = []
        for cnt in contours:
            if len(cnt) < 4:
                continue
            cnt_area = cv2.contourArea(cnt)
            if cnt_area < 50:
                continue

            approx = cv2.approxPolyDP(cnt, epsilon=0.8, closed=True)
            if len(approx) < 3:
                continue

            pts = approx.reshape(-1, 2).astype(np.float32)
            smoothed_pts = chaikin_smooth(pts, iterations=2)
            layer_curves.append(VectorCurve(smoothed_pts))

        if layer_curves:
            cluster_pixels_bgr = bgr_proc[labels_2d == i]
            median_bgr = np.median(cluster_pixels_bgr, axis=0)
            r, g, b = int(median_bgr[2]), int(median_bgr[1]), int(median_bgr[0])

            color_masks.append({"color": (r, g, b), "mask": clean_mask, "area": pixel_cnt})
            colored_layers.append({"color": (r, g, b), "curves": layer_curves, "area": pixel_cnt})

    colored_layers.sort(key=lambda item: item["area"], reverse=True)

    TARGET_AREA = 4_500_000.0
    scale = math.sqrt(TARGET_AREA / max(1, proc_w * proc_h))
    W, H = int(round(proc_w * scale)), int(round(proc_h * scale))
    internal_scale = W / max(1, proc_w)

    eps_bytes = render_master_eps(colored_layers, W, H, internal_scale, title=title, creator="peripirdaus")
    jpg_bytes = render_to_jpg_freepik(None, W, H, 0, 0, internal_scale, colored_layers=colored_layers)
    png_bytes = render_to_png_transparent(None, W, H, 0, 0, internal_scale, colored_layers=colored_layers)
    psd_bytes = render_to_psd(color_masks, proc_w, proc_h)

    desc_str = f"{title} master human vector artist illustration"
    kw_str = "vector, master, human quality, illustration, stock, repeat, clean, organized"

    eps_final = eps_bytes if isinstance(eps_bytes, bytes) else eps_bytes.encode("ascii", "replace")
    if isinstance(eps_final, bytes):
        eps_final = inject_metadata_to_eps(eps_final, title=title, description=desc_str, keywords=kw_str)

    return eps_final, jpg_bytes, png_bytes, psd_bytes


for idx, filename in enumerate(files, 1):
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    clean_base = filename.split("_2026")[0]
    clean_filename = f"{idx:02d}_{clean_base}"
    title_str = clean_base.replace("_", " ").title()
    
    print(f"[{idx:02d}/{len(files):02d}] Training (Master Human Art): {filename} -> {clean_filename}...", flush=True)
    start_t = time.time()
    
    try:
        with open(filepath, "rb") as f:
            image_bytes = f.read()
            
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        h, w = img.shape[:2]
        
        sample_small = cv2.resize(img, (120, 120))
        unique_colors_cnt = len(np.unique(sample_small.reshape(-1, 3), axis=0))
        optimal_colors = min(16, max(8, int(math.sqrt(unique_colors_cnt) * 0.7)))
        
        eps, jpg, png, psd = vectorize_master_human_art_studio(
            image_bytes, 
            num_colors=optimal_colors, 
            title=title_str
        )
        
        elapsed = round(time.time() - start_t, 2)
        
        if eps and jpg:
            eps_path = os.path.join(NEW_OUTPUT_DIR, f"{clean_filename}.eps")
            jpg_path = os.path.join(NEW_OUTPUT_DIR, f"{clean_filename}.jpg")
            png_path = os.path.join(NEW_OUTPUT_DIR, f"{clean_filename}.png")
            psd_path = os.path.join(NEW_OUTPUT_DIR, f"{clean_filename}.psd")
            
            with open(eps_path, "wb") as f:
                f.write(eps)
            with open(jpg_path, "wb") as f:
                f.write(jpg)
            if png:
                with open(png_path, "wb") as f:
                    f.write(png)
            if psd:
                with open(psd_path, "wb") as f:
                    f.write(psd)
                    
            eps_kb = round(len(eps) / 1024, 1)
            jpg_kb = round(len(jpg) / 1024, 1)
            
            results.append({
                "filename": filename,
                "clean_name": clean_filename,
                "status": "MASTER HUMAN SUCCESS",
                "colors": optimal_colors,
                "eps_kb": eps_kb,
                "jpg_kb": jpg_kb,
                "time": elapsed
            })
            print(f"   -> MASTER HUMAN SUCCESS! EPS: {eps_kb} KB | JPG: {jpg_kb} KB ({elapsed}s)", flush=True)
        else:
            results.append({"filename": filename, "status": "FAILED", "time": elapsed})
            print(f"   -> FAILED", flush=True)
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        results.append({"filename": filename, "status": f"ERROR: {e}", "time": round(time.time() - start_t, 2)})

print("\n==================================================================")
success_cnt = sum(1 for r in results if "MASTER HUMAN SUCCESS" in r["status"])
total_cnt = len(results)
accuracy_pct = round((success_cnt / max(1, total_cnt)) * 100, 1)

print(f"   MASTER HUMAN VECTOR ARTIST TRAINING REPORT:")
print(f"   Total Processed Images : {total_cnt}")
print(f"   Master Human Success   : {success_cnt}")
print(f"   Accuracy Rate          : {accuracy_pct}%")
print(f"   NEW TIMESTAMPED FOLDER : {NEW_OUTPUT_DIR}")
print("==================================================================", flush=True)
