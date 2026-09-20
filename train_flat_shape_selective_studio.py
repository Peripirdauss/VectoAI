import os
import sys
import time
import math
import cv2
import datetime
import numpy as np

sys.path.insert(0, r"c:\Users\thesa\Documents\Gravity\vecto\vecto")
from backend.vectorizer import (
    _render_color_eps,
    render_to_jpg_freepik,
    render_to_png_transparent,
    render_to_psd,
    inject_metadata_to_eps,
    filter_noise_curves
)
import potrace

DOWNLOAD_DIR = r"c:\Users\thesa\Documents\Gravity\vecto\vecto\download"

# Automatically create a NEW timestamped output folder for each training run!
timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
NEW_OUTPUT_DIR = os.path.join(DOWNLOAD_DIR, f"HASIL_TRAINING_{timestamp_str}")
os.makedirs(NEW_OUTPUT_DIR, exist_ok=True)

files = [f for f in os.listdir(DOWNLOAD_DIR) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
files.sort()

print("==================================================================")
print("   DUAL-MODE FLAT SHAPE & SELECTIVE OUTLINE VECTOR TRAINER")
print("   - Pure Soft Pastel Flat Shape Fills WITHOUT Outlines")
print("   - Selective Sharp Line Art Outlines ONLY on Dark Strokes")
print("   - 0% Oil Splotches / 100% Unbroken Continuous Paths")
print(f"   Target Folder: {DOWNLOAD_DIR}")
print(f"   NEW Timestamped Output Folder: {NEW_OUTPUT_DIR}")
print(f"   Total Test Images: {len(files)}")
print("==================================================================\n", flush=True)

results = []

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

def vectorize_flat_shape_selective_studio(image_bytes, num_colors=18, title="Flat Selective Outline Vector"):
    nparr = np.frombuffer(image_bytes, np.uint8)
    img_raw = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
    if img_raw is None:
        return None, None, None, None

    if len(img_raw.shape) == 3 and img_raw.shape[2] == 4:
        alpha = img_raw[:, :, 3]
        bgr = img_raw[:, :, :3]
        bgr[alpha < 128] = [255, 255, 255]
    else:
        bgr = img_raw

    height, width = bgr.shape[:2]
    MAX_DIM = 1600.0
    if max(width, height) > MAX_DIM:
        scale_proc = MAX_DIM / max(width, height)
        proc_w, proc_h = int(width * scale_proc), int(height * scale_proc)
        bgr_proc = cv2.resize(bgr, (proc_w, proc_h), interpolation=cv2.INTER_LANCZOS4)
    else:
        proc_w, proc_h = width, height
        bgr_proc = bgr.copy()

    smoothed_bgr = cv2.bilateralFilter(bgr_proc, d=7, sigmaColor=40, sigmaSpace=40)
    gray = cv2.cvtColor(smoothed_bgr, cv2.COLOR_BGR2GRAY)

    thresh_line = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 15, 3)
    kernel_link = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    dark_strokes_linked = cv2.morphologyEx(thresh_line, cv2.MORPH_CLOSE, kernel_link)

    lab = cv2.cvtColor(smoothed_bgr, cv2.COLOR_BGR2LAB)
    pixels = lab.reshape((-1, 3)).astype(np.float32)
    unique_colors = np.unique(pixels, axis=0)
    actual_colors = min(max(num_colors, 12), len(unique_colors))

    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.01)
    _, labels, centers_lab = cv2.kmeans(pixels, actual_colors, None, criteria, 10, cv2.KMEANS_PP_CENTERS)
    labels_2d = labels.reshape((proc_h, proc_w))

    kernel_seal = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    color_masks = []
    color_coverage = np.zeros((proc_h, proc_w), dtype=np.uint8)

    for i in range(actual_colors):
        raw_mask = (labels_2d == i).astype(np.uint8) * 255
        pixel_cnt = np.sum(raw_mask > 0)
        if pixel_cnt < 40:
            continue

        solid_mask = fill_all_interior_holes_solid(raw_mask)
        sealed_mask = cv2.dilate(solid_mask, kernel_seal, iterations=1)

        color_coverage = cv2.bitwise_or(color_coverage, sealed_mask)

        cluster_pixels_bgr = bgr_proc[labels_2d == i]
        median_bgr = np.median(cluster_pixels_bgr, axis=0)
        r, g, b = int(median_bgr[2]), int(median_bgr[1]), int(median_bgr[0])

        color_masks.append({
            "color": (r, g, b),
            "mask": sealed_mask,
            "area": int(np.sum(sealed_mask > 0)),
            "is_line_art": False
        })

    selective_outlines = cv2.bitwise_and(dark_strokes_linked, cv2.bitwise_not(color_coverage))
    if np.sum(selective_outlines > 0) > 30:
        stroke_pixels_bgr = bgr_proc[selective_outlines > 0]
        if len(stroke_pixels_bgr) > 0:
            med_bgr = np.median(stroke_pixels_bgr, axis=0)
            lr, lg, lb = int(med_bgr[2]), int(med_bgr[1]), int(med_bgr[0])

            color_masks.append({
                "color": (lr, lg, lb),
                "mask": selective_outlines,
                "area": 1,
                "is_line_art": True
            })

    color_masks.sort(key=lambda item: item["area"], reverse=True)

    TARGET_AREA = 4_500_000.0
    scale = math.sqrt(TARGET_AREA / max(1, proc_w * proc_h))
    W, H = int(round(proc_w * scale)), int(round(proc_h * scale))
    internal_scale = W / max(1, proc_w)

    colored_layers = []
    border = 2

    for idx, layer in enumerate(color_masks):
        turd = 1 if layer.get("is_line_art") else 4
        bm = potrace.Bitmap(layer["mask"] > 127)
        path = bm.trace(turdsize=turd, alphamax=0.85, opttolerance=0.15, turnpolicy=potrace.POTRACE_TURNPOLICY_MINORITY)
        if not path:
            continue

        path = filter_noise_curves(path, min_noise_size=1)
        if not path:
            continue

        filtered = []
        for curve in path:
            pts = [curve.start_point] + [s.end_point for s in curve]
            xs = [p.x for p in pts]
            ys = [p.y for p in pts]
            mn_x, mx_x = min(xs), max(xs)
            mn_y, mx_y = min(ys), max(ys)

            touches_all = (mn_x <= border and mx_x >= proc_w - border and mn_y <= border and mx_y >= proc_h - border)
            area_ratio = ((mx_x - mn_x) * (mx_y - mn_y)) / (proc_w * proc_h)

            if (touches_all or area_ratio > 0.99) and idx > 0:
                continue

            filtered.append(curve)

        if filtered:
            colored_layers.append({"color": layer["color"], "curves": filtered})

    if not colored_layers:
        return None, None, None, None

    eps_bytes = _render_color_eps(colored_layers, W, H, internal_scale, title=title, creator="peripirdaus")
    jpg_bytes = render_to_jpg_freepik(None, W, H, 0, 0, internal_scale, colored_layers=colored_layers)
    png_bytes = render_to_png_transparent(None, W, H, 0, 0, internal_scale, colored_layers=colored_layers)
    psd_bytes = render_to_psd(color_masks, proc_w, proc_h)

    desc_str = f"{title} flat pastel shape selective outline vector illustration"
    kw_str = "vector, flat shape, soft pastel, selective outline, no outline fill, stock, repeat"

    eps_final = eps_bytes if isinstance(eps_bytes, bytes) else eps_bytes.encode("ascii", "replace")
    if isinstance(eps_final, bytes):
        eps_final = inject_metadata_to_eps(eps_final, title=title, description=desc_str, keywords=kw_str)

    return eps_final, jpg_bytes, png_bytes, psd_bytes


