# Vecto: User Instructions & Guide

Welcome to **Vecto**, your professional-grade bulk vectorization tool. This guide covers how to use the tool effectively, how to handle the "Invert Colors" features, and best practices for exporting to microstock platforms like Shutterstock, Pngtree, and Vecteezy.

---

## 1. Starting and Stopping the Server

### Cara Cepat (Windows Batch Scripts):
1. **Start Server**: Cukup double-click atau jalankan `run.bat` di root project.
   - Script ini otomatis menjalankan backend (FastAPI pada port `8001`), frontend (Vite pada port `5174`), dan membuka browser secara otomatis.
2. **Stop Server**: Double-click atau jalankan `stop.bat` di root project.
   - Script ini otomatis mematikan semua process yang berjalan di port `8001` (backend) dan `5174` (frontend).

### Cara Manual:

**Backend (FastAPI):**
* *Windows (PowerShell):*
  ```powershell
  $env:PYTHONPATH="."
  .\backend\venv\Scripts\python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
  ```
* *macOS/Linux:*
  ```bash
  PYTHONPATH=. ./backend/venv/bin/python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
  ```

**Frontend (React/Vite):**
* Buka terminal baru:
  ```bash
  cd frontend
  npm run dev
  ```
* Buka browser di `http://localhost:5174`.

---

## 2. Cara Tunnelling (Akses dari Internet / Device Lain)

Untuk mengakses VectoAI dari luar jaringan lokal atau sharing ke device lain:

### Cara Praktis:
Jalankan script `tunnel.bat` yang sudah disediakan di root folder:
```cmd
tunnel.bat
```
Pilih opsi:
- **[1] localtunnel**: Menggunakan `npx localtunnel --port 5174`. Tidak butuh login, cepat.
- **[2] cloudflared**: Menggunakan Cloudflare Tunnel (`cloudflared tunnel --url http://localhost:5174`). Sangat stabil dan tidak memerlukan konfigurasi tambahan.

### Cara Manual via Terminal:
- Menggunakan **Cloudflare Tunnel**:
  ```bash
  cloudflared tunnel --url http://localhost:5174
  ```
- Menggunakan **Localtunnel**:
  ```bash
  npx localtunnel --port 5174
  ```
- Menggunakan **Ngrok** (jika terinstall):
  ```bash
  ngrok http 5174
  ```

---

## 3. Using the Vecto Interface

1. **Upload Images**: Drag and drop your raster images (PNG, JPG, JPEG) into the upload area, or click to select files. Vecto supports both single files and bulk uploads (e.g., an entire folder of icons).
2. **Preview Mode**: Click on any uploaded file in the list to see a live "selection mask". This mask shows exactly what the vectorizer sees.
    * **White shape** = What will be turned into a vector.
    * **Black shape** = What will be ignored/cut out as the transparent background.
3. **Thresholding**: Adjust the threshold slider if the preview looks too thin or too thick. For most modern AI-generated icons (like Gemini), leave it at 127.

---

## 4. The "Invert Colors" Feature (Crucial)

Vecto features a highly intelligent "Auto-Polarity Detection" engine. This means that 99% of the time, the tool automatically knows what the icon is and what the background is, regardless of whether your image is light-on-dark or dark-on-light.

However, sometimes you need manual control:
* **Checkbox OFF (Default)**: The engine traces the icons as positive solid shapes. Use this for standard icon sets.
* **Checkbox ON (Inverted)**: The engine swaps the foreground and background before tracing.
* **When to use Invert**: If your preview looks like a solid white block with black "holes" outlining your icons, check the box! This will flip the polarity and ensure your output contains standard vector paths instead of an inverted mask.

---

## 5. Understanding the Exported Files

Vecto outputs professional formats explicitly tailored for microstock and professional software (Adobe Illustrator, Affinity Designer).

* **EPS (Vector)**: The industry standard. Vecto creates strictly compliant EPSF-3.0 Level 2 files without illegal multi-page headers or custom abbreviations. When opened in Illustrator, your icons will be accurately layered grouped blocks.
* **SVG (Web)**: Perfect for UI/UX developers. Exports cleanly layered `<g>` tags perfect for direct HTML embedding or Figma.

**Note on Filenames**: Every time you download, Vecto appends a unique timestamp to the filename (e.g., `filename_4821.eps`). This guarantees your browser uses the most recently generated version and prevents caching old, blank files.

---

## 6. Submitting to Microstock Agencies

Vecto is tuned to comply with the stringent requirements of agencies like Shutterstock:

1. **Layer Separation**: Vecto groups each icon's curves individually (`gsave`/`grestore`). Reviewers require multi-icon sheets to be easily separable by the customer. Vecto does this automatically.
2. **Rich Black**: Vecto natively exports paths in true Rich Black (`0 0 0 setrgbcolor`), meeting the technical requirement for flat monochrome exports.
3. **No Shells/Bounding Boxes**: Vecto's adaptive heuristic automatically strips out the giant "background frame" that standard auto-tracers often leave behind, ensuring you only upload clean icons without a hidden giant white square blocking them.
4. **Artboard Scaling**: Vecto mathematically scales all outputs to ensure the artwork bounding box exceeds the strict **4 Megapixel** minimum requirement for microstock platforms like Shutterstock (typically yielding an area around 4.5 Megapixels).

---

## 7. Troubleshooting

* **Blank/Empty File in Illustrator**: If you uploaded a heavily compressed JPEG or an image with absolute zero mathematical contrast between background and foreground, adjust the `Threshold` slider inside the Vecto UI until you see crisp white shapes in the preview, then download again.
* **Icons are "Holes" inside a Black Box**: You accidentally vectorized inverted contours. Go back, toggle the **Invert Colors** checkbox, and download again.

If you have any other issues, remember to review both the backend terminal (for path counts) and the frontend console!
