#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daily Aaj E-Paper Downloader (Peshawar + Abbotabad -> PDF)

https://epaper.dailyaaj.com.pk/

Malik Qasim Raza Chohan style - Sahafat script jaisa

Requirements (Termux mein ek dafa install karein):
    pip install requests pillow beautifulsoup4

Usage:
    python aaj.py
"""

import os
import time
import datetime
import re
import io
import gc

import requests
import img2pdf
from PIL import Image
from bs4 import BeautifulSoup

# ===================== CONFIG =====================

# Relative folder -- works for both manual Termux runs and the automated
# scheduler (which searches its own temp working dir recursively for
# *.pdf; an absolute Android-only path would never be found there).
OUTPUT_FOLDER = "Aaj_Epaper_PDFs"

# None = aaj ki date. Ya manually "DD-MM-YYYY" format mein dein, jaise "22-08-2026"
TARGET_DATE = None

REQUEST_TIMEOUT = 20
RETRY_PER_PAGE = 2

# Page IDs jo site use karti hai (Front, City, International, District, Column, Sport, Back)
PAGE_IDS = [1, 16, 17, 18, 20, 22, 26]

EDITIONS = {
    "Peshawar":   "peshawar",
    "Abbotabad":  "abbotabad",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://epaper.dailyaaj.com.pk/",
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


def download_image(url):
    """Image download karta hai. Success par bytes return karta hai, warna None."""
    for attempt in range(1, RETRY_PER_PAGE + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200 and resp.content and len(resp.content) > 5000:
                return resp.content
            if resp.status_code == 404:
                return None
        except requests.RequestException:
            pass
        if attempt < RETRY_PER_PAGE:
            time.sleep(1.2)
    return None


def get_page_image_url(edition_code, page_id, dt):
    """POST karke us page ka main image URL nikalta hai."""
    date_form = dt.strftime("%m-%d-%Y")      # 08-22-2026
    date_hidden = dt.strftime("%Y-%m-%d")    # 2026-08-22

    data = {
        "epapertype": edition_code,
        "date": date_form,
        "dated": date_hidden,
        "epaperpage": str(page_id),
    }

    try:
        resp = requests.post(
            "https://epaper.dailyaaj.com.pk/main/epaper",
            data=data,
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        if resp.status_code != 200:
            return None

        # Main image (epaper/HASH.jpg) - pages/ wala skip karo
        matches = re.findall(r'epaper/([a-f0-9]{32})\.jpg', resp.text)
        if matches:
            # pehla match usually main page image hota hai
            hash_name = matches[0]
            return f"https://epaper.dailyaaj.com.pk/epaper/{hash_name}.jpg"
    except Exception:
        pass
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


def download_edition(name, edition_code, dt):
    date_str = dt.strftime("%d-%m-%Y")
    log(f"==> {name} ({date_str}): pages dhoondi ja rahi hain...")

    images = []
    for page_id in PAGE_IDS:
        url = get_page_image_url(edition_code, page_id, dt)
        if not url:
            log(f"    [{name}] page_id {page_id}: URL nahi mila -- skip")
            continue

        content = download_image(url)
        if content is None:
            log(f"    [{name}] page_id {page_id}: download fail")
            continue

        images.append(content)
        log(f"    [{name}] page_id {page_id}: OK ({len(content)//1024} KB)")

    if not images:
        log(f"==> {name}: koi page nahi mila is date ({date_str}) ke liye.")
        return False

    # ---- Images ko ek PDF mein combine karo (memory-safe: JPEG bytes
    # seedha PDF mein wrap hote hain) ----
    jpeg_pages = [_page_to_jpeg_bytes(raw) for raw in images]

    day_no = str(int(dt.strftime("%d")))
    mon_title = dt.strftime("%b")
    out_name = f"Aaj {name} {day_no}{mon_title}.pdf"
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
        time.sleep(1)   # thoda gap

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
