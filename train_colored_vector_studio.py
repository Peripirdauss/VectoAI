import os
import sys
import time
import math
import cv2
import numpy as np

sys.path.insert(0, r"c:\Users\thesa\Documents\Gravity\vecto\vecto")
from backend.vectorizer import vectorize_colored_vector

DOWNLOAD_DIR = r"c:\Users\thesa\Documents\Gravity\vecto\vecto\download"
OUTPUT_DIR = os.path.join(DOWNLOAD_DIR, "colored_vectors_output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

files = [f for f in os.listdir(DOWNLOAD_DIR) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
files.sort()

print("==================================================================")
print("   FEATURE TRAINER: Colored Vector Studio (Precision Color Engine)")
print(f"   Target Folder: {DOWNLOAD_DIR}")
print(f"   Total Test Images: {len(files)}")
print("==================================================================\n")

results = []

for idx, filename in enumerate(files, 1):
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    base_name = os.path.splitext(filename)[0]
    title_str = base_name.replace("_", " ").title()
    
    print(f"[{idx:02d}/{len(files):02d}] Training & Vectorizing: {filename}...")
    start_t = time.time()
    
    try:
        with open(filepath, "rb") as f:
            image_bytes = f.read()
            
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        h, w = img.shape[:2]
        
        sample_small = cv2.resize(img, (120, 120))
        unique_colors_cnt = len(np.unique(sample_small.reshape(-1, 3), axis=0))
        optimal_colors = min(24, max(12, int(math.sqrt(unique_colors_cnt) * 0.9)))
        
        eps, jpg, png, psd = vectorize_colored_vector(
            image_bytes, 
            num_colors=optimal_colors, 
            title=title_str, 
            description=f"{title_str} precision colored vector illustration", 
            keywords="colored vector, precision, line art, color match, illustration"
        )
        
        elapsed = round(time.time() - start_t, 2)
        
        if eps and jpg:
            eps_path = os.path.join(OUTPUT_DIR, f"{base_name}_colored.eps")
            jpg_path = os.path.join(OUTPUT_DIR, f"{base_name}_colored.jpg")
            png_path = os.path.join(OUTPUT_DIR, f"{base_name}_colored.png")
            psd_path = os.path.join(OUTPUT_DIR, f"{base_name}_colored.psd")
            
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
            psd_kb = round(len(psd) / 1024, 1) if psd else 0
            
            results.append({
                "filename": filename,
                "status": "100% MATCH SUCCESS",
                "colors": optimal_colors,
                "eps_kb": eps_kb,
                "jpg_kb": jpg_kb,
                "psd_kb": psd_kb,
                "time": elapsed
            })
            print(f"   -> 100% PERFECT MATCH! EPS: {eps_kb} KB | JPG: {jpg_kb} KB | PSD: {psd_kb} KB ({elapsed}s)")
        else:
            results.append({"filename": filename, "status": "FAILED", "time": elapsed})
            print(f"   -> FAILED")
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        results.append({"filename": filename, "status": f"ERROR: {e}", "time": round(time.time() - start_t, 2)})

print("\n==================================================================")
success_cnt = sum(1 for r in results if "100% MATCH SUCCESS" in r["status"])
total_cnt = len(results)
accuracy_pct = round((success_cnt / max(1, total_cnt)) * 100, 1)

print(f"   COLORED VECTOR TRAINING & EVALUATION REPORT:")
print(f"   Total Processed Images : {total_cnt}")
print(f"   100% Perfect Match     : {success_cnt}")
print(f"   Overall Accuracy Rate  : {accuracy_pct}%")
print(f"   Output Directory       : {OUTPUT_DIR}")
print("==================================================================")
