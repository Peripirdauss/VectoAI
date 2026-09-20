import io
import re
import time
import os
import json
import tempfile
import subprocess
import logging
from datetime import datetime
from PIL import Image, ExifTags

logger = logging.getLogger(__name__)

def inspect_image_metadata(file_bytes: bytes, filename: str = "") -> dict:
    """
    Inspects image file for C2PA (Content Credentials), Google Media Processing Services,
    Stable Diffusion/Midjourney prompts, and authentic software EXIF.
    """
    findings = []
    c2pa_detected = False
    c2pa_issuer = None
    ai_prompts = []

    # 1. Byte-level forensic scan for C2PA and JUMBF manifests
    raw_lower = file_bytes.lower()

    if b"google media processing services" in raw_lower:
        c2pa_detected = True
        c2pa_issuer = "Google Media Processing Services (Google Imagen / Gemini)"
        findings.append("C2PA Manifest: Ditandatangani oleh Google Media Processing Services (Google Imagen/Gemini)")
    elif b"openai" in raw_lower and (b"c2pa" in raw_lower or b"dall-e" in raw_lower):
        c2pa_detected = True
        c2pa_issuer = "OpenAI (DALL-E 3 / ChatGPT)"
        findings.append("C2PA Manifest: Terdaftar atas nama OpenAI (DALL-E 3 / ChatGPT)")
    elif b"adobe firefly" in raw_lower or (b"firefly" in raw_lower and b"c2pa" in raw_lower):
        c2pa_detected = True
        c2pa_issuer = "Adobe Firefly"
        findings.append("C2PA Manifest: Terdaftar atas nama Adobe Firefly")
    elif b"c2pa test signing cert" in raw_lower or b"c2patool" in raw_lower:
        c2pa_detected = True
        c2pa_issuer = "Local Designer C2PA (Adobe Photoshop / Local Certificate)"
        findings.append("C2PA Manifest: Ditandatangani Sertifikat Lokal Desainer (Valid & Terbuka di verify.contentauthenticity.org)")
    elif b"c2pa" in raw_lower and (b"jumb" in raw_lower or b"spec.c2pa.org" in raw_lower):
        c2pa_detected = True
        c2pa_issuer = "Standard C2PA Synthetic Media Manifest"
        findings.append("C2PA Manifest: Format C2PA / Content Credentials terdeteksi di dalam container file")

    # Check JPEG APP11 marker (0xFF, 0xEB)
    if file_bytes[:2] == b"\xff\xd8":
        idx = 2
        flen = len(file_bytes)
        while idx < flen - 4:
            if file_bytes[idx] == 0xFF:
                marker = file_bytes[idx + 1]
                if marker == 0xEB: # APP11 (JUMBF / C2PA)
                    c2pa_detected = True
                    if not c2pa_issuer:
                        c2pa_issuer = "JPEG APP11 (JUMBF/C2PA Container)"
                    findings.append("JPEG Marker: Ditemukan blok APP11 (JUMBF/C2PA Box)")
                    break
                elif marker in (0xDA, 0xD9): # SOS or EOI
                    break
                # Jump marker length
                if idx + 4 <= flen:
                    seg_len = (file_bytes[idx + 2] << 8) | file_bytes[idx + 3]
                    idx += 2 + seg_len
                else:
                    break
            else:
                idx += 1

    # Check PNG caXp chunk (C2PA in PNG)
    if b"caXp" in file_bytes:
        c2pa_detected = True
        if not c2pa_issuer:
            c2pa_issuer = "PNG caXp (C2PA Chunk)"
        findings.append("PNG Chunk: Ditemukan chunk caXp (C2PA Container)")

    # 2. Extract image metadata and dimensions with PIL
    dimensions = [0, 0]
    img_format = "UNKNOWN"
    dpi = [72, 72]
    software = None
    artist = None
    copyright_info = None
    description_info = None
    create_date = None

    try:
        with Image.open(io.BytesIO(file_bytes)) as img:
            dimensions = list(img.size)
            img_format = img.format or "UNKNOWN"
            dpi_info = img.info.get("dpi")
            if dpi_info and isinstance(dpi_info, (tuple, list)):
                dpi = [int(dpi_info[0]), int(dpi_info[1])]

            # Check PNG info chunks (parameters, prompt, workflow)
            for k, v in img.info.items():
                k_str = str(k).lower()
                v_str = str(v)
                if k_str in ("parameters", "prompt", "workflow", "comment", "description"):
                    if any(kw in v_str.lower() for kw in ["steps:", "sampler:", "cfg scale:", "seed:", "model:", "negative prompt:", "lora:"]):
                        ai_prompts.append(f"[{k}] {v_str[:300]}...")
                        findings.append(f"AI Generation Metadata ditemukan di chunk PNG [{k}]")

            # Check EXIF
            exif = img.getexif()
            if exif:
                for tag_id, val in exif.items():
                    tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                    val_str = str(val).strip()
                    if tag_name == "Software":
                        software = val_str
                    elif tag_name == "Artist":
                        artist = val_str
                    elif tag_name == "Copyright":
                        copyright_info = val_str
                    elif tag_name == "ImageDescription":
                        description_info = val_str
                    elif tag_name in ("DateTime", "DateTimeOriginal"):
                        create_date = val_str

                    # Check for AI prompts in UserComment / ImageDescription
                    if tag_name in ("UserComment", "ImageDescription", "XPComment"):
                        if any(kw in val_str.lower() for kw in ["steps:", "sampler:", "seed:", "cfg:", "prompt"]):
                            ai_prompts.append(f"[{tag_name}] {val_str[:300]}...")
                            findings.append(f"AI Generation Parameters ditemukan di EXIF {tag_name}")
    except Exception as e:
        findings.append(f"Header Parse Warning: {e}")

    # Determine compliance status
    is_local_c2pa = c2pa_detected and "local" in (c2pa_issuer or "").lower()
    is_clean = (not c2pa_detected or is_local_c2pa) and len(ai_prompts) == 0
    if not c2pa_detected and len(ai_prompts) == 0:
        status = "CLEAN"
        recommendation = "File bersih dari jejak C2PA AI. Sangat aman diunggah ke Shutterstock & Adobe Stock."
    elif is_local_c2pa and len(ai_prompts) == 0:
        status = "LOCAL_C2PA"
        recommendation = "File memiliki Sertifikat C2PA Desainer Lokal (Bisa dibuka & diverifikasi di verify.contentauthenticity.org tanpa jejak Google/AI)."
    else:
        status = "AI_DETECTED"
        recommendation = "Ditemukan jejak AI (C2PA / Prompt). Sangat disarankan membersihkan file dengan fitur 'Clean & Sanitize JPG' agar tidak terkena penolakan microstock."

    return {
        "filename": filename,
        "status": status,
        "is_clean": is_clean,
        "c2pa": {
            "detected": c2pa_detected,
            "issuer": c2pa_issuer or "None",
        },
        "ai_prompts_detected": len(ai_prompts) > 0,
        "ai_prompts": ai_prompts,
        "findings": findings,
        "exif": {
            "software": software or "Tidak terdeteksi",
            "artist": artist or "Tidak terdata",
            "copyright": copyright_info or "None",
            "description": description_info or "None",
            "created": create_date or "None",
            "dpi": f"{dpi[0]} x {dpi[1]} DPI",
        },
        "dimensions": f"{dimensions[0]} x {dimensions[1]} px",
        "format": img_format,
        "size_kb": round(len(file_bytes) / 1024, 1),
        "recommendation": recommendation
    }


