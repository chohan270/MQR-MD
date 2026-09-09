#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import img2pdf
import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = False

OUTPUT_FOLDER = "ThePatriot_PDFs"
TIMEOUT = 30
RETRIES = 4
MIN_IMAGE_BYTES = 10_000
PKT = timezone(timedelta(hours=5))
ARCHIVE = "https://epaper.dailythepatriot.com/edition/the-daily-patriot-{date}/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,image/avif,image/webp,image/*,*/*;q=0.8",
}


def log(message):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def get(session, url):
    last_error = "unknown error"
    for attempt in range(1, RETRIES + 1):
        try:
            response = session.get(url, headers=HEADERS, timeout=TIMEOUT)
            if response.status_code == 200 and response.content:
                return response
            last_error = f"HTTP {response.status_code}"
        except requests.RequestException as error:
            last_error = str(error)
        if attempt < RETRIES:
            time.sleep(attempt)
    raise RuntimeError(f"{url}: {last_error}")


def image_urls(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for tag in soup.find_all(["img", "source"]):
        for attribute in ("src", "data-src", "data-original", "data-lazy-src", "data-image"):
            value = tag.get(attribute)
            if not value:
                continue
            value = urljoin(base_url, value)
            if re.search(r"\.(?:jpg|jpeg|png|webp)(?:\?|$)", value, re.IGNORECASE):
                found.append(value)
    return list(dict.fromkeys(found))


def load_image(session, url):
    response = get(session, url)
    if len(response.content) < MIN_IMAGE_BYTES:
        raise ValueError(f"image too small: {len(response.content)} bytes")
    with Image.open(io.BytesIO(response.content)) as image:
        image.load()
        converted = image.convert("RGB")
        buffer = io.BytesIO()
        converted.save(buffer, format="JPEG", quality=95)
        return buffer.getvalue(), image.width * image.height


def find_pages(session, date_obj):
    archive_url = ARCHIVE.format(date=date_obj.strftime("%Y_%m_%d"))
    archive_response = get(session, archive_url)
    soup = BeautifulSoup(archive_response.text, "html.parser")
    pages = {}

    for anchor in soup.find_all("a", href=True):
        url = urljoin(archive_url, anchor["href"])
        text = " ".join(anchor.stripped_strings)
        match = re.search(r"page[-_ ]?(\d+)", url, re.IGNORECASE) or re.search(r"\bpage[-_ ]?(\d+)\b", text, re.IGNORECASE)
        if match:
            pages.setdefault(int(match.group(1)), url)

    for image in soup.find_all("img"):
        alt = image.get("alt", "")
        source = image.get("src") or image.get("data-src")
        match = re.search(r"P(\d+)-Daily The Patriot", alt, re.IGNORECASE)
        if source and match:
            pages.setdefault(int(match.group(1)), urljoin(archive_url, source))

    if not pages:
        raise RuntimeError(f"Official Patriot edition not found for {date_obj:%Y-%m-%d}")
    numbers = sorted(pages)
    expected = list(range(numbers[0], numbers[-1] + 1))
    if numbers != expected:
        raise RuntimeError(f"Patriot page sequence has a gap: found {numbers}")
    return pages


def download_paper(date_obj=None):
    date_obj = date_obj or datetime.now(PKT)
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    session = requests.Session()
    page_links = find_pages(session, date_obj)
    page_bytes = []

    for page_number, page_url in sorted(page_links.items()):
        candidates = [page_url]
        try:
            page_response = get(session, page_url)
            candidates = image_urls(page_response.text, page_url)
        except Exception as error:
            log(f"Page {page_number}: page HTML unavailable ({error})")
        if re.search(r"\.(?:jpg|jpeg|png|webp)(?:\?|$)", page_url, re.IGNORECASE):
            candidates.insert(0, page_url)

        best = None
        best_area = 0
        for candidate in dict.fromkeys(candidates):
            try:
                content, area = load_image(session, candidate)
                if area > best_area:
                    best, best_area = content, area
            except (OSError, ValueError, RuntimeError):
                continue
        if best is None:
            raise RuntimeError(f"Patriot page {page_number} has no valid full image")
        page_bytes.append(best)
        log(f"The Patriot ISB page {page_number}: OK")

    filename = f"The Patriot ISB {date_obj:%d%b}.pdf"
    output_path = os.path.join(OUTPUT_FOLDER, filename)
    with open(output_path, "wb") as output_file:
        output_file.write(img2pdf.convert(page_bytes))
    log(f"The Patriot ISB PDF ready: {output_path} ({len(page_bytes)} pages)")
    return output_path


if __name__ == "__main__":
    download_paper()