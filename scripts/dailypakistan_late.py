#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import io
import re
import time
import datetime
import warnings
import requests
from bs4 import BeautifulSoup
from PIL import Image

warnings.filterwarnings("ignore")

# ============================================================
# DAILY PAKISTAN E-PAPER
# ALL EDITIONS AUTO CHECK + PDF
# ============================================================

# The scheduler runs each cwd-mode script in its own temporary folder and
# collects PDFs recursively from there. This also works on Heroku.
OUTPUT_FOLDER = "DailyPakistan_Late_PDFs"

MAX_PAGES = 30
TIMEOUT = 60
RETRIES = 6

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0.0.0 Mobile Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://dailypakistan.com.pk/",
    "Connection": "close",
}

# Known Daily Pakistan editions
EDITIONS = [
    "peshawar",
    "multan",
    "lahore",
    "karachi",
    "islamabad",
    "rawalpindi",
    "gujranwala",
    "faisalabad",
    "quetta",
    "hyderabad",
    "sargodha",
    "bahawalpur",
]

os.makedirs(OUTPUT_FOLDER, exist_ok=True)


def log(text):
    now = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{now}] {text}", flush=True)


# ============================================================
# URL
# ============================================================

def make_url(edition, date, page):
    d = date.strftime("%Y-%m-%d")

    return (
        f"https://dailypakistan.com.pk/"
        f"E-Paper/{edition}/{d}/page-{page}"
    )


# ============================================================
# GET HTML
# ============================================================

def get_html(url):

    for attempt in range(1, RETRIES + 1):

        session = requests.Session()

        try:

            session.headers.update(HEADERS)

            r = session.get(
                url,
                timeout=(20, TIMEOUT),
                verify=False
            )

            if r.status_code == 200 and r.text:

                return r.text

            log(
                f"HTTP {r.status_code} "
                f"attempt {attempt}/{RETRIES}"
            )

        except Exception as e:

            log(
                f"Connection error "
                f"attempt {attempt}/{RETRIES}: {e}"
            )

        finally:

            try:
                session.close()
            except:
                pass

        if attempt < RETRIES:
            time.sleep(min(attempt * 2, 10))

    return None


# ============================================================
# FIND E-PAPER IMAGE
# ============================================================

def find_image(html):

    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    # First try image tags
    for img in soup.find_all("img"):

        sources = [
            img.get("src"),
            img.get("data-src"),
            img.get("data-original"),
            img.get("data-lazy-src"),
            img.get("data-original-src"),
        ]

        for src in sources:

            if not src:
                continue

            src = src.strip()

            if "/epaper_image/" not in src:
                continue

            if src.startswith("//"):
                src = "https:" + src

            elif src.startswith("/"):
                src = (
                    "https://dailypakistan.com.pk"
                    + src
                )

            return src

    # Raw HTML fallback
    patterns = [
        r'https?://[^"\']+/epaper_image/[^"\']+',
        r'//[^"\']+/epaper_image/[^"\']+',
        r'["\']([^"\']*epaper_image/[^"\']+)["\']',
    ]

    for pattern in patterns:

        try:
            matches = re.findall(
                pattern,
                html
            )
        except:
            matches = []

        if not matches:
            continue

        src = matches[0]

        if src.startswith("//"):
            src = "https:" + src

        elif src.startswith("/"):
            src = (
                "https://dailypakistan.com.pk"
                + src
            )

        return src

    return None


# ============================================================
# DETECT PAGES
# ============================================================

def detect_pages(html):

    pages = set()

    # Search page links
    matches = re.findall(
        r"/page-(\d+)",
        html
    )

    for number in matches:

        try:

            number = int(number)

            if 1 <= number <= MAX_PAGES:
                pages.add(number)

        except:
            pass

    # Page 1 definitely exists
    pages.add(1)

    return max(pages)


# ============================================================
# DOWNLOAD IMAGE
# ============================================================

def download_image(url):

    for attempt in range(1, RETRIES + 1):

        session = requests.Session()

        try:

            session.headers.update({
                "User-Agent":
                    HEADERS["User-Agent"],

                "Accept":
                    "image/avif,image/webp,"
                    "image/apng,image/*,*/*;q=0.8",

                "Referer":
                    "https://dailypakistan.com.pk/",

                "Connection":
                    "close",
            })

            log(
                f"⬇️ image attempt "
                f"{attempt}/{RETRIES}"
            )

            r = session.get(
                url,
                timeout=(20, TIMEOUT),
                verify=False,
                stream=True
            )

            if r.status_code == 200:

                data = bytearray()

                for chunk in r.iter_content(
                    chunk_size=64 * 1024
                ):

                    if chunk:
                        data.extend(chunk)

                if data:
                    return bytes(data)

            log(
                f"Image HTTP {r.status_code}"
            )

        except Exception as e:

            log(
                f"⚠️ image connection error: {e}"
            )

        finally:

            try:
                session.close()
            except:
                pass

        if attempt < RETRIES:

            wait = min(
                attempt * 3,
                15
            )

            log(
                f"⏳ retry after {wait}s"
            )

            time.sleep(wait)

    return None