def clean_and_inject_jpg(
    file_bytes: bytes,
    title: str = "",
    description: str = "",
    keywords=None,
    creator: str = "peripirdaus",
    software: str = "Adobe Illustrator 2024 (Macintosh)",
    quality: int = 98,
    dpi: int = 300,
    inject_c2pa: bool = False
) -> bytes:
    """
    100% Strips all C2PA, JUMBF, APP11, and AI chunks, reconstructing pure RGB pixels
    and injecting authentic Adobe Photoshop/Illustrator EXIF & XMP metadata.
    If inject_c2pa is True, additionally signs with local c2patool so it can be verified on verify.contentauthenticity.org.
    """
    # 1. Load image into memory (raw pixel decode - strips all metadata containers)
    with Image.open(io.BytesIO(file_bytes)) as raw_img:
        # Convert to RGB (dropping alpha or palette if present for clean JPEG)
        if raw_img.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", raw_img.size, (255, 255, 255))
            if raw_img.mode == "P":
                raw_img = raw_img.convert("RGBA")
            bg.paste(raw_img, mask=raw_img.split()[-1] if "A" in raw_img.mode else None)
            clean_img = bg
        else:
            clean_img = raw_img.convert("RGB")

        # 2. Build Fresh Designer EXIF
        exif = clean_img.getexif()
        now_str = datetime.now().strftime("%Y:%m:%d %H:%M:%S")
        year = time.localtime().tm_year

        # Standard EXIF tags
        exif[0x0131] = software  # Software
        exif[0x013B] = creator   # Artist
        exif[0x8298] = f"Copyright (c) {year} {creator}. All rights reserved." # Copyright
        exif[0x010E] = description or title or "High quality digital illustration" # ImageDescription
        exif[0x0132] = now_str   # DateTime
        exif[0x9003] = now_str   # DateTimeOriginal
        exif[0x9004] = now_str   # DateTimeDigitized

        # 3. Build Adobe XMP packet
        xmp_packet = _build_jpeg_xmp(title=title, description=description, keywords=keywords, creator=creator, software=software)

        # Save to buffer as fresh clean JPEG (completely without C2PA or old chunks)
        # Using Pillow native xmp parameter ensures perfect standard marker ordering (JFIF -> Exif -> XMP)
        out_buf = io.BytesIO()
        clean_img.save(
            out_buf,
            format="JPEG",
            quality=int(quality),
            dpi=(int(dpi), int(dpi)),
            exif=exif,
            xmp=xmp_packet.encode("utf-8"),
            subsampling=0 # 4:4:4 Chroma Subsampling for crispest vector rasterization
        )
        cleaned_bytes = out_buf.getvalue()

    if inject_c2pa:
        return inject_c2pa_manifest(
            cleaned_bytes,
            title=title or "Digital Illustration",
            creator=creator or "peripirdaus",
            software="Adobe Photoshop 2024"
        )

    return cleaned_bytes


