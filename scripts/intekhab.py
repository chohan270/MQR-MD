import requests
import re
import time
from PIL import Image, ImageFile
import img2pdf
import gc
from io import BytesIO
from datetime import datetime
import os


def _page_to_jpeg_bytes(raw_bytes):
    """
    Memory-safe: sirf EK page RAM mein decode hota hai (poori list decode
    RGB PIL Image objects se bhar kar RAM mein rakhna hi "memory quota
    exceeded" crash ki sabse badi wajah thi). Agar image already ek plain
    RGB JPEG hai to bina re-encode kiye seedha wapis kar deta hai.
    """
    try:
        _img = Image.open(BytesIO(raw_bytes))
        if _img.format == "JPEG" and _img.mode == "RGB":
            _img.close()
            return raw_bytes
        _img = _img.convert("RGB")
        _buf = BytesIO()
        _img.save(_buf, format="JPEG", quality=92)
        _img.close()
        return _buf.getvalue()
    except Exception:
        return raw_bytes

ImageFile.LOAD_TRUNCATED_IMAGES = True

# ===== TODAY DATE (site uses MM-DD-YY) =====
today = datetime.now()
DATE = today.strftime("%m-%d-%y")
DAY = today.strftime("%d")
MONTH_SHORT = today.strftime("%b")

# ===== EDITIONS (city name -> edition id used by dailyintekhab) =====
editions = {
    "Hub": 1,
    "Quetta": 2,
    "Karachi": 3,
}

BASE = "https://epaper.dailyintekhab.pk/today/st/{eid}/1/{date}"
MAX_RETRIES = 3
PAGE_DELAY = 0.5

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"),
}

# Har page ki thumbnail is single request me hi mil jaati hai (poori list),
# is liye har page ke liye alag request karne ki zarurat nahi.
IMG_PATTERN = re.compile(
    r'(https://epaper\.dailyintekhab\.pk/uploads/[^"\'\)\s]+?page-(\d+)\.jpg)',
    re.IGNORECASE
)

# Alternate site layout used by dailyintekhab after the markup change:
# the page number is embedded in the surrounding <a href> link, while the
# actual image filename is a random hash/JPG. This fallback prevents a false
# "zero pages" result when the old regex no longer matches.
THUMB_PATTERN = re.compile(
    r'<a href="https://epaper\.dailyintekhab\.pk/today/st/(\d+)/(\d+)/[\d-]+">'
    r'<img src="(https://epaper\.dailyintekhab\.pk/uploads/[^"]+)"></a>',
    re.IGNORECASE
)
NOT_FOUND_MARKER = "This Page Not Found Yet"
MIN_EXPECTED_PAGES = {
    "Hub": 4,
    "Quetta": 4,
    "Karachi": 4,
}
POLL_INTERVAL_MINUTES = 10
MAX_WAIT_HOURS = 3

SAVE_FOLDER = "DailyIntekhab_PDFs"
os.makedirs(SAVE_FOLDER, exist_ok=True)


def fetch_listing(eid, session):
    url = BASE.format(eid=eid, date=DATE)
    r = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                return r
        except Exception as e:
            print(f"  ⚠️  attempt {attempt} failed: {e}")
        time.sleep(1.0 * attempt)
    return r


