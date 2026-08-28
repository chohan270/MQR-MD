#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Daily K2 E-Paper Downloader
============================

PDFs save ہوں گی:

    /sdcard/Documents

Website:

    https://epaper.dailyk2.com/

Editions:

    Gilgit Baltistan -> gb
    Islamabad        -> isl
    Karachi           -> khi
    Lahore            -> lhr

Usage:

    python DailyK2.py
"""

import os
import time
import io
import gc
import datetime

import requests
import img2pdf
from bs4 import BeautifulSoup
from PIL import Image


# ===================== CONFIG =====================

BASE_URL = "https://epaper.dailyk2.com"

# Relative folder -- works for both manual Termux runs and the automated
# scheduler (which searches its own temp working dir recursively for
# *.pdf; an absolute Android-only path like /sdcard/... would never be
# found there, so those PDFs would silently never get auto-forwarded).
OUTPUT_FOLDER = "DailyK2_Epaper_PDFs"

# None = aaj ki date
#
# Agar kisi purani date ka paper chahiye ho:
#
# TARGET_DATE = "16-08-2026"
#
TARGET_DATE = None

MAX_PAGES = 20

REQUEST_TIMEOUT = 20

RETRY_PER_PAGE = 2


# ===================== EDITIONS ====================

EDITIONS = {
    "Gilgit Baltistan": "gb",
    "Islamabad":        "isl",
    "Karachi":          "khi",
    "Lahore":           "lhr",
}


# ===================== HEADERS =====================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/124.0.0.0 "
        "Mobile Safari/537.36"
    )
}


# ===================================================

os.makedirs(
    OUTPUT_FOLDER,
    exist_ok=True
)


def log(msg):

    ts = datetime.datetime.now().strftime(
        "%H:%M:%S"
    )

    print(
        f"[{ts}] {msg}"
    )


def get_target_date():

    if TARGET_DATE:

        return datetime.datetime.strptime(
            TARGET_DATE,
            "%d-%m-%Y"
        )

    return datetime.datetime.now()


def build_page_url(
    edition_code,
    page,
    dt
):

    date = dt.strftime(
        "%Y-%m-%d"
    )

    return (
        f"{BASE_URL}/"
        f"{edition_code}/"
        f"{date}/"
        f"page{page}"
    )


def download_page(url):

    for attempt in range(
        1,
        RETRY_PER_PAGE + 1
    ):

        try:

            response = requests.get(
                url,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT
            )

            if (
                response.status_code == 200
                and response.content
            ):
                return response

            if response.status_code == 404:

                return None

        except requests.RequestException:

            pass

        if attempt < RETRY_PER_PAGE:

            time.sleep(1)

    return None


def find_image_url(html):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    for img in soup.find_all("img"):

        for attribute in (
            "src",
            "data-src",
            "data-lazy-src",
            "data-original"
        ):

            value = img.get(
                attribute
            )

            if not value:
                continue

            lower = value.lower()

            if (
                ".jpg" in lower
                or ".jpeg" in lower
                or ".png" in lower
                or ".webp" in lower
            ):

                if not any(
                    word in lower
                    for word in (
                        "logo",
                        "icon",
                        "avatar"
                    )
                ):

                    return value

    return None


def make_full_url(url):

    if url.startswith("//"):

        return "https:" + url

    if url.startswith("/"):

        return BASE_URL + url

    if url.startswith("http"):

        return url

    return BASE_URL + "/" + url


def download_image(url):

    for attempt in range(
        1,
        RETRY_PER_PAGE + 1
    ):

        try:

            response = requests.get(
                url,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT
            )

            if (
                response.status_code == 200
                and response.content
            ):
                try:
                    image = Image.open(io.BytesIO(response.content))
                    image.verify()
                    image.close()
                    return response.content
                except Exception:
                    pass

        except requests.RequestException:

            pass

        if attempt < RETRY_PER_PAGE:

            time.sleep(1)

    return None


def download_edition(
    name,
    edition_code,
    dt
):

    date_str = dt.strftime(
        "%d-%m-%Y"
    )

    log(
        f"==> {name} "
        f"({date_str}): "
        f"pages dhoondi ja rahi hain..."
    )

    images = []

    for page in range(
        1,
        MAX_PAGES + 1
    ):

        page_url = build_page_url(
            edition_code,
            page,
            dt
        )

        response = download_page(
            page_url
        )

        if response is None:

            log(
                f"    [{name}] "
                f"page {page}: "
                f"nahi mila -- rukk raha hoon"
            )

            break

        image_url = find_image_url(
            response.text
        )

        if image_url is None:

            log(
                f"    [{name}] "
                f"page {page}: "
                f"image nahi mili"
            )

            break

        image_url = make_full_url(
            image_url
        )

        image_data = download_image(
            image_url
        )

        if image_data is None:

            log(
                f"    [{name}] "
                f"page {page}: "
                f"download fail"
            )

            break

        images.append(
            image_data
        )

        log(
            f"    [{name}] "
            f"page {page}: OK "
            f"({len(image_data)//1024} KB)"
        )

    if not images:

        log(
            f"==> {name}: "
            f"koi page nahi mila."
        )

        return False

    # ================= PDF =================
    # Memory-safe: JPEG bytes seedha PDF mein wrap hote hain, poori list
    # decode karke RAM mein RGB images ke tor par nahi rakhi jaati
    # (pehle wala tareeqa 20 high-res pages par bhi memory crash de
    # sakta tha).

    jpeg_pages = []

    for raw in images:

        try:

            img = Image.open(io.BytesIO(raw))

            if img.format == "JPEG" and img.mode == "RGB":
                img.close()
                jpeg_pages.append(raw)
            else:
                img = img.convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=92)
                img.close()
                jpeg_pages.append(buf.getvalue())

        except Exception as error:

            log(
                f"[{name}] "
                f"image error: "
                f"{error}"
            )

    if not jpeg_pages:

        return False

    day_no = str(
        int(
            dt.strftime("%d")
        )
    )

    mon_title = dt.strftime(
        "%b"
    )

    out_name = (
        f"DailyK2 {name} "
        f"{day_no}{mon_title}.pdf"
    )

    out_path = os.path.join(
        OUTPUT_FOLDER,
        out_name
    )

    with open(out_path, "wb") as f:
        f.write(img2pdf.convert(jpeg_pages))

    log(
        f"==> {name}: "
        f"PDF ban gaya -- "
        f"{out_name} "
        f"({len(jpeg_pages)} pages)"
    )

    jpeg_pages = None
    gc.collect()

    return True


# ===================== MAIN =======================

if __name__ == "__main__":

    start = time.time()

    dt = get_target_date()

    log(
        "============================================"
    )

    log(
        "Daily K2 E-Paper Downloader"
    )

    log(
        f"Output folder: "
        f"{OUTPUT_FOLDER}"
    )

    log(
        f"Target date: "
        f"{dt.strftime('%d-%m-%Y')}"
    )

    log(
        f"Editions: "
        f"{', '.join(EDITIONS.keys())}"
    )

    log(
        "============================================"
    )

    results = {}

    for name, edition_code in EDITIONS.items():

        try:

            ok = download_edition(
                name,
                edition_code,
                dt
            )

            results[name] = ok

        except Exception as error:

            results[name] = False

            log(
                f"{name}: ERROR -> "
                f"{error}"
            )

    # ================= SUMMARY =================

    log("")

    log(
        "===================== SUMMARY ====================="
    )

    success = 0

    for name, ok in results.items():

        status = (
            "OK"
            if ok
            else "FAILED"
        )

        if ok:

            success += 1

        log(
            f"{name:<20} -> {status}"
        )

    log(
        f"Total: "
        f"{success}/{len(EDITIONS)} "
        f"editions successful."
    )

    log(
        "====================================================="
    )

    log(
        f"Time taken: "
        f"{time.time() - start:.2f} seconds"
    )