def inject_c2pa_manifest(
    jpeg_bytes: bytes,
    title: str = "Digital Illustration",
    creator: str = "peripirdaus",
    software: str = "Adobe Photoshop 2024"
) -> bytes:
    """
    Signs the image using c2patool with local creator credentials and Adobe Photoshop action,
    making it valid and inspectable on verify.contentauthenticity.org without Google AI traces.
    """
    c2patool_bin = "/opt/homebrew/bin/c2patool"
    if not os.path.exists(c2patool_bin):
        logger.warning("c2patool binary not found at %s", c2patool_bin)
        return jpeg_bytes

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = os.path.join(tmpdir, "input.jpg")
            out_path = os.path.join(tmpdir, "signed.jpg")
            manifest_path = os.path.join(tmpdir, "manifest.json")

            with open(in_path, "wb") as f:
                f.write(jpeg_bytes)

            manifest = {
                "claim_generator": f"{software} (Macintosh)",
                "title": title or "Digital Artwork",
                "assertions": [
                    {
                        "label": "c2pa.actions",
                        "data": {
                            "actions": [
                                {
                                    "action": "c2pa.created",
                                    "softwareAgent": software,
                                    "digitalSourceType": "http://cv.iptc.org/newscodes/digitalsourcetype/graphicArt"
                                }
                            ]
                        }
                    },
                    {
                        "label": "stds.schema-org.CreativeWork",
                        "data": {
                            "@context": "http://schema.org/",
                            "@type": "CreativeWork",
                            "author": [
                                {
                                    "@type": "Person",
                                    "name": creator or "peripirdaus"
                                }
                            ]
                        }
                    }
                ]
            }

            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f)

            env = os.environ.copy()
            env["PATH"] = f"/opt/homebrew/bin:{env.get('PATH', '')}"
            res = subprocess.run(
                [c2patool_bin, in_path, "-m", manifest_path, "-o", out_path, "--force"],
                capture_output=True,
                text=True,
                env=env
            )

            if res.returncode == 0 and os.path.exists(out_path):
                with open(out_path, "rb") as f:
                    return f.read()
            else:
                logger.warning("c2patool failed: %s", res.stderr)
    except Exception as e:
        logger.warning("C2PA signing exception: %s", e)

    return jpeg_bytes


def _build_jpeg_xmp(title: str = "", description: str = "", keywords=None, creator: str = "peripirdaus", software: str = "Adobe Illustrator 2024 (Macintosh)") -> str:
    """Builds standard Adobe XMP metadata block for JPEG files."""
    if isinstance(keywords, str):
        kw_list = [k.strip() for k in keywords.replace("\n", ",").split(",") if k.strip()]
    elif isinstance(keywords, (list, tuple, set)):
        kw_list = [str(k).strip() for k in keywords if str(k).strip()]
    else:
        kw_list = []

    clean_title = (title or "").strip()
    clean_desc = (description or "").strip()
    keywords_rdf = "\n".join([f"     <rdf:li>{kw}</rdf:li>" for kw in kw_list])
    kw_comma_str = ", ".join(kw_list)

    return f"""<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"
    xmlns:xmp="http://ns.adobe.com/xap/1.0/">
   <dc:title>
    <rdf:Alt>
     <rdf:li xml:lang="x-default">{clean_title}</rdf:li>
    </rdf:Alt>
   </dc:title>
   <dc:description>
    <rdf:Alt>
     <rdf:li xml:lang="x-default">{clean_desc}</rdf:li>
    </rdf:Alt>
   </dc:description>
   <dc:creator>
    <rdf:Seq>
     <rdf:li>{creator}</rdf:li>
    </rdf:Seq>
   </dc:creator>
   <dc:subject>
    <rdf:Bag>
{keywords_rdf}
    </rdf:Bag>
   </dc:subject>
   <photoshop:CaptionWriter>{creator}</photoshop:CaptionWriter>
   <photoshop:Credit>{creator}</photoshop:Credit>
   <xmp:CreatorTool>{software}</xmp:CreatorTool>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>"""


def _inject_xmp_into_jpeg(jpg_bytes: bytes, xmp_str: str) -> bytes:
    """Injects XMP into JPEG as APP1 marker (http://ns.adobe.com/xap/1.0/)."""
    if not xmp_str or jpg_bytes[:2] != b"\xff\xd8":
        return jpg_bytes

    xmp_header = b"http://ns.adobe.com/xap/1.0/\x00"
    payload = xmp_header + xmp_str.encode("utf-8")
    length = len(payload) + 2
    app1_marker = b"\xff\xe1" + length.to_bytes(2, "big") + payload

    # Insert right after SOI (FF D8)
    return jpg_bytes[:2] + app1_marker + jpg_bytes[2:]
