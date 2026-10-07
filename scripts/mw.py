#!/usr/bin/env python3
"""Reaction-triggered PDF processor.

Keeps the mw.py cleanup/merge pipeline and uses wm.py's two-PNG watermark
selection logic for the front page.
"""
import argparse
import io
import json
import os
import re
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import RectangleObject
from reportlab.pdfgen import canvas

import wm

MAX_PROMO_PAGES = 2
DARKNESS_THRESHOLD = 70
PROMO_KEYWORDS = [
    "whatsapp", "whats app", "social media", "join our group", "join group", "group link"
]
BOTTOM_WATERMARK_TEXT = "Social Media Pakistan 0342-4938217"
WATERMARK_PATCH_PADDING = 2
_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
_SKIP_HASHES_PATH = _ASSETS_DIR / "mw_auto_skip_image_hashes.json"
_SKIP_HASH_DATA = json.loads(_SKIP_HASHES_PATH.read_text(encoding="utf-8"))
AUTO_SKIP_PAGE_HASHES = tuple(_SKIP_HASH_DATA["pageHashes"])
AUTO_SKIP_IMAGE_HASHES = tuple(_SKIP_HASH_DATA["imageHashes"])
REFERENCE_HASH_MAX_DISTANCE = 4


def clean_filename(filename):
    name, ext = os.path.splitext(filename)
    name = re.sub(r'(?i)(?:^|[\s._-])mw(?:[\s._-]|$)', ' ', name)
    name = re.sub(r'(?i)(?:^|[\s._-])m\.?w\.?(?:[\s._-]|$)', ' ', name)

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
    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"^[\s._-]+|[\s._-]+$", "", name)
    date_first = re.match(rf"^(\d{{1,2}})\s+({months})\s+(.+)$", name, re.I)
    if date_first:
        day, month, rest = date_first.groups()
        name = f"{rest.strip()} {day}{month}"
    return name + ext.lower()


def image_difference_hash(image):
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    if alpha.getextrema()[0] < 255:
        bounds = alpha.getbbox()
        if bounds:
            rgba = rgba.crop(bounds)
        background = Image.new("RGBA", rgba.size, "white")
        background.alpha_composite(rgba)
        image = background.convert("RGB")
    else:
        image = rgba.convert("RGB")

    grayscale = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
    pixels = list(grayscale.getdata())
    fingerprint = 0
    for y in range(8):
        for x in range(8):
            fingerprint = (fingerprint << 1) | (pixels[y * 9 + x] > pixels[y * 9 + x + 1])
    return f"{fingerprint:016x}"


def _matches_reference_hash(fingerprint, references):
    value = int(fingerprint, 16)
    return any(
        (value ^ int(reference, 16)).bit_count() <= REFERENCE_HASH_MAX_DISTANCE
        for reference in references
    )


def _render_page_for_image_match(page):
    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_page(page)
    writer.write(buffer)
    document = pdfium.PdfDocument(buffer.getvalue())
    try:
        return document[0].render(scale=0.35).to_pil().convert("RGB")
    finally:
        document.close()


def has_reference_ad_image(page):
    page_images = page.images
    for page_image in page_images:
        fingerprint = image_difference_hash(page_image.image)
        if (
            _matches_reference_hash(fingerprint, AUTO_SKIP_PAGE_HASHES)
            or _matches_reference_hash(fingerprint, AUTO_SKIP_IMAGE_HASHES)
        ):
            return True

    if not page_images:
        fingerprint = image_difference_hash(_render_page_for_image_match(page))
        return _matches_reference_hash(fingerprint, AUTO_SKIP_PAGE_HASHES)
    return False


def contains_reference_ad(pdf_path):
    reader = PdfReader(pdf_path)
    return any(has_reference_ad_image(page) for page in reader.pages)


