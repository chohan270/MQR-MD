#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import io
import os
import time
from datetime import datetime, timedelta, timezone

import img2pdf
import requests
from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = False

OUTPUT_FOLDER = "BusinessRecorder_PDFs"
BASE_IMAGE_URL = "https://e.brecorder.com/image/papers/{year}/{month}/{day}/page_{page}.jpg?download=1"
MANDATORY_PAGES = tuple(range(1, 11))
OPTIONAL_PAGES = (91, 95, 96, 97)
RETRIES = 4
TIMEOUT = 35
MIN_IMAGE_BYTES = 20_000
MIN_IMAGE_WIDTH = 500
MIN_IMAGE_HEIGHT = 700
PKT = timezone(timedelta(hours=5))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Accept": "image/avif,image/webp,image/jpeg,image/*,*/*;q=0.8",
    "Referer": "https://epaper.brecorder.com/",
}


def log(message):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}", flush=True)


def page_url(date_obj, page_number):
    return BASE_IMAGE_URL.format(
        year=date_obj.strftime("%Y"),
        month=date_obj.strftime("%m"),
        day=date_obj.strftime("%d"),
        page=page_number,
    )


def fetch_image(session, url):
    last_error = "unknown error"
    for attempt in range(1, RETRIES + 1):
        try:
            response = session.get(url, headers=HEADERS, timeout=TIMEOUT)
            if response.status_code == 404:
                return None, "not found"
            if response.status_code != 200:
                last_error = f"HTTP {response.status_code}"
            elif len(response.content) < MIN_IMAGE_BYTES:
                last_error = f"too small ({len(response.content)} bytes)"
            else:
                with Image.open(io.BytesIO(response.content)) as image:
                    image.load()
                    if image.width < MIN_IMAGE_WIDTH or image.height < MIN_IMAGE_HEIGHT:
                        last_error = f"unexpected size {image.width}x{image.height}"
                    else:
                        return response.content, None
        except (requests.RequestException, OSError, ValueError) as error:
            last_error = str(error)
        if attempt < RETRIES:
            time.sleep(attempt)
    return None, last_error


def normalise_jpeg(raw_bytes):
    with Image.open(io.BytesIO(raw_bytes)) as image:
        image.load()
        if image.format == "JPEG" and image.mode == "RGB":
            return raw_bytes
        converted = image.convert("RGB")
        buffer = io.BytesIO()
        converted.save(buffer, format="JPEG", quality=95)
        return buffer.getvalue()


def download_paper(date_obj=None):
    date_obj = date_obj or datetime.now(PKT)
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    session = requests.Session()
    page_bytes = {}

    for page_number in MANDATORY_PAGES:
        url = page_url(date_obj, page_number)
        raw_bytes, error = fetch_image(session, url)
        if raw_bytes is None:
            log(f"Business Recorder page {page_number} missing/invalid: {error}")
            log("Mandatory page missing; refusing to create an incomplete PDF")
            return None
        page_bytes[page_number] = normalise_jpeg(raw_bytes)
        log(f"Business Recorder page {page_number}: OK")

    for page_number in OPTIONAL_PAGES:
        raw_bytes, error = fetch_image(session, page_url(date_obj, page_number))
        if raw_bytes is not None:
            page_bytes[page_number] = normalise_jpeg(raw_bytes)
            log(f"Business Recorder extra page {page_number}: OK")
        elif error != "not found":
            log(f"Business Recorder extra page {page_number}: skipped ({error})")

    ordered_pages = sorted(page_bytes)
    if ordered_pages[:len(MANDATORY_PAGES)] != list(MANDATORY_PAGES):
        log("Page sequence validation failed; refusing to create PDF")
        return None

    filename = f"Business Recorder {date_obj.strftime('%d%B')}.pdf"
    output_path = os.path.join(OUTPUT_FOLDER, filename)
    with open(output_path, "wb") as output_file:
        output_file.write(img2pdf.convert([page_bytes[number] for number in ordered_pages]))
    log(f"Business Recorder PDF ready: {output_path} ({len(ordered_pages)} pages)")
    return output_path


if __name__ == "__main__":
    download_paper()