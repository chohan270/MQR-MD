#!/usr/bin/env python3
"""Reaction-triggered PDF processor.

Keeps the mw.py cleanup/merge pipeline and uses wm.py's two-PNG watermark
selection logic for the front page.
"""
import argparse
import io
import os
import re
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

import wm

MAX_PROMO_PAGES = 2
DARKNESS_THRESHOLD = 70
PROMO_KEYWORDS = [
    "whatsapp", "whats app", "social media", "join our group", "join group", "group link"
]
BOTTOM_WATERMARK_KEYWORDS = ["social media pakistan", "4938217"]
PAD_X = 2
PAD_Y_TOP = 1
PAD_Y_BOTTOM = 1
WIDTH_MULTIPLIER = 0.52
Y_OFFSET = -8


def clean_filename(filename):
    name, ext = os.path.splitext(filename)
    months = r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|June|July|August|September|October|November|December"
    match = re.match(rf"^(\d{{1,2}})\s+({months})\s+(.+)$", name, re.I)
    if match:
        day, month, rest = match.groups()
        name = f"{rest.strip()} {day}{month}"
    else:
        match = re.match(rf"^(.+?)\s+(\d{{1,2}})\s+({months})$", name, re.I)
        if match:
            rest, day, month = match.groups()
            name = f"{rest.strip()} {day}{month}"
    return re.sub(r"\s+", " ", name).strip() + ext.lower()


def is_promo_page(page):
    try:
        text = (page.extract_text() or "").lower()
    except Exception:
        text = ""
    if any(keyword in text for keyword in PROMO_KEYWORDS):
        return True
    try:
        images = page.images
        if not images:
            return False
        image = images[0].image.convert("L")
        image.thumbnail((150, 150))
        pixels = list(image.getdata())
        return bool(pixels) and sum(pixels) / len(pixels) < DARKNESS_THRESHOLD
    except Exception:
        return False


def remove_promo_pages(pages):
    check_count = min(MAX_PROMO_PAGES, len(pages) - 1)
    remove_indices = [
        len(pages) - offset
        for offset in range(1, check_count + 1)
        if is_promo_page(pages[len(pages) - offset])
    ]
    for index in sorted(remove_indices, reverse=True):
        pages.pop(index)
    return len(remove_indices)


def find_watermark_boxes(page):
    boxes = []

    def apply_matrix(point, matrix):
        x, y = point
        a, b, c, d, e, f = matrix
        return a * x + c * y + e, b * x + d * y + f

    def visitor(text, cm, tm, font_dict, font_size):
        if text.strip() and any(keyword in text.lower() for keyword in BOTTOM_WATERMARK_KEYWORDS):
            x, y = apply_matrix((0, 0), tm)
            x, y = apply_matrix((x, y), cm)
            boxes.append((text, x, y, font_size or 12))

    try:
        page.extract_text(visitor_text=visitor)
    except Exception:
        return []
    return boxes


def build_patch_overlay(page_width, page_height, boxes):
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(page_width, page_height))
    pdf.setFillColorRGB(1, 1, 1)
    for text, x, y, font_size in boxes:
        estimated_width = len(text) * font_size * WIDTH_MULTIPLIER
        rect_x = max(0, x - PAD_X)
        rect_y = max(0, y - (font_size * 0.25) + Y_OFFSET)
        rect_w = min(page_width - rect_x, estimated_width + 2 * PAD_X)
        rect_h = min(page_height - rect_y, (font_size * 0.8) + PAD_Y_TOP + PAD_Y_BOTTOM)
        pdf.rect(rect_x, rect_y, rect_w, rect_h, fill=1, stroke=0)
    pdf.save()
    buffer.seek(0)
    return PdfReader(buffer).pages[0]


def remove_bottom_watermark(pages):
    covered = 0
    for page in pages:
        boxes = find_watermark_boxes(page)
        if not boxes:
            continue
        mediabox = page.mediabox
        patch = build_patch_overlay(float(mediabox.width), float(mediabox.height), boxes)
        page.merge_page(patch)
        covered += 1
    return covered


def build_front_watermark(page):
    images = page.images
    if not images:
        return None, None
    image = images[0].image.convert("RGB")
    png_path, width, margin, position, opacity = wm.pick_watermark_settings(image)
    image = wm.apply_watermark(image, png_path, width, margin, position, opacity)
    buffer = io.BytesIO()
    image.save(buffer, format="PDF")
    buffer.seek(0)
    return PdfReader(buffer).pages[0], image


def process_pdf(pdf_path, output_path):
    reader = PdfReader(pdf_path)
    pages = list(reader.pages)
    if not pages:
        raise ValueError("PDF has no pages")

    remove_promo_pages(pages)
    remove_bottom_watermark(pages)

    front_page, _ = build_front_watermark(pages[0])
    writer = PdfWriter()
    for index, page in enumerate(pages):
        writer.add_page(front_page if index == 0 and front_page is not None else page)

    extra_pdf = wm.EXTRA_LAST_PDF
    if extra_pdf and os.path.exists(extra_pdf):
        for page in PdfReader(extra_pdf).pages:
            writer.add_page(page)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as output:
        writer.write(output)
    return output_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    process_pdf(args.input, args.output)
    print(f"MW_RESULT:{args.output}", flush=True)


if __name__ == "__main__":
    main()