def is_promo_page(page):
    try:
        text = (page.extract_text() or "").lower()
    except Exception:
        text = ""
    watermark_pattern = r"social\s*media\s*pakistan\s*0342[\s-]*4938217"
    text_without_watermark = re.sub(watermark_pattern, "", text)
    if any(keyword in text_without_watermark for keyword in PROMO_KEYWORDS):
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
    writer = PdfWriter()
    writer.add_page(page)
    buffer = io.BytesIO()
    writer.write(buffer)

    document = pdfium.PdfDocument(buffer.getvalue())
    text_page = None
    try:
        text_page = document[0].get_textpage()
        text = text_page.get_text_range()
        char_count = text_page.count_chars()
        if len(text) != char_count:
            text = "".join(text_page.get_text_range(index, 1) for index in range(char_count))

        normalized = []
        source_indices = []
        for index, char in enumerate(text):
            for normalized_char in char.casefold():
                if normalized_char.isalnum():
                    normalized.append(normalized_char)
                    source_indices.append(index)

        normalized_text = "".join(normalized)
        target = "".join(char.casefold() for char in BOTTOM_WATERMARK_TEXT if char.isalnum())
        boxes = []
        offset = 0
        while (match_start := normalized_text.find(target, offset)) != -1:
            char_boxes = [
                text_page.get_charbox(source_indices[index])
                for index in range(match_start, match_start + len(target))
            ]
            char_boxes = [box for box in char_boxes if box[2] > box[0] and box[3] > box[1]]
            if char_boxes:
                boxes.append((
                    min(box[0] for box in char_boxes),
                    min(box[1] for box in char_boxes),
                    max(box[2] for box in char_boxes),
                    max(box[3] for box in char_boxes),
                ))
            offset = match_start + len(target)
        return boxes
    finally:
        if text_page is not None:
            text_page.close()
        document.close()


def build_patch_overlay(page_width, page_height, boxes, origin_x=0, origin_y=0):
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(page_width, page_height))
    pdf.setFillColorRGB(1, 1, 1)
    for left, bottom, right, top in boxes:
        rect_x = max(0, left - WATERMARK_PATCH_PADDING)
        rect_y = max(0, bottom - WATERMARK_PATCH_PADDING)
        rect_right = min(page_width, right + WATERMARK_PATCH_PADDING)
        rect_top = min(page_height, top + WATERMARK_PATCH_PADDING)
        pdf.rect(rect_x, rect_y, rect_right - rect_x, rect_top - rect_y, fill=1, stroke=0)
    pdf.save()
    buffer.seek(0)
    overlay = PdfReader(buffer).pages[0]
    overlay.mediabox = RectangleObject([
        origin_x,
        origin_y,
        origin_x + page_width,
        origin_y + page_height,
    ])
    return overlay


def remove_bottom_watermark(pages):
    covered = 0
    for page in pages:
        boxes = find_watermark_boxes(page)
        if not boxes:
            continue
        mediabox = page.mediabox
        patch = build_patch_overlay(
            float(mediabox.width),
            float(mediabox.height),
            boxes,
            float(mediabox.left),
            float(mediabox.bottom),
        )
        page.merge_page(patch)
        covered += 1
    return covered


def build_front_watermark(page):
    return wm.build_watermarked_front_page_for_page(page)


def save_front_page_thumbnail(image, output_path):
    if image is None:
        return None
    thumb_path = os.path.splitext(output_path)[0] + ".thumb.jpg"
    with open(thumb_path, "wb") as thumb_file:
        thumb_file.write(wm.make_thumbnail_jpeg(image))
    return thumb_path


def process_pdf(pdf_path, output_path, skip_reference_images=False):
    if skip_reference_images and contains_reference_ad(pdf_path):
        print(f"Reference ad image found; automatic MW processing skipped: {pdf_path}")
        return None

    reader = PdfReader(pdf_path)
    pages = list(reader.pages)
    if not pages:
        raise ValueError("PDF has no pages")

    remove_promo_pages(pages)
    remove_bottom_watermark(pages)

    front_page, front_image = build_front_watermark(pages[0])
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
    save_front_page_thumbnail(front_image, output_path)
    return output_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--skip-reference-images", action="store_true")
    args = parser.parse_args()
    result = process_pdf(args.input, args.output, skip_reference_images=args.skip_reference_images)
    if result is None:
        print(f"MW_SKIPPED_REFERENCE_IMAGE:{args.input}", flush=True)
        return
    print(f"MW_RESULT:{args.output}", flush=True)


if __name__ == "__main__":
    main()
