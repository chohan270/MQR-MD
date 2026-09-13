#!/usr/bin/env python3
"""Download today's Lead Pakistan e-paper as a PDF."""
import argparse
import io
import os
from datetime import datetime

import requests
from PIL import Image
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

TIMEOUT = 20
MAX_WIDTH = 1600
JPEG_QUALITY = 70


def download_today(output_dir):
    now = datetime.now()
    year_month = now.strftime("%Y%m")
    day = now.strftime("%d")
    date_for_name = now.strftime("%d%b")
    base_url = f"https://leadpakistan.com.pk/ep/{year_month}/{day}/pages/Page{{}}.jpg"
    output_path = os.path.join(output_dir, f"Daily LeadPakistan {date_for_name}.pdf")
    os.makedirs(output_dir, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36"})
    pdf = None
    page_count = 0
    try:
        for page_number in range(1, 101):
            response = session.get(base_url.format(page_number), timeout=TIMEOUT)
            if response.status_code != 200:
                break
            image = Image.open(io.BytesIO(response.content))
            image.load()
            if image.mode != "RGB":
                image = image.convert("RGB")
            if image.width > MAX_WIDTH:
                ratio = MAX_WIDTH / image.width
                image = image.resize((MAX_WIDTH, int(image.height * ratio)), Image.Resampling.LANCZOS)
            compressed = io.BytesIO()
            image.save(compressed, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            compressed.seek(0)
            size = (image.width, image.height)
            if pdf is None:
                pdf = canvas.Canvas(output_path, pagesize=size)
            else:
                pdf.setPageSize(size)
            pdf.drawImage(ImageReader(compressed), 0, 0, width=size[0], height=size[1], mask="auto")
            pdf.showPage()
            page_count += 1
            image.close()
            compressed.close()
        if pdf is None or page_count == 0:
            raise RuntimeError("today's Lead Pakistan edition was not found")
        pdf.save()
    finally:
        session.close()
    print(f"Lead Pakistan: {page_count} pages -> {output_path}", flush=True)
    return output_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--outdir", default=".")
    args = parser.parse_args()
    download_today(args.outdir)


if __name__ == "__main__":
    main()
