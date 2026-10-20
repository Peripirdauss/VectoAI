import asyncio
import base64
import io
import os
import re
import time
import zipfile
import importlib
import numpy as np
import cv2
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor
from pydantic import BaseModel

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

import backend.vectorizer as _vec_module
from backend.vectorizer import (
    process_image, vectorize, process_color_image, vectorize_color,
    vectorize_vision_ai, sanitize_svg_for_microstock,
    vectorize_freepik, vectorize_adobe_stock, vectorize_vecteezy, vectorize_shutterstock, vectorize_shutterstock_pattern, preflight_check,
    analyze_seamless_continuity, generate_3x3_tile_preview, vectorize_seamless_pattern_tiled, slice_grid_icons
)
from backend.duplicate_finder import find_duplicates_in_batch
from backend.ftp_uploader import test_ftp_connection, upload_files_to_ftp
from backend.metadata_verifier import inspect_image_metadata, clean_and_inject_jpg

app = FastAPI(title="Vecto Studio API")

# Calculate optimal CPU worker threads for parallel batch vectorization
MAX_WORKERS = min(32, (os.cpu_count() or 4) * 2)

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def str_to_bool(val) -> bool:
    if isinstance(val, bool): return val
    return str(val).lower() in ("true", "1", "yes")

def parse_grid_layout(layout: str) -> tuple[int, int]:
    layout = (layout or "3x3").strip().lower()
    if layout == "2x2":
        return 2, 2
    elif layout == "4x4":
        return 4, 4
    elif layout == "3x4":
        return 3, 4
    elif layout == "4x3":
        return 4, 3
    else:
        return 3, 3 # Default 3x3 collection sheet

def sanitize_filename(filename: str) -> str:
    base_name = filename.rsplit('.', 1)[0]
    safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', base_name)
    safe_name = re.sub(r'_+', '_', safe_name).strip('_')
    return safe_name or "vectorized"


def _sync_preview(contents: bytes, threshold: int, inv: bool, mode: str, num_colors: int, filter_speckle: int = 4, color_precision: int = 8, hierarchical: str = "stacked", corner_threshold: int = 60, curve_mode: str = "spline", length_threshold: float = 10.0, splice_threshold: int = 55, pre_smoothing: bool = True):
    if mode == "vision":
        try:
            import os
            if "/opt/homebrew/lib" not in os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", ""):
                os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = f"/opt/homebrew/lib:{os.environ.get('DYLD_FALLBACK_LIBRARY_PATH', '')}"
            import vtracer

            t0 = time.time()
            trace_bytes = contents
            if pre_smoothing:
                try:
                    nparr = np.frombuffer(contents, np.uint8)
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
                    trace_bytes = contents

            svg_str = vtracer.convert_raw_image_to_svg(
                trace_bytes,
                colormode="color",
                hierarchical=hierarchical,
                mode=curve_mode,
                filter_speckle=int(filter_speckle),
                color_precision=int(color_precision),
                layer_difference=16,
                corner_threshold=int(corner_threshold),
                length_threshold=float(length_threshold),
                splice_threshold=int(splice_threshold),
                max_iterations=15,
                path_precision=2
            )
            if not svg_str:
                return None, None, None

            # Microstock Sanitizer: Remove stray sub-pixel dust points
            svg_str, strays_removed = sanitize_svg_for_microstock(svg_str)

            elapsed = time.time() - t0
            paths_count = len(re.findall(r'<path\b', svg_str))
            nodes_count = len(re.findall(r'[MLCQZmlcqz]', svg_str))
            colors = set(re.findall(r'fill="([^"]+)"', svg_str))
            b64_svg = base64.b64encode(svg_str.encode('utf-8')).decode('utf-8')
            
            stats = {
                "paths": paths_count,
                "nodes": nodes_count,
                "strays_removed": strays_removed,
                "colors": len(colors),
                "mode": curve_mode,
                "hierarchical": hierarchical,
                "time_ms": round(elapsed * 1000, 1),
                "microstock_ready": True
            }
            return f"data:image/svg+xml;base64,{b64_svg}", stats, svg_str
        except Exception as err:
            print("Vision preview error:", err)
            # fallback to color preview
            preview_img, _, _ = process_color_image(contents, num_colors=num_colors)
            if preview_img is None: return None, None, None
            _, encoded_img = cv2.imencode('.png', preview_img)
            return f"data:image/png;base64,{base64.b64encode(encoded_img).decode('utf-8')}", None, None

    elif mode == "color":
        preview_img, _, _ = process_color_image(contents, num_colors=num_colors)
    else:
        preview_img, _ = process_image(contents, threshold_val=threshold, invert=inv)
    
    if preview_img is None:
        return None, None, None
    
    _, encoded_img = cv2.imencode('.png', preview_img)
    return f"data:image/png;base64,{base64.b64encode(encoded_img).decode('utf-8')}", None, None


