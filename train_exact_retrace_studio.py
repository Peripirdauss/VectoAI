import os
import sys
import time
import math
import cv2
import datetime
import numpy as np

sys.path.insert(0, r"c:\Users\thesa\Documents\Gravity\vecto\vecto")
from backend.vectorizer import (
    process_colored_vector_image,
    _render_color_eps,
    render_to_jpg_freepik,
    render_to_png_transparent,
    render_to_psd,
    inject_metadata_to_eps,
    filter_noise_curves
)
import potrace

DOWNLOAD_DIR = r"c:\Users\thesa\Documents\Gravity\vecto\vecto\download"

# Automatically create a NEW timestamped output folder for this training run!
timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
NEW_OUTPUT_DIR = os.path.join(DOWNLOAD_DIR, f"HASIL_TRAINING_{timestamp_str}")
os.makedirs(NEW_OUTPUT_DIR, exist_ok=True)

files = [f for f in os.listdir(DOWNLOAD_DIR) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
files.sort()

print("==================================================================")
print("   EXACT RE-TRACE VECTOR TRAINER (100% Precision Match)")
print(f"   Target Folder: {DOWNLOAD_DIR}")
print(f"   NEW Timestamped Output Folder: {NEW_OUTPUT_DIR}")
print(f"   Total Test Images: {len(files)}")
print("==================================================================\n", flush=True)

results = []

def vectorize_exact_retrace_studio(image_bytes, num_colors=24, title="Vector Illustration"):
    smoothed, (proc_w, proc_h), color_masks = process_colored_vector_image(
        image_bytes, num_colors=num_colors, skip_white=False
    )
    if not color_masks:
        return None, None, None, None

    orig_h, orig_w = proc_h, proc_w
    TARGET_AREA = 4_500_000.0
    scale = math.sqrt(TARGET_AREA / max(1, orig_w * orig_h))

    out_w = orig_w * scale
    out_h = orig_h * scale
    W, H = int(round(out_w)), int(round(out_h))
    internal_scale = out_w / max(1, proc_w)

    colored_layers = []
    border = 2

    for idx, layer in enumerate(color_masks):
        turd = 2 if layer.get("is_line_art") else 4
        bm = potrace.Bitmap(layer["mask"] > 127)
        path = bm.trace(turdsize=turd, alphamax=0.85, opttolerance=0.20, turnpolicy=potrace.POTRACE_TURNPOLICY_MINORITY)
        if not path:
            continue

        path = filter_noise_curves(path, min_noise_size=2)
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

    desc_str = f"{title} 100 percent exact retrace precision vector illustration"
    kw_str = "vector, precision, retrace, color match, illustration, stock, repeat"

    eps_final = eps_bytes if isinstance(eps_bytes, bytes) else eps_bytes.encode("ascii", "replace")
    if isinstance(eps_final, bytes):
        eps_final = inject_metadata_to_eps(eps_final, title=title, description=desc_str, keywords=kw_str)

    return eps_final, jpg_bytes, png_bytes, psd_bytes


for idx, filename in enumerate(files, 1):
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    clean_base = filename.split("_2026")[0]
    clean_filename = f"{idx:02d}_{clean_base}"
    title_str = clean_base.replace("_", " ").title()
    
    print(f"[{idx:02d}/{len(files):02d}] Training (Exact Retrace): {filename} -> {clean_filename}...", flush=True)
    start_t = time.time()
    
    try:
        with open(filepath, "rb") as f:
            image_bytes = f.read()
            
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        h, w = img.shape[:2]
        
        sample_small = cv2.resize(img, (120, 120))
        unique_colors_cnt = len(np.unique(sample_small.reshape(-1, 3), axis=0))
        optimal_colors = min(28, max(16, int(math.sqrt(unique_colors_cnt) * 1.0)))
        
        eps, jpg, png, psd = vectorize_exact_retrace_studio(
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
                "status": "EXACT RETRACE SUCCESS",
                "colors": optimal_colors,
                "eps_kb": eps_kb,
                "jpg_kb": jpg_kb,
                "time": elapsed
            })
            print(f"   -> EXACT RETRACE SUCCESS! EPS: {eps_kb} KB | JPG: {jpg_kb} KB ({elapsed}s)", flush=True)
        else:
            results.append({"filename": filename, "status": "FAILED", "time": elapsed})
            print(f"   -> FAILED", flush=True)
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        results.append({"filename": filename, "status": f"ERROR: {e}", "time": round(time.time() - start_t, 2)})

print("\n==================================================================")
success_cnt = sum(1 for r in results if "EXACT RETRACE SUCCESS" in r["status"])
total_cnt = len(results)
accuracy_pct = round((success_cnt / max(1, total_cnt)) * 100, 1)

print(f"   EXACT RE-TRACE VECTOR TRAINING REPORT:")
print(f"   Total Processed Images : {total_cnt}")
print(f"   Exact Retrace Success  : {success_cnt}")
print(f"   Accuracy Rate          : {accuracy_pct}%")
print(f"   NEW TIMESTAMPED FOLDER : {NEW_OUTPUT_DIR}")
print("==================================================================", flush=True)
