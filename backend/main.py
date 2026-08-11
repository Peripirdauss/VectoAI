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
    vectorize_freepik, vectorize_adobe_stock, vectorize_vecteezy, vectorize_shutterstock, vectorize_shutterstock_pattern, preflight_check,
    analyze_seamless_continuity, generate_3x3_tile_preview, vectorize_seamless_pattern_tiled
)
from backend.duplicate_finder import find_duplicates_in_batch
from backend.ftp_uploader import test_ftp_connection, upload_files_to_ftp

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

def sanitize_filename(filename: str) -> str:
    base_name = filename.rsplit('.', 1)[0]
    safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', base_name)
    safe_name = re.sub(r'_+', '_', safe_name).strip('_')
    return safe_name or "vectorized"


def _sync_preview(contents: bytes, threshold: int, inv: bool, mode: str, num_colors: int):
    if mode == "color":
        preview_img, _, _ = process_color_image(contents, num_colors=num_colors)
    else:
        preview_img, _ = process_image(contents, threshold_val=threshold, invert=inv)
    
    if preview_img is None:
        return None
    
    _, encoded_img = cv2.imencode('.png', preview_img)
    return base64.b64encode(encoded_img).decode('utf-8')


@app.post("/api/preview")
async def preview_threshold(
    file: UploadFile = File(...),
    threshold: int = Form(127),
    invert: str = Form("false"),
    mode: str = Form("monochrome"),
    numColors: int = Form(4)
):
    try:
        inv = str_to_bool(invert)
        contents = await file.read()
        base64_img = await asyncio.to_thread(_sync_preview, contents, threshold, inv, mode, numColors)
        if base64_img is None:
            raise HTTPException(status_code=400, detail="Invalid image")
        return {"preview": f"data:image/png;base64,{base64_img}"}
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


def _sync_vectorize(contents: bytes, format: str, threshold: int, inv: bool, mode: str, num_colors: int, filename: str = "vectorized", title: str = None, creator: str = "peripirdaus", opttolerance: float = 0.1, alphamax: float = 1.0, description: str = "", keywords: str = ""):
    eps_title = title or f"{sanitize_filename(filename)}.{format.lower()}"
    if mode == "color":
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
    mode: str = Form("monochrome"),
    numColors: int = Form(4),
    creator: str = Form("peripirdaus"),
    opttolerance: float = Form(0.1),
    alphamax: float = Form(1.0),
    title: str = Form(""),
    description: str = Form(""),
    keywords: str = Form("")
):
    try:
        inv = str_to_bool(invert)
        contents = await file.read()
        vec_data = await asyncio.to_thread(
            _sync_vectorize, contents, format, threshold, inv, mode, numColors, file.filename, title or None, creator, opttolerance, alphamax, description, keywords
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


def _sync_bulk_vectorize(files_data: list, format: str, threshold: int, inv: bool, mode: str, num_colors: int, title: str = "", description: str = "", keywords: str = ""):
    zip_buffer = io.BytesIO()
    ext = format.lower()
    
    def _proc_item(args):
        i, (orig_filename, contents) = args
        eps_title = title or f"{sanitize_filename(orig_filename)}_{i+1}.{ext}"
        if mode == "color":
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
    mode: str = Form("monochrome"),
    numColors: int = Form(4),
    title: str = Form(""),
    description: str = Form(""),
    keywords: str = Form("")
):
    try:
        inv = str_to_bool(invert)
        files_data = [(f.filename, await f.read()) for f in files]
        
        zip_bytes = await asyncio.to_thread(_sync_bulk_vectorize, files_data, format, threshold, inv, mode, numColors, title, description, keywords)
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


def _sync_freepik_batch(files_data: list, threshold: int, inv: bool, mode: str, num_colors: int, creator: str = "peripirdaus", split_grid: bool = False, title: str = "", description: str = "", keywords: str = ""):
    def _proc_item(args):
        i, (orig_filename, contents) = args
        safe_name = sanitize_filename(orig_filename)
        eps_title = title or f"{safe_name}.eps"
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

        # Check if grid auto-splitter produced sub-items
        if res2 is True and isinstance(res1, list):
            sub_entries = []
            for sub in res1:
                idx_str = f"sub_{sub['sub_index']}"
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
    title: str = Form(""),
    description: str = Form(""),
    keywords: str = Form("")
):
    try:
        inv = str_to_bool(invert)
        split_g = str_to_bool(splitGrid)
        files_data = [(f.filename, await f.read()) for f in files]
        
        results = await asyncio.to_thread(_sync_freepik_batch, files_data, threshold, inv, mode, numColors, creator, split_g, title, description, keywords)
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


def _sync_shutterstock_standard_batch(files_data: list, threshold: int, inv: bool, mode: str, num_colors: int, creator: str = "peripirdaus", title: str = "", description: str = "", keywords: str = ""):
    def _proc_item(args):
        i, (orig_filename, contents) = args
        safe_name = sanitize_filename(orig_filename)
        eps_title = title or f"{safe_name}.eps"
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
            return item
        return None

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        items = list(enumerate(files_data))
        results_raw = executor.map(_proc_item, items)

    results = [r for r in results_raw if r is not None]
    return results


@app.post("/api/shutterstock-vectorize-standard")
async def shutterstock_vectorize_standard_endpoint(
    files: List[UploadFile] = File(...),
    threshold: int = Form(127),
    invert: str = Form("false"),
    mode: str = Form("monochrome"),
    numColors: int = Form(4),
    creator: str = Form("peripirdaus"),
    title: str = Form(""),
    description: str = Form(""),
    keywords: str = Form("")
):
    try:
        inv = str_to_bool(invert)
        files_data = [(f.filename, await f.read()) for f in files]
        results = await asyncio.to_thread(_sync_shutterstock_standard_batch, files_data, threshold, inv, mode, numColors, creator, title, description, keywords)
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


def _sync_vecteezy_batch(files_data: list, threshold: int, inv: bool, mode: str, num_colors: int, format: str, alphamax: float, opttolerance: float, creator: str = "peripirdaus", title: str = "", description: str = "", keywords: str = ""):
    zip_buffer = io.BytesIO()
    ext = format.lower()
    is_bulk = len(files_data) > 1
    
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
                return f"{item_name}.{ext}", eps_bytes, f"{item_name}.jpg", jpg_data
            return None

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            items = list(enumerate(files_data))
            results_raw = executor.map(_proc_item, items)

        written_count = 0
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for res in results_raw:
                if res is not None:
                    eps_name, eps_bytes, jpg_name, jpg_bytes = res
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
    title: str = Form(""),
    description: str = Form(""),
    keywords: str = Form("")
):
    try:
        inv = str_to_bool(invert)
        ext = format.lower()
        files_data = [(f.filename, await f.read()) for f in files]
        
        result_data, is_zip = await asyncio.to_thread(_sync_vecteezy_batch, files_data, threshold, inv, mode, numColors, ext, alphamax, opttolerance, creator, title, description, keywords)
        if not result_data:
            raise HTTPException(status_code=400, detail="Tidak ada ikon yang terdeteksi untuk Vecteezy.")
            
        if len(files) == 1:
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