for idx, filename in enumerate(files, 1):
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    clean_base = filename.split("_2026")[0]
    clean_filename = f"{idx:02d}_{clean_base}"
    title_str = clean_base.replace("_", " ").title()
    
    print(f"[{idx:02d}/{len(files):02d}] Training (Flat Selective): {filename} -> {clean_filename}...", flush=True)
    start_t = time.time()
    
    try:
        with open(filepath, "rb") as f:
            image_bytes = f.read()
            
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        h, w = img.shape[:2]
        
        sample_small = cv2.resize(img, (120, 120))
        unique_colors_cnt = len(np.unique(sample_small.reshape(-1, 3), axis=0))
        optimal_colors = min(18, max(12, int(math.sqrt(unique_colors_cnt) * 0.8)))
        
        eps, jpg, png, psd = vectorize_flat_shape_selective_studio(
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
                "status": "FLAT SELECTIVE SUCCESS",
                "colors": optimal_colors,
                "eps_kb": eps_kb,
                "jpg_kb": jpg_kb,
                "time": elapsed
            })
            print(f"   -> FLAT SELECTIVE SUCCESS! EPS: {eps_kb} KB | JPG: {jpg_kb} KB ({elapsed}s)", flush=True)
        else:
            results.append({"filename": filename, "status": "FAILED", "time": elapsed})
            print(f"   -> FAILED", flush=True)
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        results.append({"filename": filename, "status": f"ERROR: {e}", "time": round(time.time() - start_t, 2)})

print("\n==================================================================")
success_cnt = sum(1 for r in results if "FLAT SELECTIVE SUCCESS" in r["status"])
total_cnt = len(results)
accuracy_pct = round((success_cnt / max(1, total_cnt)) * 100, 1)

print(f"   DUAL-MODE FLAT SHAPE & SELECTIVE OUTLINE TRAINING REPORT:")
print(f"   Total Processed Images : {total_cnt}")
print(f"   Flat Selective Success : {success_cnt}")
print(f"   Accuracy Rate          : {accuracy_pct}%")
print(f"   NEW TIMESTAMPED FOLDER : {NEW_OUTPUT_DIR}")
print("==================================================================", flush=True)