@app.post("/api/preview")
async def preview_threshold(
    file: UploadFile = File(...),
    threshold: int = Form(127),
    invert: str = Form("false"),
    mode: str = Form("vision"),
    numColors: int = Form(4),
    filterSpeckle: int = Form(4),
    colorPrecision: int = Form(8),
    hierarchical: str = Form("stacked"),
    cornerThreshold: int = Form(60),
    curveMode: str = Form("spline"),
    lengthThreshold: float = Form(10.0),
    spliceThreshold: int = Form(55),
    preSmoothing: str = Form("true")
):
    try:
        inv = str_to_bool(invert)
        smooth = str_to_bool(preSmoothing)
        contents = await file.read()
        preview_url, stats, svg_raw = await asyncio.to_thread(
            _sync_preview, contents, threshold, inv, mode, numColors, filterSpeckle, colorPrecision, hierarchical, cornerThreshold, curveMode, lengthThreshold, spliceThreshold, smooth
        )
        if preview_url is None:
            raise HTTPException(status_code=400, detail="Invalid image")
        return {"preview": preview_url, "stats": stats, "svg": svg_raw}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def _sync_vectorize(contents: bytes, format: str, threshold: int, inv: bool, mode: str, num_colors: int, filename: str = "vectorized", title: str = None, creator: str = "peripirdaus", opttolerance: float = 0.1, alphamax: float = 1.0, description: str = "", keywords: str = "", filter_speckle: int = 4, color_precision: int = 8, hierarchical: str = "stacked", corner_threshold: int = 60, curve_mode: str = "spline", length_threshold: float = 10.0, splice_threshold: int = 55, pre_smoothing: bool = True):
    eps_title = title or f"{sanitize_filename(filename)}.{format.lower()}"
    if mode == "vision":
        return vectorize_vision_ai(
            contents,
            fmt=format,
            colormode="color",
            hierarchical=hierarchical,
            mode=curve_mode,
            filter_speckle=filter_speckle,
            color_precision=color_precision,
            corner_threshold=corner_threshold,
            length_threshold=length_threshold,
            splice_threshold=splice_threshold,
            pre_smoothing=pre_smoothing,
            title=eps_title,
            creator=creator,
            description=description,
            keywords=keywords
        )
    elif mode == "color":
        _, (width, height), color_masks = process_color_image(contents, num_colors=num_colors)
        if not color_masks:
            return None
        return vectorize_color(color_masks, width, height, fmt=format, title=eps_title, creator=creator, opttolerance=opttolerance, alphamax=alphamax, description=description, keywords=keywords)
    else:
        thresh_img, (width, height) = process_image(contents, threshold_val=threshold, invert=inv)
        if thresh_img is None:
            return None
        return vectorize(thresh_img, width, height, fmt=format, title=eps_title, creator=creator, opttolerance=opttolerance, alphamax=alphamax, description=description, keywords=keywords)


