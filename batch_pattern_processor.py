import os
import sys
import time
import math
import cv2
import numpy as np

sys.path.insert(0, r"c:\Users\thesa\Documents\Gravity\vecto\vecto")
from backend.vectorizer import vectorize_shutterstock_pattern, vectorize_shutterstock

DOWNLOAD_DIR = r"c:\Users\thesa\Documents\Gravity\vecto\vecto\download"
OUTPUT_DIR = os.path.join(DOWNLOAD_DIR, "output_vectors")
os.makedirs(OUTPUT_DIR, exist_ok=True)

files = [f for f in os.listdir(DOWNLOAD_DIR) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
files.sort()

print(f"==================================================")
print(f" Starting Batch Pattern Vector Engine Training ")
print(f" Target Directory: {DOWNLOAD_DIR}")
print(f" Found {len(files)} pattern images to process.")
print(f"==================================================\n")

results = []

for idx, filename in enumerate(files, 1):
    filepath = os.path.join(DOWNLOAD_DIR, filename)
    base_name = os.path.splitext(filename)[0]
    
    print(f"[{idx}/{len(files)}] Processing: {filename}...")
    start_t = time.time()
    
    try:
        with open(filepath, "rb") as f:
            image_bytes = f.read()
            
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        h, w = img.shape[:2]
        
        sample_small = cv2.resize(img, (150, 150))
        unique_colors_cnt = len(np.unique(sample_small.reshape(-1, 3), axis=0))
        optimal_colors = min(20, max(10, int(math.sqrt(unique_colors_cnt) * 0.8)))
        
        title_str = base_name.replace("_", " ").title()
        
        eps, jpg, png, psd = vectorize_shutterstock_pattern(
            image_bytes, 
            num_colors=optimal_colors, 
            title=title_str, 
            description=f"{title_str} seamless pattern vector illustration", 
            keywords="pattern, seamless, vector, background, illustration, repeat"
        )
        
        if not eps or not jpg:
            eps, jpg, png, psd = vectorize_shutterstock(
                image_bytes,
                mode="color",
                num_colors=optimal_colors,
                title=title_str,
                description=f"{title_str} seamless pattern vector illustration",
                keywords="pattern, seamless, vector, background, illustration, repeat"
            )
            
        elapsed = round(time.time() - start_t, 2)
        
        if eps and jpg:
            eps_file = os.path.join(OUTPUT_DIR, f"{base_name}.eps")
            jpg_file = os.path.join(OUTPUT_DIR, f"{base_name}.jpg")
            png_file = os.path.join(OUTPUT_DIR, f"{base_name}.png")
            psd_file = os.path.join(OUTPUT_DIR, f"{base_name}.psd")
            
            with open(eps_file, "wb") as f:
                f.write(eps)
            with open(jpg_file, "wb") as f:
                f.write(jpg)
            if png:
                with open(png_file, "wb") as f:
                    f.write(png)
            if psd:
                with open(psd_file, "wb") as f:
                    f.write(psd)
                    
            status_item = {
                "file": filename,
                "status": "SUCCESS (100%)",
                "eps_kb": round(len(eps) / 1024, 1),
                "jpg_kb": round(len(jpg) / 1024, 1),
                "png_kb": round(len(png) / 1024, 1) if png else 0,
                "psd_kb": round(len(psd) / 1024, 1) if psd else 0,
                "colors_used": optimal_colors,
                "time_sec": elapsed
            }
            results.append(status_item)
            print(f"   -> SUCCESS! EPS: {status_item['eps_kb']} KB | JPG: {status_item['jpg_kb']} KB | PSD: {status_item['psd_kb']} KB ({elapsed}s)")
        else:
            results.append({"file": filename, "status": "FAILED", "time_sec": elapsed})
            print(f"   -> FAILED to vectorize image.")
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        results.append({"file": filename, "status": f"ERROR: {e}", "time_sec": round(time.time() - start_t, 2)})

print("\n==================================================")
success_cnt = sum(1 for r in results if "SUCCESS" in r["status"])
total_cnt = len(results)
success_pct = round((success_cnt / max(1, total_cnt)) * 100, 1)
print(f" Batch Training Complete!")
print(f" Total Processed: {total_cnt}")
print(f" Success Rate: {success_pct}% ({success_cnt}/{total_cnt})")
print(f" Output Folder: {OUTPUT_DIR}")
print("==================================================")
