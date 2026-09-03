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
import gc
import time
import datetime
import re
import requests
import img2pdf
from PIL import Image

# ===================== CONFIG =====================

# Relative folder (creates inside wherever the script is run from). This
# works both for manual Termux runs AND for the automated scheduler, which
# runs each "cwd" script inside its own dedicated temp working directory
# and recursively searches that directory for the resulting *.pdf files --
# an absolute Android-only path (e.g. /storage/emulated/0/DCIM/...) would
# be invisible to that search and the script's PDFs would never get
# picked up by the auto-forward system.
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


def build_article_url(code, dt):
    """New Pakistan Today e-paper article URLs: /YYYY/MM/DD/epaperYY-MM-D-code"""
    yyyy = dt.strftime("%Y")
    mm = dt.strftime("%m")
    dd = dt.strftime("%d")
    yy = dt.strftime("%y")
    candidates = [
        f"https://www.pakistantoday.com.pk/{yyyy}/{mm}/{dd}/epaper{yy}-{mm}-{dd}-{code}",
        f"https://www.pakistantoday.com.pk/{yyyy}/{mm}/{dd}/epaper{yy}-{int(mm)}-{int(dd)}-{code}",
        f"https://www.pakistantoday.com.pk/{yyyy}/{int(mm)}/{int(dd)}/epaper{yy}-{mm}-{dd}-{code}",
        f"https://www.pakistantoday.com.pk/{yyyy}/{mm}/{dd}/epaper{yy}-{mm}-{int(dd)}-{code}",
    ]
    return candidates


def find_article_images(html):
    """Pakistan Today's newer article pages expose a direct preview image instead of Issuu pages."""
    found = []
    for attr in ["src", "data-src", "data-lazy-src"]:
        for match in re.findall(rf"{attr}=['\"]([^'\"\s>]+)['\"]", html, re.I):
            if "/uploads/" in match.lower() or "thumbs" in match.lower():
                found.append(match)
    for match in re.findall(r'https?://[^\"\'\s>]+(?:uploads|thumbs)[^\"\'\s>]+\.(?:jpg|jpeg|png|webp)', html, re.I):
        found.append(match)
    unique = []
    for item in found:
        cleaned = item.replace('\\/', '/').replace(' ', '%20')
        if cleaned.startswith('//'):
            cleaned = 'https:' + cleaned
        if cleaned not in unique:
            unique.append(cleaned)
    return unique


def download_article_fallback(name, code, dt):
    """Fallback: Pakistan Today has moved from Issuu to article-based e-paper pages."""
    candidate_urls = build_article_url(code, dt)
    log(f"    [{name}] article fallback check: {candidate_urls[0]}")

    for page_url in candidate_urls:
        try:
            resp = requests.get(page_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                continue
            html = resp.text
            images = find_article_images(html)
            if not images:
                continue
            for image_url in images[:10]:
                content = download_image(image_url)
                if content is None:
                    continue
                log(f"    [{name}] fallback image URL found: {image_url}")
                return [content]
        except Exception as e:
            log(f"    [{name}] fallback fetch error: {e}")
            continue
    return []


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


def _page_to_jpeg_bytes(raw_bytes):
    """Ek dafa mein sirf EK page RAM mein decode hota hai (memory-safe)."""
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        if img.format == "JPEG" and img.mode == "RGB":
            img.close()
            return raw_bytes
        img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=92)
        img.close()
        return buf.getvalue()
    except Exception:
        return raw_bytes


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
        log(f"==> {name}: Issuu document nahi mila, article fallback try kar rahe hain...")
        images = download_article_fallback(name, code, dt)
        if not images:
            log(f"==> {name}: koi page download nahi hua.")
            return False
    else:
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

    # ---- PDF banao (memory-safe: JPEG bytes seedha PDF mein wrap hote
    # hain, poori list decode karke RAM mein nahi rakhi jaati) ----
    jpeg_pages = [_page_to_jpeg_bytes(raw) for raw in images]

    day_no = str(int(dt.strftime("%d")))
    mon_title = dt.strftime("%b")
    out_name = f"PakistanToday {name} {day_no}{mon_title}.pdf"
    out_path = os.path.join(OUTPUT_FOLDER, out_name)

    with open(out_path, "wb") as f:
        f.write(img2pdf.convert(jpeg_pages))
    log(f"==> {name}: ✅ PDF ban gaya -- {out_name} ({len(jpeg_pages)} pages)")
    jpeg_pages = None
    gc.collect()
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
