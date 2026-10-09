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
from pypdf.generic import ContentStream, RectangleObject
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
REFERENCE_SKIP_IMAGE_HASHES = tuple(_SKIP_HASH_DATA["skipImageHashes"])
FRONT_PAGE_COVER_IMAGE_HASHES = tuple(_SKIP_HASH_DATA["coverImageHashes"])
_COVER_TEMPLATE_DIR = _ASSETS_DIR / "mw_cover_reference_images"
_SKIP_TEMPLATE_DIR = _ASSETS_DIR / "mw_skip_reference_images"


def _load_reference_template(path):
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        if rgba.getchannel("A").getextrema()[0] < 255:
            bounds = rgba.getchannel("A").getbbox()
            if bounds:
                rgba = rgba.crop(bounds)
            background = Image.new("RGBA", rgba.size, "white")
            background.alpha_composite(rgba)
            return background.convert("RGB")
        return rgba.convert("RGB")


_COVER_TEMPLATES = tuple(
    _load_reference_template(path)
    for path in sorted(_COVER_TEMPLATE_DIR.glob("reference-*.jpg"))
)
if len(_COVER_TEMPLATES) != len(FRONT_PAGE_COVER_IMAGE_HASHES):
    raise RuntimeError("Front-page cover reference images are missing from the assets directory")
_SKIP_REFERENCE_TEMPLATES = tuple(
    _load_reference_template(path)
    for path in sorted(_SKIP_TEMPLATE_DIR.glob("reference-*"))
)
if len(_SKIP_REFERENCE_TEMPLATES) != len(REFERENCE_SKIP_IMAGE_HASHES):
    raise RuntimeError("Full-PDF skip reference images are missing from the assets directory")
REFERENCE_HASH_MAX_DISTANCE = 4
REFERENCE_COVER_MATCH_THRESHOLD = 0.08
REFERENCE_SKIP_MATCH_THRESHOLDS = (0.045, 0.065)
REFERENCE_SKIP_MIN_WIDTH_FRACTIONS = (0.4, 0.0)
_COVER_WIDTH_FACTORS = (0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15, 1.2)


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


def _render_page_for_image_match(page, scale=0.35):
    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_page(page)
    writer.write(buffer)
    document = pdfium.PdfDocument(buffer.getvalue())
    try:
        return document[0].render(scale=scale).to_pil().convert("RGB")
    finally:
        document.close()


def has_reference_ad_image(page):
    page_images = page.images
    for page_image in page_images:
        fingerprint = image_difference_hash(page_image.image)
        if (
            _matches_reference_hash(fingerprint, AUTO_SKIP_PAGE_HASHES)
            or _matches_reference_hash(fingerprint, REFERENCE_SKIP_IMAGE_HASHES)
        ):
            return True

    if not page_images:
        fingerprint = image_difference_hash(_render_page_for_image_match(page))
        return _matches_reference_hash(fingerprint, AUTO_SKIP_PAGE_HASHES)
    return False


def contains_reference_ad(pdf_path):
    reader = PdfReader(pdf_path)
    for index, page in enumerate(reader.pages):
        if has_reference_ad_image(page):
            return True
        if index == 0 and page.images:
            rendered_page = _render_page_for_image_match(page, scale=0.35)
            if any(
                _candidate_cover_matches(
                    rendered_page,
                    template,
                    threshold=REFERENCE_SKIP_MATCH_THRESHOLDS[template_index],
                    minimum_width_fraction=REFERENCE_SKIP_MIN_WIDTH_FRACTIONS[template_index],
                )
                for template_index, template in enumerate(_SKIP_REFERENCE_TEMPLATES)
            ):
                return True
    return False


def _image_signature(image, size=8):
    return image.convert("RGB").resize((size, size), Image.Resampling.BILINEAR).tobytes()


def _signature_distance(first, second):
    return sum(abs(left - right) for left, right in zip(first, second)) / (len(first) * 255)