def download_edition_fallback(edition, eid, debug_dump=False):
    print(f"\n📖 Trying fallback parser for {edition}...")
    session = requests.Session()
    start_time = time.time()
    page_map = {}
    min_expected = MIN_EXPECTED_PAGES.get(edition, 1)
    last_html = ""

    while True:
        r = fetch_listing(eid, session)
        elapsed_min = (time.time() - start_time) / 60.0

        if r is None or r.status_code != 200:
            if elapsed_min >= MAX_WAIT_HOURS * 60:
                print(f"  ❌ {edition}: could not load page listing after {MAX_WAIT_HOURS}h — giving up.")
                return False
            print(f"  ⚠️  {edition}: listing page failed to load. Retrying in {POLL_INTERVAL_MINUTES} min...")
            time.sleep(POLL_INTERVAL_MINUTES * 60)
            continue

        last_html = r.text
        matches = THUMB_PATTERN.findall(r.text)
        page_map = {}
        for m_eid, page_num, img_url in matches:
            if int(m_eid) == eid:
                page_map[int(page_num)] = img_url

        if len(page_map) >= min_expected:
            break

        not_yet = NOT_FOUND_MARKER in r.text
        if elapsed_min >= MAX_WAIT_HOURS * 60:
            if page_map:
                print(f"  ⚠️  {edition}: only {len(page_map)}/{min_expected} pages after {MAX_WAIT_HOURS}h — saving what's there.")
                break
            print(f"  ❌ {edition}: today's edition never appeared after {MAX_WAIT_HOURS}h — giving up.")
            if debug_dump:
                dump_path = os.path.join(SAVE_FOLDER, f"debug_{edition}_fallback.html")
                with open(dump_path, "w", encoding="utf-8") as f:
                    f.write(last_html)
                print(f"  ℹ️  Raw HTML saved to {dump_path} for inspection.")
            return False

        reason = "not uploaded yet (site shows 'This Page Not Found Yet!')" if not_yet else f"only {len(page_map)}/{min_expected} pages so far"
        print(f"  ⏳ {edition}: {reason}. Waiting {POLL_INTERVAL_MINUTES} min before checking again...")
        time.sleep(POLL_INTERVAL_MINUTES * 60)

    sorted_pages = sorted(page_map.items())
    images = []
    for page_num, img_url in sorted_pages:
        img = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                ir = session.get(img_url, headers=HEADERS, timeout=15)
                img = _page_to_jpeg_bytes(ir.content)
                break
            except Exception as e:
                if attempt == MAX_RETRIES:
                    print(f"  ({edition} page {page_num} image download failed after {MAX_RETRIES} tries: {e})")
                else:
                    time.sleep(1.0 * attempt)
        if img is None:
            continue
        images.append(img)
        print(f"{edition} - Page {page_num} added (fallback)")
        time.sleep(PAGE_DELAY)

    if not images:
        print(f"❌ {edition} fallback pages not found")
        return False

    pdf_name = f"Intekhab {edition} {DAY}{MONTH_SHORT}.pdf"
    pdf_path = os.path.join(SAVE_FOLDER, pdf_name)
    with open(pdf_path, "wb") as _f:
        _f.write(img2pdf.convert(images))
    print(f"✅ {edition} PDF ready via fallback: {pdf_path}  ({len(images)} pages)")
    return True


def download_edition(edition, eid, debug_dump=False):
    print(f"\n📖 Downloading {edition} newspaper...")
    session = requests.Session()
    url = BASE.format(eid=eid, date=DATE)

    r = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(url, headers=HEADERS, timeout=20)
            if r.status_code == 200:
                break
        except Exception as e:
            print(f"  ⚠️  attempt {attempt} failed: {e}")
        time.sleep(1.0 * attempt)

    if r is None or r.status_code != 200:
        print(f"  ❌ {edition}: could not load page listing (HTTP {r.status_code if r else 'no response'})")
        return download_edition_fallback(edition, eid, debug_dump) if not debug_dump else download_edition_fallback(edition, eid, debug_dump)

    matches = IMG_PATTERN.findall(r.text)
    if not matches:
        print(f"  ❌ {edition}: no page images found on listing page.")
        if debug_dump:
            dump_path = os.path.join(SAVE_FOLDER, f"debug_{edition}.html")
            with open(dump_path, "w", encoding="utf-8") as f:
                f.write(r.text)
            print(f"  ℹ️  Raw HTML saved to {dump_path} for inspection.")
        return download_edition_fallback(edition, eid, debug_dump)

    # dedupe + sort by page number, keep url
    page_map = {}
    for img_url, page_num in matches:
        page_map[int(page_num)] = img_url
    sorted_pages = sorted(page_map.items())

    images = []
    for page_num, img_url in sorted_pages:
        img = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                ir = session.get(img_url, headers=HEADERS, timeout=15)
                img = _page_to_jpeg_bytes(ir.content)
                break
            except Exception as e:
                if attempt == MAX_RETRIES:
                    print(f"  ({edition} page {page_num} image download failed after {MAX_RETRIES} tries: {e})")
                else:
                    time.sleep(1.0 * attempt)
        if img is None:
            continue
        images.append(img)
        print(f"{edition} - Page {page_num} added")
        time.sleep(PAGE_DELAY)

    if images:
        pdf_name = f"Intekhab {edition} {DAY}{MONTH_SHORT}.pdf"
        pdf_path = os.path.join(SAVE_FOLDER, pdf_name)
        with open(pdf_path, "wb") as _f:
            _f.write(img2pdf.convert(images))
        print(f"✅ {edition} PDF ready: {pdf_path}  ({len(images)} pages)")
        return True

    print(f"❌ {edition} pages not found")
    return download_edition_fallback(edition, eid, debug_dump)


for edition, eid in editions.items():
    download_edition(edition, eid, debug_dump=True)
    time.sleep(1.5)
