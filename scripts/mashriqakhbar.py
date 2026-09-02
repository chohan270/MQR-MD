#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mashriq Akhbar Lahore e-paper downloader.

This script follows the repo's standard pattern:
- outputs inside a local folder relative to the working directory
- handles the page discovery from the publisher's HTML
- saves a single PDF in the folder and exits
"""

import hashlib
import os
import re
import time
from datetime import datetime
from io import BytesIO

import requests
from bs4 import BeautifulSoup
from PIL import Image

warnings = None

BASE = "https://mashriqakhbar.com.pk"
OUTPUT_FOLDER = "Mashriq_Akhbar_PDFs"
DATE = datetime.now().strftime("%Y-%m-%d")
MAX_PAGES = 30
RETRY = 3

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 14) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/139.0.0.0 Mobile Safari/537.36"
    ),
    "Referer": BASE + "/",
}

os.makedirs(OUTPUT_FOLDER, exist_ok=True)


def get_html(session, url):
    for attempt in range(1, RETRY + 1):
        try:
            r = session.get(url, headers=HEADERS, timeout=30, verify=False)
            if r.status_code == 200:
                return r.text
            print(f"   HTTP {r.status_code} (try {attempt})")
        except Exception:
            print(f"   Connection error (try {attempt})")
        time.sleep(1)
    return None


def find_images(html):
    soup = BeautifulSoup(html, "html.parser")
    found = []

    for tag in soup.find_all("img"):
        for attr in ["src", "data-src", "data-original", "data-lazy-src"]:
            src = tag.get(attr)
            if not src:
                continue
            if "epaper-admin/uploads/pages" in src:
                found.append(src)

    patterns = re.findall(r'https?://[^"\']+epaper-admin/uploads/pages/[^"\']+', html, re.I)
    found.extend(patterns)

    result = []
    for x in found:
        x = x.replace("\\/", "/")
        if x.startswith("//"):
            x = "https:" + x
        elif x.startswith("/"):
            x = BASE + x
        if x not in result:
            result.append(x)
    return result


def image_hash(data):
    return hashlib.sha256(data).hexdigest()


def download(url, session):
    for attempt in range(1, RETRY + 1):
        try:
            r = session.get(url, headers=HEADERS, timeout=40, verify=False)
            if r.status_code == 200 and len(r.content) > 5000:
                return r.content
        except Exception:
            pass
        time.sleep(1)
    return None


def main():
    print("=" * 70)
    print("        MASHRIQ AKHBAR - LAHORE E-PAPER")
    print("=" * 70)
    print("Date:", DATE)
    print("Edition: Lahore")
    print("Output:", OUTPUT_FOLDER)
    print("=" * 70)

    session = requests.Session()
    pdf_images = []
    used_urls = set()
    used_hashes = set()

    for page in range(1, MAX_PAGES + 1):
        page_url = f"{BASE}/page/p{page}/{DATE}/1"
        print()
        print(f"📄 PAGE {page}")
        print("URL:", page_url)

        html = get_html(session, page_url)
        if not html:
            print("❌ Page open nahi hui")
            break

        image_urls = find_images(html)
        if not image_urls:
            print("❌ Image URL nahi mila")
            break

        new_image = None
        new_url = None
        new_data = None

        for image_url in image_urls:
            if image_url in used_urls:
                continue

            print("🖼 Try:", image_url)
            data = download(image_url, session)
            if not data:
                continue

            h = image_hash(data)
            if h in used_hashes:
                print("⚠️ Duplicate image - skipped")
                used_urls.add(image_url)
                continue

            try:
                img = Image.open(BytesIO(data)).convert("RGB")
                new_image = img
                new_url = image_url
                new_data = data
                break
            except Exception:
                continue

        if new_image is None:
            print("❌ Is page ke liye NEW image nahi mili")
            break

        used_urls.add(new_url)
        used_hashes.add(image_hash(new_data))
        pdf_images.append(new_image)

        print(f"✅ Page {page} added")
        print(f"   Size: {new_image.width}x{new_image.height}")

    print()
    print("=" * 70)
    print("              PDF BAN RAHI HAI")
    print("=" * 70)

    if not pdf_images:
        print("❌ Koi page download nahi hua")
        return

    pdf_path = os.path.join(OUTPUT_FOLDER, f"Mashriq_Akhbar_Lahore_{DATE}.pdf")
    pdf_images[0].save(pdf_path, "PDF", resolution=150, save_all=True, append_images=pdf_images[1:])

    print()
    print("✅ COMPLETE")
    print("Total unique pages:", len(pdf_images))
    print()
    print("PDF:")
    print(pdf_path)

    for img in pdf_images:
        try:
            img.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