# ============================================================
# DOWNLOAD ONE EDITION
# ============================================================

def download_edition(
    edition,
    date
):

    display_name = edition.title()

    print()
    print("=" * 65)
    print(
        f"📰 DAILY PAKISTAN - "
        f"{display_name.upper()}"
    )
    print("=" * 65)

    first_url = make_url(
        edition,
        date,
        1
    )

    log(first_url)

    html = get_html(
        first_url
    )

    if not html:

        log(
            f"❌ {display_name}: "
            "not available"
        )

        return False

    # Make sure it is really an e-paper page
    first_image = find_image(
        html
    )

    if not first_image:

        log(
            f"❌ {display_name}: "
            "e-paper image not found"
        )

        return False

    total_pages = detect_pages(
        html
    )

    log(
        f"📄 Pages detected: "
        f"{total_pages}"
    )

    images = []

    # ========================================================
    # PAGES
    # ========================================================

    for page in range(
        1,
        total_pages + 1
    ):

        print(
            f"📄 {display_name} "
            f"Page {page}/{total_pages}",
            flush=True
        )

        current_url = make_url(
            edition,
            date,
            page
        )

        if page == 1:

            page_html = html

        else:

            page_html = get_html(
                current_url
            )

            if not page_html:

                log(
                    f"⚠️ Page {page}: "
                    "page failed"
                )

                continue

        image_url = find_image(
            page_html
        )

        if not image_url:

            log(
                f"⚠️ Page {page}: "
                "image not found"
            )

            continue

        raw = download_image(
            image_url
        )

        if not raw:

            log(
                f"❌ Page {page}: "
                "download failed"
            )

            continue

        try:

            image = Image.open(
                io.BytesIO(raw)
            )

            image = image.convert(
                "RGB"
            )

            images.append(
                image
            )

            log(
                f"✅ Page {page}: "
                f"{len(raw)//1024} KB "
                f"{image.width}x"
                f"{image.height}"
            )

        except Exception as e:

            log(
                f"❌ Page {page}: "
                f"{e}"
            )

        time.sleep(1)

    # ========================================================
    # PDF
    # ========================================================

    if not images:

        log(
            f"❌ {display_name}: "
            "no pages downloaded"
        )

        return False

    day = str(
        int(date.strftime("%d"))
    )

    month = date.strftime(
        "%b"
    )

    filename = (
        f"Daily Pakistan "
        f"{display_name} "
        f"{day}{month}.pdf"
    )

    output = os.path.join(
        OUTPUT_FOLDER,
        filename
    )

    log(
        "📕 Creating PDF..."
    )

    try:

        images[0].save(
            output,
            "PDF",
            resolution=150.0,
            save_all=True,
            append_images=images[1:]
        )

    except Exception as e:

        log(
            f"❌ PDF error: {e}"
        )

        return False

    size = (
        os.path.getsize(output)
        / (1024 * 1024)
    )

    print("-" * 65)

    log(
        f"✅ {display_name} PDF READY"
    )

    log(
        f"Pages: "
        f"{len(images)}/{total_pages}"
    )

    log(
        f"File: {output}"
    )

    log(
        f"Size: {size:.2f} MB"
    )

    print("-" * 65)

    return True


# ============================================================
# MAIN
# ============================================================

def main():

    start = time.time()

    today = datetime.datetime.now()

    print()
    print("=" * 65)
    print(
        "       DAILY PAKISTAN E-PAPER DOWNLOADER"
    )
    print(
        "             ALL EDITIONS"
    )
    print("=" * 65)

    log(
        f"Date: {today.strftime('%Y-%m-%d')}"
    )

    log(
        f"Editions checking: "
        f"{len(EDITIONS)}"
    )

    print("=" * 65)

    results = {}

    # ========================================================
    # CHECK ALL EDITIONS
    # ========================================================

    for edition in EDITIONS:

        try:

            results[edition] = (
                download_edition(
                    edition,
                    today
                )
            )

        except KeyboardInterrupt:

            print()

            log(
                "⛔ Download stopped."
            )

            return

        except Exception as e:

            log(
                f"❌ {edition}: "
                f"{e}"
            )

            results[edition] = False

    # ========================================================
    # SUMMARY
    # ========================================================

    print()
    print()
    print("=" * 65)
    print(
        "                         SUMMARY"
    )
    print("=" * 65)

    success = 0

    for edition, result in results.items():

        if result:

            success += 1
            status = "✅ DOWNLOADED"

        else:

            status = "❌ NOT AVAILABLE"

        print(
            f"{edition.title():<18} -> {status}"
        )

    print("-" * 65)

    print(
        f"Successful: "
        f"{success}/{len(EDITIONS)}"
    )

    print(
        f"Time: "
        f"{time.time() - start:.2f} seconds"
    )

    print("=" * 65)

    print()
    print(
        "📁 PDFs:"
    )
    print(
        OUTPUT_FOLDER
    )
    print()


if __name__ == "__main__":
    main()