def _candidate_cover_matches(
    page_image,
    template,
    threshold=REFERENCE_COVER_MATCH_THRESHOLD,
    minimum_width_fraction=0.0,
):
    page_width, page_height = page_image.size
    template_width, template_height = template.size
    minimum_width = max(
        min(36, max(24, page_width // 14)),
        round(page_width * minimum_width_fraction),
    )
    maximum_width = min(int(page_width * 0.9), template_width)
    if maximum_width < minimum_width:
        return None

    coarse_candidates = []
    target_width = minimum_width
    while target_width <= maximum_width:
        target_height = max(1, round(template_height * target_width / template_width))
        if target_height > page_height:
            break
        scaled_template = template.resize((target_width, target_height), Image.Resampling.LANCZOS)
        template_signature = _image_signature(scaled_template)
        step_x = max(8, target_width // 3)
        step_y = max(6, target_height // 3)
        best_for_scale = []
        for top in range(0, page_height - target_height + 1, step_y):
            for left in range(0, page_width - target_width + 1, step_x):
                candidate = page_image.crop((
                    left,
                    top,
                    left + target_width,
                    top + target_height,
                ))
                score = _signature_distance(
                    template_signature,
                    _image_signature(candidate),
                )
                candidate_result = (
                    score,
                    left,
                    top,
                    target_width,
                    target_height,
                    step_x,
                    step_y,
                )
                if len(best_for_scale) < 5:
                    best_for_scale.append(candidate_result)
                    best_for_scale.sort()
                elif score < best_for_scale[-1][0]:
                    best_for_scale[-1] = candidate_result
                    best_for_scale.sort()
        coarse_candidates.extend(best_for_scale)
        target_width = max(target_width + 1, round(target_width * 1.35))

    if not coarse_candidates:
        return None
    if min(candidate[0] for candidate in coarse_candidates) > 0.18:
        return None

    refined_candidates = []
    for _, coarse_left, coarse_top, coarse_width, _, step_x, step_y in sorted(coarse_candidates)[:24]:
        for width_factor in _COVER_WIDTH_FACTORS:
            width = max(1, round(coarse_width * width_factor))
            height = max(1, round(template_height * width / template_width))
            if width > page_width or height > page_height:
                continue
            signature = _image_signature(template.resize((width, height), Image.Resampling.LANCZOS))
            offset_x = max(1, step_x // 3)
            offset_y = max(1, step_y // 3)
            for top in range(
                max(0, coarse_top - step_y),
                min(page_height - height, coarse_top + step_y) + 1,
                offset_y,
            ):
                for left in range(
                    max(0, coarse_left - step_x),
                    min(page_width - width, coarse_left + step_x) + 1,
                    offset_x,
                ):
                    candidate = page_image.crop((left, top, left + width, top + height))
                    score = _signature_distance(
                        signature,
                        _image_signature(candidate),
                    )
                    refined_candidates.append((
                        score,
                        left,
                        top,
                        width,
                        height,
                        offset_x,
                        offset_y,
                    ))

    best_match = None
    for _, left, top, width, height, step_x, step_y in sorted(refined_candidates)[:12]:
        for width_factor in (0.98, 1.0, 1.02):
            exact_width = max(1, round(width * width_factor))
            exact_height = max(1, round(template_height * exact_width / template_width))
            if exact_width > page_width or exact_height > page_height:
                continue
            signature = _image_signature(
                template.resize((exact_width, exact_height), Image.Resampling.LANCZOS),
                size=32,
            )
            for top_delta in (-step_y, 0, step_y):
                exact_top = max(0, min(page_height - exact_height, top + top_delta))
                for left_delta in (-step_x, 0, step_x):
                    exact_left = max(0, min(page_width - exact_width, left + left_delta))
                    candidate = page_image.crop((
                        exact_left,
                        exact_top,
                        exact_left + exact_width,
                        exact_top + exact_height,
                    ))
                    score = _signature_distance(
                        signature,
                        _image_signature(candidate, size=32),
                    )
                    if best_match is None or score < best_match[0]:
                        best_match = (
                            score,
                            (
                                exact_left,
                                exact_top,
                                exact_left + exact_width,
                                exact_top + exact_height,
                            ),
                        )

    if best_match and best_match[0] <= threshold:
        return best_match[1]
    return None


def _multiply_pdf_matrices(first, second):
    a, b, c, d, e, f = first
    g, h, i, j, k, l = second
    return (
        a * g + c * h,
        b * g + d * h,
        a * i + c * j,
        b * i + d * j,
        a * k + c * l + e,
        b * k + d * l + f,
    )


def _find_embedded_cover_boxes(page):
    image_hashes = {
        image.name.rsplit(".", 1)[0]: image_difference_hash(image.image)
        for image in page.images
    }
    boxes = []
    identity = (1, 0, 0, 1, 0, 0)

    def visit(content, resources, initial_matrix, depth=0):
        if depth > 8 or resources is None:
            return
        resources = resources.get_object()
        xobjects = resources.get("/XObject")
        if xobjects is None:
            return
        xobjects = xobjects.get_object()
        matrix = initial_matrix
        stack = []
        for operands, operator in ContentStream(content, page.pdf).operations:
            if operator == b"q":
                stack.append(matrix)
            elif operator == b"Q":
                if stack:
                    matrix = stack.pop()
            elif operator == b"cm":
                matrix = _multiply_pdf_matrices(matrix, tuple(float(value) for value in operands))
            elif operator == b"Do":
                resource_name = str(operands[0])
                xobject_ref = xobjects.get(resource_name)
                if xobject_ref is None:
                    continue
                xobject = xobject_ref.get_object()
                subtype = xobject.get("/Subtype")
                if subtype == "/Image":
                    fingerprint = image_hashes.get(resource_name.lstrip("/"))
                    if fingerprint and _matches_reference_hash(
                        fingerprint,
                        FRONT_PAGE_COVER_IMAGE_HASHES,
                    ):
                        corners = [
                            (
                                matrix[0] * x + matrix[2] * y + matrix[4],
                                matrix[1] * x + matrix[3] * y + matrix[5],
                            )
                            for x, y in ((0, 0), (1, 0), (0, 1), (1, 1))
                        ]
                        boxes.append((
                            min(point[0] for point in corners),
                            min(point[1] for point in corners),
                            max(point[0] for point in corners),
                            max(point[1] for point in corners),
                        ))
                elif subtype == "/Form":
                    form_matrix = tuple(float(value) for value in xobject.get("/Matrix", identity))
                    visit(
                        xobject,
                        xobject.get("/Resources", resources),
                        _multiply_pdf_matrices(matrix, form_matrix),
                        depth + 1,
                    )

    page_resources = page.get("/Resources")
    if page_resources is not None and page.get_contents() is not None:
        visit(page.get_contents(), page_resources, identity)
    return boxes


def _pdf_boxes_to_render_pixels(page, boxes, rendered_size):
    crop = page.cropbox
    crop_width = float(crop.width)
    crop_height = float(crop.height)
    rotation = int(page.get("/Rotate", 0)) % 360
    display_width = crop_height if rotation in (90, 270) else crop_width
    display_height = crop_width if rotation in (90, 270) else crop_height
    scale_x = rendered_size[0] / display_width
    scale_y = rendered_size[1] / display_height
    crop_left = float(crop.left)
    crop_bottom = float(crop.bottom)
    pixel_boxes = []
    for left, bottom, right, top in boxes:
        x0, x1 = left - crop_left, right - crop_left
        y0, y1 = bottom - crop_bottom, top - crop_bottom
        if rotation == 90:
            pixel_box = (y0 * scale_x, x0 * scale_y, y1 * scale_x, x1 * scale_y)
        elif rotation == 180:
            pixel_box = (
                (crop_width - x1) * scale_x,
                y0 * scale_y,
                (crop_width - x0) * scale_x,
                y1 * scale_y,
            )
        elif rotation == 270:
            pixel_box = (
                (crop_height - y1) * scale_x,
                (crop_width - x1) * scale_y,
                (crop_height - y0) * scale_x,
                (crop_width - x0) * scale_y,
            )
        else:
            pixel_box = (
                x0 * scale_x,
                (crop_height - y1) * scale_y,
                x1 * scale_x,
                (crop_height - y0) * scale_y,
            )
        pixel_boxes.append(tuple(round(value) for value in pixel_box))
    return pixel_boxes


def find_front_page_cover_boxes(page):
    page_images = page.images
    if not page_images:
        return [], (0, 0)

    rendered_page = _render_page_for_image_match(page, scale=0.35)
    embedded_boxes = _find_embedded_cover_boxes(page)
    if embedded_boxes:
        return _pdf_boxes_to_render_pixels(page, embedded_boxes, rendered_page.size), rendered_page.size

    boxes = []
    candidate_indices = set()
    for page_image in page.images:
        fingerprint = image_difference_hash(page_image.image)
        candidate_indices.update(
            index
            for index, reference in enumerate(FRONT_PAGE_COVER_IMAGE_HASHES)
            if _matches_reference_hash(fingerprint, (reference,))
        )
    templates = (
        [_COVER_TEMPLATES[index] for index in sorted(candidate_indices)]
        if candidate_indices
        else _COVER_TEMPLATES
    )
    for template in templates:
        box = _candidate_cover_matches(rendered_page, template)
        if box:
            padding_x = max(1, round((box[2] - box[0]) * 0.08))
            padding_y = max(1, round((box[3] - box[1]) * 0.08))
            boxes.append((
                max(0, box[0] - padding_x),
                max(0, box[1] - padding_y),
                min(rendered_page.width, box[2] + padding_x),
                min(rendered_page.height, box[3] + padding_y),
            ))
    return boxes, rendered_page.size


def cover_boxes_to_pdf(page, boxes, rendered_size):
    if not boxes:
        return []

    crop = page.cropbox
    media = page.mediabox
    crop_left = float(crop.left - media.left)
    crop_bottom = float(crop.bottom - media.bottom)
    crop_width = float(crop.width)
    crop_height = float(crop.height)
    rotation = int(page.get("/Rotate", 0)) % 360
    display_width = crop_height if rotation in (90, 270) else crop_width
    display_height = crop_width if rotation in (90, 270) else crop_height
    scale_x = rendered_size[0] / display_width
    scale_y = rendered_size[1] / display_height

    pdf_boxes = []
    for left, top, right, bottom in boxes:
        screen_left = left / scale_x
        screen_right = right / scale_x
        screen_top = top / scale_y
        screen_bottom = bottom / scale_y
        if rotation == 90:
            x0, x1 = screen_top, screen_bottom
            y0, y1 = screen_left, screen_right
        elif rotation == 180:
            x0, x1 = crop_width - screen_right, crop_width - screen_left
            y0, y1 = screen_top, screen_bottom
        elif rotation == 270:
            x0, x1 = crop_width - screen_bottom, crop_width - screen_top
            y0, y1 = crop_height - screen_right, crop_height - screen_left
        else:
            x0, x1 = screen_left, screen_right
            y0, y1 = crop_height - screen_bottom, crop_height - screen_top
        pdf_boxes.append((
            crop_left + x0,
            crop_bottom + y0,
            crop_left + x1,
            crop_bottom + y1,
        ))
    return pdf_boxes


def cover_front_page_regions(page, boxes, rendered_size):
    pdf_boxes = cover_boxes_to_pdf(page, boxes, rendered_size)
    if not pdf_boxes:
        return 0
    media = page.mediabox
    patch = build_patch_overlay(
        float(media.width),
        float(media.height),
        pdf_boxes,
        float(media.left),
        float(media.bottom),
    )
    page.merge_page(patch)
    return len(pdf_boxes)


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
        print(f"Full-PDF skip reference found; MW processing skipped: {pdf_path}")
        return None

    reader = PdfReader(pdf_path)
    pages = list(reader.pages)
    if not pages:
        raise ValueError("PDF has no pages")

    cover_boxes, rendered_size = find_front_page_cover_boxes(pages[0])
    if cover_boxes:
        covered = cover_front_page_regions(pages[0], cover_boxes, rendered_size)
        print(f"  Covered {covered} matching reference-image area(s) on the front page")

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
    parser.add_argument("--reference-images-checked", action="store_true")
    args = parser.parse_args()
    result = process_pdf(
        args.input,
        args.output,
        skip_reference_images=args.skip_reference_images and not args.reference_images_checked,
    )
    if result is None:
        print(f"MW_SKIPPED_REFERENCE_IMAGE:{args.input}", flush=True)
        return
    print(f"MW_RESULT:{args.output}", flush=True)


if __name__ == "__main__":
    main()