@app.post("/api/vectorize")
async def vectorize_image_endpoint(
    file: UploadFile = File(...),
    format: str = Form("eps"),
    threshold: int = Form(127),
    invert: str = Form("false"),
    mode: str = Form("vision"),
    numColors: int = Form(4),
    creator: str = Form("peripirdaus"),
    opttolerance: float = Form(0.1),
    alphamax: float = Form(1.0),
    title: str = Form(""),
    description: str = Form(""),
    keywords: str = Form(""),
    filterSpeckle: int = Form(4),
    colorPrecision: int = Form(8),
    hierarchical: str = Form("stacked"),
    cornerThreshold: int = Form(60),
    curveMode: str = Form("spline"),
    lengthThreshold: float = Form(10.0),
    spliceThreshold: int = Form(55),
    preSmoothing: str = Form("true")
):
    try:
        inv = str_to_bool(invert)
        smooth = str_to_bool(preSmoothing)
        contents = await file.read()
        vec_data = await asyncio.to_thread(
            _sync_vectorize, contents, format, threshold, inv, mode, numColors, file.filename, title or None, creator, opttolerance, alphamax, description, keywords, filterSpeckle, colorPrecision, hierarchical, cornerThreshold, curveMode, lengthThreshold, spliceThreshold, smooth
        )
        
        if vec_data is None:
            raise HTTPException(status_code=400, detail="Tidak ada ikon terdeteksi.")
        
        safe_name = sanitize_filename(file.filename)
        ext = format.lower()
        filename = f"{safe_name}.{ext}"
        media_type = "application/postscript" if ext == "eps" else "image/svg+xml"
        
        return Response(
            content=vec_data if isinstance(vec_data, bytes) else vec_data.encode(),
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def _sync_bulk_vectorize(files_data: list, format: str, threshold: int, inv: bool, mode: str, num_colors: int, title: str = "", description: str = "", keywords: str = "", filter_speckle: int = 4, color_precision: int = 8, hierarchical: str = "stacked", corner_threshold: int = 60, curve_mode: str = "spline", length_threshold: float = 10.0, splice_threshold: int = 55, pre_smoothing: bool = True):
    zip_buffer = io.BytesIO()
    ext = format.lower()
    
    def _proc_item(args):
        i, (orig_filename, contents) = args
        eps_title = title or f"{sanitize_filename(orig_filename)}_{i+1}.{ext}"
        if mode == "vision":
            vec_data = vectorize_vision_ai(
                contents,
                fmt=format,
                colormode="color",
                hierarchical=hierarchical,
                mode=curve_mode,
                filter_speckle=filter_speckle,
                color_precision=color_precision,
                corner_threshold=corner_threshold,
                length_threshold=length_threshold,
                splice_threshold=splice_threshold,
                pre_smoothing=pre_smoothing,
                title=eps_title,
                description=description,
                keywords=keywords
            )
        elif mode == "color":
            _, (width, height), color_masks = process_color_image(contents, num_colors=num_colors)
            vec_data = vectorize_color(color_masks, width, height, fmt=format, title=eps_title, description=description, keywords=keywords) if color_masks else None
        else:
            thresh_img, (width, height) = process_image(contents, threshold_val=threshold, invert=inv)
            vec_data = vectorize(thresh_img, width, height, fmt=format, title=eps_title, description=description, keywords=keywords) if thresh_img is not None else None
        
        if vec_data is not None:
            safe_name = sanitize_filename(orig_filename)
            filename = f"{safe_name}_{i+1}.{ext}"
            data_bytes = vec_data if isinstance(vec_data, bytes) else vec_data.encode()
            return filename, data_bytes
        return None

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        items = list(enumerate(files_data))
        results_raw = executor.map(_proc_item, items)

    written_count = 0
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for res in results_raw:
            if res is not None:
                filename, data_bytes = res
                zip_file.writestr(filename, data_bytes)
                written_count += 1
    
    return zip_buffer.getvalue() if written_count > 0 else None


@app.post("/api/bulk-vectorize")
async def bulk_vectorize_endpoint(
    files: List[UploadFile] = File(...),
    format: str = Form("eps"),
    threshold: int = Form(127),
    invert: str = Form("false"),
    mode: str = Form("vision"),
    numColors: int = Form(4),
    title: str = Form(""),
    description: str = Form(""),
    keywords: str = Form(""),
    filterSpeckle: int = Form(4),
    colorPrecision: int = Form(8),
    hierarchical: str = Form("stacked"),
    cornerThreshold: int = Form(60),
    curveMode: str = Form("spline"),
    lengthThreshold: float = Form(10.0),
    spliceThreshold: int = Form(55),
    preSmoothing: str = Form("true")
):
    try:
        inv = str_to_bool(invert)
        smooth = str_to_bool(preSmoothing)
        files_data = [(f.filename, await f.read()) for f in files]
        
        zip_bytes = await asyncio.to_thread(
            _sync_bulk_vectorize, files_data, format, threshold, inv, mode, numColors, title, description, keywords, filterSpeckle, colorPrecision, hierarchical, cornerThreshold, curveMode, lengthThreshold, spliceThreshold, smooth
        )
        if not zip_bytes:
            raise HTTPException(status_code=400, detail="Tidak ada ikon yang terdeteksi untuk di-vektorisasi.")

        ext = format.lower()
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename=vectorized_{ext}.zip"}
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def _sync_freepik_batch(files_data: list, threshold: int, inv: bool, mode: str, num_colors: int, creator: str = "peripirdaus", split_grid: bool = False, split_layout: str = "3x3", title: str = "", description: str = "", keywords: str = ""):
    def _proc_item(args):
        i, (orig_filename, contents) = args
        safe_name = sanitize_filename(orig_filename)
        eps_title = title or f"{safe_name}.eps"

        if split_grid:
            rows, cols = parse_grid_layout(split_layout)
            tiles = slice_grid_icons(contents, rows=rows, cols=cols)
            if len(tiles) > 1:
                sub_entries = []
                for sub_idx, sub_tile in enumerate(tiles):
                    idx_str = f"icon_{sub_idx + 1}"
                    sub_title = f"{safe_name}_{idx_str}"
                    res1, res2, res3 = vectorize_freepik(
                        sub_tile,
                        threshold_val=threshold,
                        invert=inv,
                        mode=mode,
                        num_colors=num_colors,
                        title=sub_title,
                        creator=creator,
                        split_grid=False,
                        description=description,
                        keywords=keywords
                    )
                    if res1 is not None and res2 is not None:
                        sub_entries.append({
                            "eps_name": f"{safe_name}_{idx_str}.eps",
                            "jpg_name": f"{safe_name}_{idx_str}.jpg",
                            "png_name": f"{safe_name}_{idx_str}.png",
                            "eps_b64": base64.b64encode(res1 if isinstance(res1, bytes) else res1.encode()).decode(),
                            "jpg_b64": base64.b64encode(res2).decode(),
                            "png_b64": base64.b64encode(res3).decode() if res3 else "",
                        })
                if sub_entries:
                    return sub_entries

        res1, res2, res3 = vectorize_freepik(
            contents,
            threshold_val=threshold,
            invert=inv,
            mode=mode,
            num_colors=num_colors,
            title=eps_title,
            creator=creator,
            split_grid=split_grid,
            description=description,
            keywords=keywords
        )
        if res1 is None:
            return None

        # Check if legacy grid auto-splitter produced sub-items
        if res2 is True and isinstance(res1, list):
            sub_entries = []
            for sub in res1:
                idx_str = f"icon_{sub['sub_index']}"
                sub_entries.append({
                    "eps_name": f"{safe_name}_{idx_str}.eps",
                    "jpg_name": f"{safe_name}_{idx_str}.jpg",
                    "png_name": f"{safe_name}_{idx_str}.png",
                    "eps_b64": base64.b64encode(sub["eps"]).decode(),
                    "jpg_b64": base64.b64encode(sub["jpg"]).decode(),
                    "png_b64": base64.b64encode(sub["png"]).decode(),
                })
            return sub_entries
        else:
            eps_data, jpg_data, png_data = res1, res2, res3
            item_name = f"{safe_name}_{i+1}" if len(files_data) > 1 else safe_name
            item = {
                "eps_name": f"{item_name}.eps",
                "jpg_name": f"{item_name}.jpg",
                "eps_b64": base64.b64encode(eps_data if isinstance(eps_data, bytes) else eps_data.encode()).decode(),
                "jpg_b64": base64.b64encode(jpg_data).decode(),
            }
            if png_data:
                item["png_name"] = f"{item_name}.png"
                item["png_b64"] = base64.b64encode(png_data).decode()
            return [item]

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        items = list(enumerate(files_data))
        results_raw = executor.map(_proc_item, items)

    results = []
    for r in results_raw:
        if r:
            results.extend(r)
    return results


@app.post("/api/freepik-vectorize")
async def freepik_vectorize_endpoint(
    files: List[UploadFile] = File(...),
    threshold: int = Form(127),
    invert: str = Form("false"),
    mode: str = Form("monochrome"),
    numColors: int = Form(4),
    creator: str = Form("peripirdaus"),
    splitGrid: str = Form("false"),
    splitLayout: str = Form("3x3"),
    title: str = Form(""),
    description: str = Form(""),
    keywords: str = Form("")
):
    try:
        inv = str_to_bool(invert)
        split_g = str_to_bool(splitGrid)
        files_data = [(f.filename, await f.read()) for f in files]
        
        results = await asyncio.to_thread(_sync_freepik_batch, files_data, threshold, inv, mode, numColors, creator, split_g, splitLayout, title, description, keywords)
        if not results:
            raise HTTPException(status_code=400, detail="Tidak ada ikon yang terdeteksi untuk Freepik.")

        return {"files": results}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def _sync_shutterstock_batch(files_data: list, num_colors: int, creator: str = "peripirdaus", dilation_px: int = 1, title: str = "", description: str = "", keywords: str = ""):
    def _proc_item(args):
        i, (orig_filename, contents) = args
        safe_name = sanitize_filename(orig_filename)
        eps_title = title or f"{safe_name}.eps"
        eps_data, jpg_data, png_data, psd_data = vectorize_shutterstock_pattern(
            contents,
            num_colors=num_colors,
            title=eps_title,
            creator=creator,
            dilation_px=dilation_px,
            description=description,
            keywords=keywords
        )
        if eps_data is not None and jpg_data is not None:
            item_name = f"{safe_name}_{i+1}" if len(files_data) > 1 else safe_name
            item = {
                "eps_name": f"{item_name}.eps",
                "jpg_name": f"{item_name}.jpg",
                "eps_b64": base64.b64encode(eps_data if isinstance(eps_data, bytes) else eps_data.encode()).decode(),
                "jpg_b64": base64.b64encode(jpg_data).decode(),
            }
            if png_data:
                item["png_name"] = f"{item_name}.png"
                item["png_b64"] = base64.b64encode(png_data).decode()
            if psd_data:
                item["psd_name"] = f"{item_name}.psd"
                item["psd_b64"] = base64.b64encode(psd_data).decode()
            return item
        return None

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        items = list(enumerate(files_data))
        results_raw = executor.map(_proc_item, items)

    results = [r for r in results_raw if r is not None]
    return results


@app.post("/api/shutterstock-vectorize")
async def shutterstock_vectorize_endpoint(
    files: List[UploadFile] = File(...),
    numColors: int = Form(8),
    creator: str = Form("peripirdaus"),
    dilationPx: int = Form(1),
    title: str = Form(""),
    description: str = Form(""),
    keywords: str = Form("")
):
    try:
        files_data = [(f.filename, await f.read()) for f in files]
        results = await asyncio.to_thread(_sync_shutterstock_batch, files_data, numColors, creator, dilationPx, title, description, keywords)
        if not results:
            raise HTTPException(status_code=400, detail="Tidak ada gambar pattern yang terdeteksi untuk Shutterstock.")

        return {"files": results}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def _sync_shutterstock_standard_batch(files_data: list, threshold: int, inv: bool, mode: str, num_colors: int, creator: str = "peripirdaus", split_grid: bool = False, split_layout: str = "3x3", title: str = "", description: str = "", keywords: str = ""):
    def _proc_item(args):
        i, (orig_filename, contents) = args
        safe_name = sanitize_filename(orig_filename)
        eps_title = title or f"{safe_name}.eps"

        if split_grid:
            rows, cols = parse_grid_layout(split_layout)
            tiles = slice_grid_icons(contents, rows=rows, cols=cols)
            if len(tiles) > 1:
                sub_entries = []
                for sub_idx, sub_tile in enumerate(tiles):
                    idx_str = f"icon_{sub_idx + 1}"
                    sub_title = f"{safe_name}_{idx_str}"
                    eps_data, jpg_data, png_data, psd_data = vectorize_shutterstock(
                        sub_tile,
                        threshold_val=threshold,
                        invert=inv,
                        mode=mode,
                        num_colors=num_colors,
                        title=sub_title,
                        creator=creator,
                        description=description,
                        keywords=keywords
                    )
                    if eps_data is not None and jpg_data is not None:
                        entry = {
                            "eps_name": f"{safe_name}_{idx_str}.eps",
                            "jpg_name": f"{safe_name}_{idx_str}.jpg",
                            "eps_b64": base64.b64encode(eps_data if isinstance(eps_data, bytes) else eps_data.encode()).decode(),
                            "jpg_b64": base64.b64encode(jpg_data).decode(),
                        }
                        if png_data:
                            entry["png_name"] = f"{safe_name}_{idx_str}.png"
                            entry["png_b64"] = base64.b64encode(png_data).decode()
                        if psd_data:
                            entry["psd_name"] = f"{safe_name}_{idx_str}.psd"
                            entry["psd_b64"] = base64.b64encode(psd_data).decode()
                        sub_entries.append(entry)
                if sub_entries:
                    return sub_entries

        eps_data, jpg_data, png_data, psd_data = vectorize_shutterstock(
            contents,
            threshold_val=threshold,
            invert=inv,
            mode=mode,
            num_colors=num_colors,
            title=eps_title,
            creator=creator,
            description=description,
            keywords=keywords
        )
        if eps_data is not None and jpg_data is not None:
            item_name = f"{safe_name}_{i+1}" if len(files_data) > 1 else safe_name
            item = {
                "eps_name": f"{item_name}.eps",
                "jpg_name": f"{item_name}.jpg",
                "eps_b64": base64.b64encode(eps_data if isinstance(eps_data, bytes) else eps_data.encode()).decode(),
                "jpg_b64": base64.b64encode(jpg_data).decode(),
            }
            if png_data:
                item["png_name"] = f"{item_name}.png"
                item["png_b64"] = base64.b64encode(png_data).decode()
            if psd_data:
                item["psd_name"] = f"{item_name}.psd"
                item["psd_b64"] = base64.b64encode(psd_data).decode()
            return [item]
        return None

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        items = list(enumerate(files_data))
        results_raw = executor.map(_proc_item, items)

    results = []
    for r in results_raw:
        if r is not None:
            if isinstance(r, list):
                results.extend(r)
            else:
                results.append(r)
    return results


@app.post("/api/shutterstock-vectorize-standard")
async def shutterstock_vectorize_standard_endpoint(
    files: List[UploadFile] = File(...),
    threshold: int = Form(127),
    invert: str = Form("false"),
    mode: str = Form("monochrome"),
    numColors: int = Form(4),
    creator: str = Form("peripirdaus"),
    splitGrid: str = Form("false"),
    splitLayout: str = Form("3x3"),
    title: str = Form(""),
    description: str = Form(""),
    keywords: str = Form("")
):
    try:
        inv = str_to_bool(invert)
        split_g = str_to_bool(splitGrid)
        files_data = [(f.filename, await f.read()) for f in files]
        results = await asyncio.to_thread(_sync_shutterstock_standard_batch, files_data, threshold, inv, mode, numColors, creator, split_g, splitLayout, title, description, keywords)
        if not results:
            raise HTTPException(status_code=400, detail="Tidak ada ikon / vektor yang terdeteksi untuk Shutterstock.")

        return {"files": results}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/pattern/test-tile")
async def test_seamless_pattern_tile_endpoint(
    file: UploadFile = File(...)
):
    try:
        contents = await file.read()
        analysis = await asyncio.to_thread(analyze_seamless_continuity, contents)
        preview_b64 = await asyncio.to_thread(generate_3x3_tile_preview, contents, 3)
        
        return {
            "analysis": analysis,
            "preview_3x3": f"data:image/png;base64,{preview_b64}" if preview_b64 else None
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/pattern/vectorize-tiled")
async def vectorize_seamless_pattern_tiled_endpoint(
    file: UploadFile = File(...),
    numColors: int = Form(16),
    format: str = Form("eps"),
    mode: str = Form("color"),
    creator: str = Form("peripirdaus")
):
    try:
        contents = await file.read()
        safe_name = sanitize_filename(file.filename)
        vec_bytes, jpg_bytes, png_bytes = await asyncio.to_thread(
            vectorize_seamless_pattern_tiled,
            contents,
            num_colors=numColors,
            grid_rows=3,
            grid_cols=3,
            title=f"{safe_name}_pattern.{format.lower()}",
            creator=creator,
            fmt=format,
            mode=mode
        )
        if not vec_bytes:
            raise HTTPException(status_code=400, detail="Gagal mengolah vektor pattern.")

        zip_buffer = io.BytesIO()
        ext = format.lower()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            zip_file.writestr(f"{safe_name}_3x3_repeat.{ext}", vec_bytes)
            if jpg_bytes:
                zip_file.writestr(f"{safe_name}_3x3_repeat.jpg", jpg_bytes)
            if png_bytes:
                zip_file.writestr(f"{safe_name}_3x3_repeat.png", png_bytes)

        return Response(
            content=zip_buffer.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename={safe_name}_seamless_vector_pack.zip"}
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def _sync_adobe_batch(files_data: list, threshold: int, inv: bool, mode: str, num_colors: int, fill_holes: bool, format: str, creator: str = "peripirdaus", title: str = "", description: str = "", keywords: str = ""):
    zip_buffer = io.BytesIO()
    ext = format.lower()
    is_bulk = len(files_data) > 1
    
    if not is_bulk:
        orig_filename, contents = files_data[0]
        safe_name = sanitize_filename(orig_filename)
        vec_data = vectorize_adobe_stock(
            contents,
            threshold_val=threshold,
            invert=inv,
            mode=mode,
            num_colors=num_colors,
            fill_holes=fill_holes,
            fmt=ext,
            title=title or f"{safe_name}.{ext}",
            creator=creator,
            description=description,
            keywords=keywords
        )
        return vec_data, False
    else:
        def _proc_item(args):
            i, (orig_filename, contents) = args
            safe_name = sanitize_filename(orig_filename)
            vec_data = vectorize_adobe_stock(
                contents,
                threshold_val=threshold,
                invert=inv,
                mode=mode,
                num_colors=num_colors,
                fill_holes=fill_holes,
                fmt=ext,
                title=title or f"{safe_name}_{i+1}.{ext}",
                creator=creator,
                description=description,
                keywords=keywords
            )
            if vec_data is not None:
                filename = f"{safe_name}_{i+1}.{ext}"
                data_bytes = vec_data if isinstance(vec_data, bytes) else vec_data.encode()
                return filename, data_bytes
            return None

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            items = list(enumerate(files_data))
            results_raw = executor.map(_proc_item, items)

        written_count = 0
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for res in results_raw:
                if res is not None:
                    filename, data_bytes = res
                    zip_file.writestr(filename, data_bytes)
                    written_count += 1

        return zip_buffer.getvalue() if written_count > 0 else None, True


@app.post("/api/adobe-stock-vectorize")
async def adobe_stock_vectorize_endpoint(
    files: List[UploadFile] = File(...),
    threshold: int = Form(127),
    invert: str = Form("false"),
    mode: str = Form("monochrome"),
    numColors: int = Form(4),
    fillHoles: str = Form("true"),
    format: str = Form("eps"),
    creator: str = Form("peripirdaus"),
    title: str = Form(""),
    description: str = Form(""),
    keywords: str = Form("")
):
    try:
        inv = str_to_bool(invert)
        fill_h = str_to_bool(fillHoles)
        ext = format.lower()
        files_data = [(f.filename, await f.read()) for f in files]
        
        result_data, is_zip = await asyncio.to_thread(_sync_adobe_batch, files_data, threshold, inv, mode, numColors, fill_h, ext, creator, title, description, keywords)
        if not result_data:
            raise HTTPException(status_code=400, detail="Tidak ada ikon yang terdeteksi untuk Adobe Stock.")
            
        if len(files) == 1:
            media_type = "application/postscript" if ext == "eps" else "image/svg+xml"
            safe_name = sanitize_filename(files[0].filename)
            return Response(
                content=result_data if isinstance(result_data, bytes) else result_data.encode(),
                media_type=media_type,
                headers={"Content-Disposition": f"attachment; filename={safe_name}.{ext}"}
            )
        else:
            return Response(
                content=result_data,
                media_type="application/zip",
                headers={"Content-Disposition": f"attachment; filename=adobe_stock_vectors_{ext}.zip"}
            )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def _sync_vecteezy_batch(files_data: list, threshold: int, inv: bool, mode: str, num_colors: int, format: str, alphamax: float, opttolerance: float, creator: str = "peripirdaus", split_grid: bool = False, split_layout: str = "3x3", title: str = "", description: str = "", keywords: str = ""):
    zip_buffer = io.BytesIO()
    ext = format.lower()
    is_bulk = len(files_data) > 1 or split_grid
    
    if not is_bulk:
        orig_filename, contents = files_data[0]
        safe_name = sanitize_filename(orig_filename)
        eps_data, jpg_data = vectorize_vecteezy(
            contents,
            threshold_val=threshold,
            invert=inv,
            mode=mode,
            num_colors=num_colors,
            fmt=ext,
            alphamax=alphamax,
            opttolerance=opttolerance,
            title=title or f"{safe_name}.{ext}",
            creator=creator,
            description=description,
            keywords=keywords
        )
        return (eps_data, jpg_data), False
    else:
        def _proc_item(args):
            i, (orig_filename, contents) = args
            safe_name = sanitize_filename(orig_filename)

            if split_grid:
                rows, cols = parse_grid_layout(split_layout)
                tiles = slice_grid_icons(contents, rows=rows, cols=cols)
                if len(tiles) > 1:
                    sub_res = []
                    for sub_idx, sub_tile in enumerate(tiles):
                        item_name = f"{safe_name}_icon_{sub_idx + 1}"
                        eps_data, jpg_data = vectorize_vecteezy(
                            sub_tile,
                            threshold_val=threshold,
                            invert=inv,
                            mode=mode,
                            num_colors=num_colors,
                            fmt=ext,
                            alphamax=alphamax,
                            opttolerance=opttolerance,
                            title=item_name,
                            creator=creator,
                            description=description,
                            keywords=keywords
                        )
                        if eps_data is not None:
                            eps_bytes = eps_data if isinstance(eps_data, bytes) else eps_data.encode()
                            sub_res.append((f"{item_name}.{ext}", eps_bytes, f"{item_name}.jpg", jpg_data))
                    if sub_res:
                        return sub_res

            item_name = f"{safe_name}_{i+1}" if len(files_data) > 1 else safe_name
            eps_data, jpg_data = vectorize_vecteezy(
                contents,
                threshold_val=threshold,
                invert=inv,
                mode=mode,
                num_colors=num_colors,
                fmt=ext,
                alphamax=alphamax,
                opttolerance=opttolerance,
                title=title or f"{item_name}.{ext}",
                creator=creator,
                description=description,
                keywords=keywords
            )
            if eps_data is not None:
                eps_bytes = eps_data if isinstance(eps_data, bytes) else eps_data.encode()
                return [(f"{item_name}.{ext}", eps_bytes, f"{item_name}.jpg", jpg_data)]
            return None

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            items = list(enumerate(files_data))
            results_raw = executor.map(_proc_item, items)

        written_count = 0
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for res_list in results_raw:
                if res_list:
                    for (eps_name, eps_bytes, jpg_name, jpg_bytes) in res_list:
                        zip_file.writestr(eps_name, eps_bytes)
                        if jpg_bytes is not None:
                            zip_file.writestr(jpg_name, jpg_bytes)
                        written_count += 1

        return zip_buffer.getvalue() if written_count > 0 else None, True


@app.post("/api/vecteezy-vectorize")
async def vecteezy_vectorize_endpoint(
    files: List[UploadFile] = File(...),
    threshold: int = Form(127),
    invert: str = Form("false"),
    mode: str = Form("monochrome"),
    numColors: int = Form(4),
    format: str = Form("eps"),
    alphamax: float = Form(0.75),
    opttolerance: float = Form(0.20),
    creator: str = Form("peripirdaus"),
    splitGrid: str = Form("false"),
    splitLayout: str = Form("3x3"),
    title: str = Form(""),
    description: str = Form(""),
    keywords: str = Form("")
):
    try:
        inv = str_to_bool(invert)
        split_g = str_to_bool(splitGrid)
        ext = format.lower()
        files_data = [(f.filename, await f.read()) for f in files]
        
        result_data, is_zip = await asyncio.to_thread(_sync_vecteezy_batch, files_data, threshold, inv, mode, numColors, ext, alphamax, opttolerance, creator, split_g, splitLayout, title, description, keywords)
        if not result_data:
            raise HTTPException(status_code=400, detail="Tidak ada ikon yang terdeteksi untuk Vecteezy.")
            
        if len(files) == 1 and not split_g:
            eps_data, _ = result_data
            if not eps_data:
                raise HTTPException(status_code=400, detail="Tidak ada ikon terdeteksi.")
            media_type = "application/postscript" if ext == "eps" else "image/svg+xml"
            safe_name = sanitize_filename(files[0].filename)
            return Response(
                content=eps_data if isinstance(eps_data, bytes) else eps_data.encode(),
                media_type=media_type,
                headers={"Content-Disposition": f"attachment; filename={safe_name}.{ext}"}
            )
        else:
            return Response(
                content=result_data,
                media_type="application/zip",
                headers={"Content-Disposition": f"attachment; filename=vecteezy_vectors_{ext}.zip"}
            )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/preflight")
async def preflight_audit_endpoint(
    file: UploadFile = File(...),
    threshold: int = Form(127),
    invert: str = Form("false"),
    mode: str = Form("monochrome"),
    numColors: int = Form(4)
):
    try:
        inv = str_to_bool(invert)
        contents = await file.read()
        audit = await asyncio.to_thread(preflight_check, contents, threshold_val=threshold, invert=inv, mode=mode, num_colors=numColors)
        return audit
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))



@app.post("/api/check-duplicates")
async def check_duplicates_endpoint(
    files: List[UploadFile] = File(...),
    threshold: float = Form(85.0)
):
    try:
        files_data = [(f.filename, await f.read()) for f in files]
        duplicates = await asyncio.to_thread(find_duplicates_in_batch, files_data, threshold)
        return {"duplicates": duplicates, "count": len(duplicates)}
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


from backend.vector_repair import repair_engine
from backend.vector_validator import validate_repaired_vector

@app.post("/api/repair-vector")
async def repair_vector_endpoint(
    file: UploadFile = File(...),
    filename: Optional[str] = Form(None),
    num_colors: Optional[int] = Form(32)
):
    try:
        content = await file.read()
        target_name = filename or file.filename or "artwork.svg"
        colors_val = num_colors if num_colors else 32
        res = await asyncio.to_thread(repair_engine.repair_svg_to_geometry, content, target_name, colors_val)
        if isinstance(res, dict):
            res = {k: v for k, v in res.items() if not isinstance(v, bytes)}
        return res
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/validate-vector")
async def validate_vector_endpoint(
    file: UploadFile = File(...)
):
    try:
        content = await file.read()
        res = await asyncio.to_thread(validate_repaired_vector, content, file.filename)
        return res
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ftp/test")
async def test_ftp_endpoint(
    host: str = Form(...),
    port: int = Form(21),
    username: str = Form(""),
    password: str = Form("")
):
    try:
        res = await asyncio.to_thread(test_ftp_connection, host, port, username, password)
        return res
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ftp/upload")
async def upload_ftp_endpoint(
    host: str = Form(...),
    port: int = Form(21),
    username: str = Form(""),
    password: str = Form(""),
    remoteDir: str = Form("/"),
    files: List[UploadFile] = File(...)
):
    try:
        files_data = [(f.filename, await f.read()) for f in files]
        res = await asyncio.to_thread(upload_files_to_ftp, host, port, username, password, remoteDir, files_data)
        return res
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/verify-metadata")
async def verify_metadata_endpoint(
    file: UploadFile = File(...)
):
    try:
        content = await file.read()
        res = await asyncio.to_thread(inspect_image_metadata, content, file.filename or "image.jpg")
        return res
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/clean-jpg")
async def clean_jpg_endpoint(
    file: UploadFile = File(...),
    title: str = Form(""),
    description: str = Form(""),
    keywords: str = Form(""),
    creator: str = Form("peripirdaus"),
    software: str = Form("Adobe Illustrator 2024 (Macintosh)"),
    quality: int = Form(98),
    dpi: int = Form(300),
    inject_c2pa: bool = Form(False)
):
    try:
        content = await file.read()
        cleaned_bytes = await asyncio.to_thread(
            clean_and_inject_jpg,
            content,
            title=title,
            description=description,
            keywords=keywords,
            creator=creator,
            software=software,
            quality=quality,
            dpi=dpi,
            inject_c2pa=inject_c2pa
        )
        safe_name = sanitize_filename(file.filename or "cleaned_image")
        filename = f"{safe_name}_clean.jpg"
        return Response(
            content=cleaned_bytes,
            media_type="image/jpeg",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/bulk-clean-jpg")
async def bulk_clean_jpg_endpoint(
    files: List[UploadFile] = File(...),
    title: str = Form(""),
    description: str = Form(""),
    keywords: str = Form(""),
    creator: str = Form("peripirdaus"),
    software: str = Form("Adobe Illustrator 2024 (Macintosh)"),
    quality: int = Form(98),
    dpi: int = Form(300),
    inject_c2pa: bool = Form(False)
):
    try:
        zip_buffer = io.BytesIO()
        files_data = [(f.filename, await f.read()) for f in files]

        def _proc_item(args):
            i, (orig_filename, content) = args
            safe_name = sanitize_filename(orig_filename or f"cleaned_{i+1}")
            clean_bytes = clean_and_inject_jpg(
                content,
                title=title or f"{safe_name.replace('_', ' ')}",
                description=description,
                keywords=keywords,
                creator=creator,
                software=software,
                quality=quality,
                dpi=dpi,
                inject_c2pa=inject_c2pa
            )
            return f"{safe_name}_clean.jpg", clean_bytes

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            results = list(executor.map(_proc_item, enumerate(files_data)))

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for fname, fbytes in results:
                zip_file.writestr(fname, fbytes)

        return Response(
            content=zip_buffer.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": "attachment; filename=cleaned_jpgs_sanitized.zip"}
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


class IconGenerateProxyReq(BaseModel):
    endpoint: str
    api_key: str
    payload: dict
    mode: str = "auto"   # "auto" | "images" | "chat"
    remove_background: bool = False
    anti_ai: bool = False
    fake_metadata: bool = False


def _post_process_image(img_data: bytes, remove_bg: bool, anti_ai: bool, fake_metadata: bool) -> bytes:
    """Apply optional post-processing to raw image bytes. Returns PNG bytes."""
    import io, base64, numpy as np
    from PIL import Image, ImageFilter, ImageEnhance
    from PIL.PngImagePlugin import PngInfo

    input_img = Image.open(io.BytesIO(img_data)).convert("RGBA")

    if remove_bg:
        import rembg
        input_img = rembg.remove(input_img)

    if anti_ai:
        bg = Image.new("RGBA", input_img.size, (255, 255, 255, 255))
        bg.paste(input_img, (0, 0), input_img)
        rgb_img = bg.convert("RGB")

        orig_size = rgb_img.size
        rgb_img = rgb_img.resize((int(orig_size[0]*1.02), int(orig_size[1]*0.98)), resample=Image.Resampling.LANCZOS)
        rgb_img = rgb_img.crop((4, 4, orig_size[0]-4, orig_size[1]-4))
        rgb_img = rgb_img.resize(orig_size, resample=Image.Resampling.BICUBIC)

        arr = np.array(rgb_img, dtype=np.float32)
        h, w = arr.shape[:2]
        xx, yy = np.meshgrid(np.arange(w), np.arange(h))
        adv_noise = np.sin(xx * 0.8) * np.cos(yy * 0.8) * 6.0
        rand_noise = np.random.randn(h, w, 3) * 5.0
        arr = np.clip(arr + adv_noise[:, :, np.newaxis] + rand_noise, 0, 255).astype(np.uint8)
        rgb_img = Image.fromarray(arr)

        r, g, b = rgb_img.split()
        from PIL import ImageChops
        r = ImageChops.offset(r, 1, 0)
        b = ImageChops.offset(b, -1, 0)
        rgb_img = Image.merge("RGB", (r, g, b))
        rgb_img = rgb_img.filter(ImageFilter.GaussianBlur(radius=0.4))
        rgb_img = rgb_img.filter(ImageFilter.UnsharpMask(radius=2.0, percent=120, threshold=3))
        enhancer = ImageEnhance.Color(rgb_img)
        rgb_img = enhancer.enhance(0.92)
        tmp_io = io.BytesIO()
        rgb_img.save(tmp_io, format="JPEG", quality=75)
        rgb_img = Image.open(tmp_io)

        if remove_bg:
            r, g, b = rgb_img.split()
            alpha = input_img.split()[3]
            input_img = Image.merge("RGBA", (r, g, b, alpha))
        else:
            input_img = rgb_img.convert("RGBA")

    buffered = io.BytesIO()
    if fake_metadata:
        metadata = PngInfo()
        metadata.add_text("Software", "Adobe Photoshop 25.0 (Windows)")
        metadata.add_text("Author", "Vecto Studio")
        metadata.add_text("Description", "Handcrafted Vector Asset")
        input_img.save(buffered, format="PNG", pnginfo=metadata)
    else:
        input_img.save(buffered, format="PNG")
    return buffered.getvalue()


@app.post("/api/generate-icon")
async def proxy_generate_icon(req: IconGenerateProxyReq):
    try:
        import urllib.request
        import json, base64, re

        auth_header = f"Bearer {req.api_key}" if not req.api_key.startswith("Bearer ") else req.api_key
        base_url = req.endpoint.strip().rstrip("/")
        model = req.payload.get("model", "")
        prompt = req.payload.get("prompt", "")

        # --- Determine mode ---
        # "auto": try chat completions for 9router ag/ models, otherwise images/generations
        mode = req.mode
        if mode == "auto":
            # ag/ models use chat completions with native image output on 9router
            if model.startswith("ag/") or model.startswith("gc/") or model.startswith("gemini/"):
                mode = "chat"
            else:
                mode = "images"

        resp_images_b64 = []  # list of raw b64 strings

        if mode == "chat":
            # Use /chat/completions with modalities: ["text", "image"] for native image generation
            chat_url = base_url + "/chat/completions"
            chat_payload = {
                "model": model,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
                "modalities": ["text", "image"]
            }
            data_bytes = json.dumps(chat_payload).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "Authorization": auth_header,
                "User-Agent": "VectoAI-Proxy/1.0"
            }
            http_req = urllib.request.Request(chat_url, data=data_bytes, headers=headers, method="POST")
            with urllib.request.urlopen(http_req, timeout=180) as resp:
                resp_body = resp.read().decode("utf-8", errors="ignore")
            resp_data = json.loads(resp_body)

            # Extract image(s) from chat completion response
            # Standard chat completion: choices[].message.content (list of parts)
            for choice in resp_data.get("choices", []):
                msg = choice.get("message", {})
                content = msg.get("content", "")
                # Content can be a list of parts (OpenAI multi-modal) or plain text
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict):
                            if part.get("type") == "image_url":
                                url_data = part.get("image_url", {}).get("url", "")
                                if url_data.startswith("data:image/"):
                                    # strip data url prefix
                                    b64 = url_data.split(",", 1)[1]
                                    resp_images_b64.append(b64)
                            elif part.get("type") == "image":
                                b64 = part.get("image_url", {}).get("url", "") or part.get("data", "")
                                if b64:
                                    resp_images_b64.append(b64.split(",", 1)[-1])
                elif isinstance(content, str):
                    # Gemini sometimes returns base64 inline in text - look for data URI
                    matches = re.findall(r'data:image/[^;]+;base64,([A-Za-z0-9+/=]+)', content)
                    resp_images_b64.extend(matches)
                    # Also check inline_data via Gemini raw
                    for part in msg.get("parts", []):
                        if isinstance(part, dict) and "inline_data" in part:
                            resp_images_b64.append(part["inline_data"].get("data", ""))

            # Also check top-level "data" array (some 9router versions wrap it)
            for item in resp_data.get("data", []):
                if "b64_json" in item:
                    resp_images_b64.append(item["b64_json"])
                elif "url" in item and item["url"].startswith("data:image/"):
                    resp_images_b64.append(item["url"].split(",", 1)[1])

            if not resp_images_b64:
                # No image found in response - surface the full response as error
                raise HTTPException(status_code=502, detail=f"Model tidak mengembalikan gambar. Pastikan model mendukung image output. Response: {resp_body[:500]}")

        else:
            # Standard OpenAI /images/generations
            img_url = base_url + "/images/generations"
            img_payload = {k: v for k, v in req.payload.items()}
            img_payload["response_format"] = "b64_json"
            data_bytes = json.dumps(img_payload).encode("utf-8")
            headers = {
                "Content-Type": "application/json",
                "Authorization": auth_header,
                "User-Agent": "VectoAI-Proxy/1.0"
            }
            http_req = urllib.request.Request(img_url, data=data_bytes, headers=headers, method="POST")
            with urllib.request.urlopen(http_req, timeout=180) as resp:
                resp_body = resp.read().decode("utf-8", errors="ignore")
            resp_data = json.loads(resp_body)

            for item in resp_data.get("data", []):
                if "b64_json" in item:
                    resp_images_b64.append(item["b64_json"])
                elif "url" in item:
                    # fetch url
                    img_req = urllib.request.Request(item["url"], headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(img_req, timeout=30) as img_resp:
                        raw = img_resp.read()
                    import base64 as _b64
                    resp_images_b64.append(_b64.b64encode(raw).decode())

        # Post-process and return in standard {data: [{b64_json: ...}]} format
        result_items = []
        for b64_str in resp_images_b64:
            try:
                raw_bytes = base64.b64decode(b64_str)
                if req.remove_background or req.anti_ai or req.fake_metadata:
                    processed = await asyncio.to_thread(
                        _post_process_image, raw_bytes,
                        req.remove_background, req.anti_ai, req.fake_metadata
                    )
                    result_items.append({"b64_json": base64.b64encode(processed).decode()})
                else:
                    result_items.append({"b64_json": b64_str})
            except Exception as ex:
                print(f"Post-processing error: {ex}")
                result_items.append({"b64_json": b64_str})

        return {"data": result_items}

    except HTTPException:
        raise
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        raise HTTPException(status_code=e.code, detail=err_body or str(e))
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)

