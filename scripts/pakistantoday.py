#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pakistan Today E-Paper Downloader (3 Editions -> PDF)

Lahore / Karachi / Islamabad
==========================================================================
Style: Sahafat script jaisa (Malik Qasim Raza Chohan style)

Issuu pe host hota hai:
    https://issuu.com/pakistantoday-paperazzi/docs/epaper_YY-MM-DD_xxx

Image pattern (oembed se ID nikalta hai):
    https://image.isu.pub/{document_id}/jpg/page_{n}.jpg

Requirements (Termux mein ek dafa):
    pip install requests pillow

Usage:
    python pakistan_today.py
"""

import os
import io
import time
import datetime
import re
import requests
from PIL import Image

# ===================== CONFIG =====================

OUTPUT_FOLDER = "PakistanToday_Epaper_PDFs"

# None = aaj ki date. Ya manually "DD-MM-YYYY" format, jaise "20-08-2026"
TARGET_DATE = None

MAX_PAGES = 20
REQUEST_TIMEOUT = 20
RETRY_PER_PAGE = 2

# Edition short codes jo Issuu document name mein use hote hain
EDITIONS = {
    "Lahore":     "lhr",
    "Karachi":    "khi",
    "Islamabad":  "isb",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36"
    )
}

# ===================================================

os.makedirs(OUTPUT_FOLDER, exist_ok=True)


def log(msg):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def get_target_date():
    if TARGET_DATE:
        return datetime.datetime.strptime(TARGET_DATE, "%d-%m-%Y")
    return datetime.datetime.now()


def build_doc_slug(code, dt):
    """
    Issuu document name banata hai.
    Example: epaper_26-08-20_lhr
    Note: kabhi-kabhi format thoda change hota hai (26-8-20 vs 26-08-20)
    """
    yy = dt.strftime("%y")
    mm = dt.strftime("%m")
    dd = dt.strftime("%d")
    return f"epaper_{yy}-{mm}-{dd}_{code}"


def get_document_id(slug):
    """
    Issuu oembed se document ID nikaalta hai.
    Thumbnail URL se ID extract hota hai.
    """
    issuu_url = f"https://issuu.com/pakistantoday-paperazzi/docs/{slug}"
    oembed = f"https://issuu.com/oembed?url={issuu_url}&format=json"

    try:
        r = requests.get(oembed, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json()
        thumb = data.get("thumbnail_url", "")
        # Example: https://image.isu.pub/260819210140-182d8361856dce782526461a4e1e7a9b/jpg/page_1_thumb_medium.jpg
        m = re.search(r"image\.isu\.pub/([a-f0-9\-]+)/", thumb)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def download_image(url):
    for attempt in range(1, RETRY_PER_PAGE + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200 and len(resp.content) > 5000:
                return resp.content
            if resp.status_code == 404:
                return None
        except requests.RequestException:
            pass
        if attempt < RETRY_PER_PAGE:
            time.sleep(1)
    return None


def download_edition(name, code, dt):
    date_str = dt.strftime("%d-%m-%Y")
    slug = build_doc_slug(code, dt)

    log(f"==> {name} ({date_str}): document ID dhoondh raha hoon...")
    log(f"    slug: {slug}")

    doc_id = get_document_id(slug)
    if not doc_id:
        # fallback: kabhi kabhi leading zero missing hota hai
        yy = dt.strftime("%y")
        mm = str(int(dt.strftime("%m")))   # 08 -> 8
        dd = str(int(dt.strftime("%d")))   # 05 -> 5
        alt_slug = f"epaper_{yy}-{mm}-{dd}_{code}"
        log(f"    trying alternate slug: {alt_slug}")
        doc_id = get_document_id(alt_slug)
        if doc_id:
            slug = alt_slug

    if not doc_id:
        log(f"==> {name}: document nahi mila is date ke liye.")
        return False

    log(f"    document ID: {doc_id}")

    images = []
    for page in range(1, MAX_PAGES + 1):
        url = f"https://image.isu.pub/{doc_id}/jpg/page_{page}.jpg"
        content = download_image(url)
        if content is None:
            log(f"    [{name}] page {page}: nahi mila -- stop")
            break
        images.append(content)
        log(f"    [{name}] page {page}: OK ({len(content)//1024} KB)")

    if not images:
        log(f"==> {name}: koi page download nahi hua.")
        return False

    # ---- PDF banao ----
    pil_images = []
    for raw in images:
        img = Image.open(io.BytesIO(raw)).convert("RGB")
        pil_images.append(img)

    day_no = str(int(dt.strftime("%d")))
    mon_title = dt.strftime("%b")
    out_name = f"PakistanToday {name} {day_no}{mon_title}.pdf"
    out_path = os.path.join(OUTPUT_FOLDER, out_name)

    pil_images[0].save(out_path, save_all=True, append_images=pil_images[1:])
    log(f"==> {name}: ✅ PDF ban gaya -- {out_name} ({len(pil_images)} pages)")
    return True


if __name__ == "__main__":
    start = time.time()
    dt = get_target_date()
    date_str = dt.strftime("%d-%m-%Y")

    log(f"Output folder: {OUTPUT_FOLDER}")
    log(f"Target date: {date_str}")
    log(f"Editions ({len(EDITIONS)}): {', '.join(EDITIONS.keys())}")

    results = {}
    for name, code in EDITIONS.items():
        ok = download_edition(name, code, dt)
        results[name] = ok
        time.sleep(1)   # thoda gap editions ke beech

    log("")
    log("===================== SUMMARY =====================")
    success = 0
    for name, ok in results.items():
        status = "OK" if ok else "FAILED"
        if ok:
            success += 1
        log(f"{name:<12} -> {status}")
    log(f"Total: {success}/{len(EDITIONS)} editions successful.")
    log("=====================================================")
    log(f"Time taken: {time.time() - start:.2f} seconds")
