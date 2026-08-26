#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Daily Ausaf Epaper (epaper.dailyausaf.com) Auto Downloader
=====================================================================
Malik Edition - All Editions Named Properly
"""

import argparse
import concurrent.futures
import gc
import hashlib
import io
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, parse_qs

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    sys.exit("requests missing hai. Pehle chalayein: pip install requests")

try:
    from PIL import Image, ImageFile
    ImageFile.LOAD_TRUNCATED_IMAGES = False
except ImportError:
    sys.exit("Pillow missing hai. Pehle chalayein: pip install pillow")

try:
    import img2pdf
except ImportError:
    sys.exit("img2pdf missing hai. Pehle chalayein: pip install img2pdf")


BASE = "https://epaper.dailyausaf.com"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ur;q=0.8",
    "Referer": BASE + "/",
    "Connection": "keep-alive",
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
}

HTML_RETRIES = 4
IMAGE_RETRIES = 6
RETRY_SLEEP = 1.5
REQUEST_TIMEOUT = 40
THREADS_PER_EDITION = 3
EDITION_DELAY = 2.5
STATION_PROBE_RANGE = range(1, 26)
MAX_PAGES_FALLBACK = 30

# ===================== CONFIG - ALL EDITIONS NAMED =====================

# Ye editions NAHI chahiye
EXCLUDE_STATIONS = {9, 11}

# Force include stations - discovery miss karay toh bhi yeh shaamil honge
FORCE_INCLUDE_STATIONS = {1, 2, 3, 4, 5, 7, 8}

# Manual edition names - EXACT names as per site
MANUAL_EDITION_NAMES = {
    1: "Islamabad",
    2: "Lahore",
    3: "Peshawar",
    4: "Gilgit Baltistan",
    5: "London",
    7: "Muzafarabad",
    8: "Karachi",
}

# Page discovery ke liye extra params
FALLBACK_PAGE_PARAMS = ["page", "pno", "page_no", "p", "pg", "no", "page_id"]

# ===========================================================

EDITIONS_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ausaf_editions_cache.json")
EDITIONS_CACHE_HOURS = 24

PKT = timezone(timedelta(hours=5))

FULL_IMG_RE = re.compile(
    r'(?:https?://epaper\.dailyausaf\.com/)?issues/\d{4}-\d{2}-\d{2}/\d+-full\.jpg',
    re.IGNORECASE,
)
OG_IMAGE_RE = re.compile(
    r'property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
JSON_IMAGE_KEY_RE = re.compile(
    r'["\'](?:image|img|page_image|src|url|file|path)["\']\s*:\s*["\']([^"\']+\.(?:jpg|jpeg|png))["\']',
    re.IGNORECASE,
)
MAPHILIGHTED_IMG_RE = re.compile(
    r'<img[^>]*class=["\']maphilighted["\'][^>]*src=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
STATIONISH_LINK_RE = re.compile(
    r'(?:href|src)=["\']([^"\']*station_id=\d+[^"\']*)["\']',
    re.IGNORECASE,
)


def unescape_slashes(text):
    return text.replace('\\/', '/')


def make_absolute(url):
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return BASE + url
    return BASE + "/" + url


def cache_busted(url):
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}_={int(time.time() * 1000)}"


def today_pkt_str():
    return datetime.now(PKT).strftime("%Y-%m-%d")


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def make_session():
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504],
                   allowed_methods=["GET"])
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=10)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update(HEADERS)
    return s


def http_get(session, url, extra_headers=None):
    last_err = None
    hdrs = dict(HEADERS)
    if extra_headers:
        hdrs.update(extra_headers)
    for attempt in range(1, HTML_RETRIES + 1):
        try:
            r = session.get(cache_busted(url), timeout=REQUEST_TIMEOUT, headers=hdrs)
            if r.status_code == 200 and r.text:
                return r
            last_err = f"HTTP {r.status_code}"
        except requests.RequestException as e:
            last_err = str(e)
        time.sleep(RETRY_SLEEP * attempt)
    log(f"    FAILED after {HTML_RETRIES} tries: {url}  ({last_err})")
    return None


def extract_full_image_url(html_text):
    for text in (html_text, unescape_slashes(html_text)):
        m = MAPHILIGHTED_IMG_RE.search(text)
        if m:
            return make_absolute(m.group(1))
        m = FULL_IMG_RE.search(text)
        if m:
            return make_absolute(m.group(0))
        m = JSON_IMAGE_KEY_RE.search(text)
        if m:
            url = m.group(1)
            if "issues" in url.lower() or url.lower().endswith((".jpg", ".jpeg", ".png")):
                return make_absolute(url)
        m = OG_IMAGE_RE.search(text)
        if m:
            url = m.group(1)
            if url.lower().endswith((".jpg", ".jpeg", ".png")):
                return make_absolute(url)
    return None


def download_and_verify_image(session, url):
    last_err = None
    for attempt in range(1, IMAGE_RETRIES + 1):
        try:
            r = session.get(cache_busted(url) if attempt > 1 else url,
                             timeout=REQUEST_TIMEOUT, stream=True)
            if r.status_code != 200:
                last_err = f"HTTP {r.status_code}"
                r.close()
            else:
                chunks = []
                for chunk in r.raw.stream(65536, decode_content=True):
                    if chunk:
                        chunks.append(chunk)
                content = b"".join(chunks)
                r.close()
                expected_len = r.headers.get("Content-Length")
                if expected_len is not None and int(expected_len) != len(content):
                    last_err = f"size mismatch (expected {expected_len}, got {len(content)})"
                elif len(content) < 2000:
                    last_err = f"too small ({len(content)} bytes)"
                else:
                    try:
                        im = Image.open(io.BytesIO(content))
                        im.load()
                        return content
                    except Exception as e:
                        last_err = f"corrupt/truncated image ({e})"
        except requests.RequestException as e:
            last_err = str(e)
        time.sleep(RETRY_SLEEP * attempt)
    log(f"    FAILED after {IMAGE_RETRIES} tries: {url}  ({last_err})")
    return None


# ===================== DISCOVERY =====================

TITLE_RE = re.compile(r'<title>([^<]*)</title>', re.IGNORECASE)
OG_SITE_NAME_RE = re.compile(
    r'property=["\']og:(?:site_name|title)["\']\s+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_NAME_NOISE_WORDS = [
    "daily", "ausaf", "e-paper", "epaper", "e paper", "newspaper", "today",
    "online", "urdu", "read", "edition", "news",
]


def clean_edition_name(raw):
    if not raw:
        return None
    text = raw
    for sep in ["|", "-", "\u2013", "\u2014", ":"]:
        text = text.replace(sep, " ")
    words = text.split()
    kept = [w for w in words if w.lower().strip(",.") not in _NAME_NOISE_WORDS]
    cleaned = " ".join(kept).strip()
    if not cleaned or len(cleaned) > 30 or len(cleaned) < 2:
        return None
    return cleaned.title().replace(" ", "_")


def load_editions_cache():
    try:
        with open(EDITIONS_CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        age_hours = (time.time() - data.get("saved_at", 0)) / 3600.0
        if age_hours > EDITIONS_CACHE_HOURS:
            return None
        return {int(sid): name for sid, name in data.get("editions", {}).items()}
    except (FileNotFoundError, json.JSONDecodeError, ValueError, KeyError):
        return None


def save_editions_cache(editions):
    try:
        with open(EDITIONS_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"saved_at": time.time(),
                       "editions": {str(k): v for k, v in editions.items()}}, f)
    except OSError:
        pass


def discover_editions(session, force=False):
    if not force:
        cached = load_editions_cache()
        if cached:
            log(f"Editions cache se load ho gaye ({len(cached)} editions): "
                f"{', '.join(f'{v}({k})' for k, v in cached.items())}")
            return cached

    station_ids = set()

    r = http_get(session, BASE + "/")
    if r is not None:
        text = unescape_slashes(r.text)
        for m in STATIONISH_LINK_RE.findall(text):
            qs = parse_qs(urlsplit(unescape_slashes(m)).query)
            if "station_id" in qs:
                station_ids.add(int(qs["station_id"][0]))

    if not station_ids:
        log("Homepage se station_ids nahi milay, 1-25 individually probe kar rahe hain...")
        date_str = today_pkt_str()

        def probe(sid):
            url = f"{BASE}/page?station_id={sid}&date={date_str}"
            rr = http_get(session, url)
            if rr is not None and extract_full_image_url(rr.text):
                return sid
            return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            for sid in ex.map(probe, STATION_PROBE_RANGE):
                if sid is not None:
                    station_ids.add(sid)
                    log(f"  station_id={sid}: valid edition mili.")

    if not station_ids:
        return {}

    log(f"{len(station_ids)} station_id mile. Har ek ka naam maloom kar rahe hain...")

    date_str = today_pkt_str()

    def get_name(sid):
        url = f"{BASE}/page?station_id={sid}&date={date_str}"
        rr = http_get(session, url)
        name = None
        if rr is not None:
            text = unescape_slashes(rr.text)
            m = TITLE_RE.search(text)
            candidate = m.group(1).strip() if m else None
            if not candidate:
                m = OG_SITE_NAME_RE.search(text)
                candidate = m.group(1).strip() if m else None
            name = clean_edition_name(candidate)
        return sid, name

    editions = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        for sid, name in ex.map(get_name, sorted(station_ids)):
            editions[sid] = name or f"Station_{sid}"

    # Force include manual names
    for sid, manual_name in MANUAL_EDITION_NAMES.items():
        if manual_name and sid in editions:
            editions[sid] = manual_name.title().replace(" ", "_")

    log(f"Editions: {', '.join(f'{v}({k})' for k, v in editions.items())}")
    save_editions_cache(editions)
    return editions


def discover_pages(session, station_id, date_str, page1_html, page1_img_url):
    text = unescape_slashes(page1_html)
    ordered_values = {}

    for m in STATIONISH_LINK_RE.findall(text):
        full = unescape_slashes(m)
        qs = parse_qs(urlsplit(full).query)
        if "station_id" not in qs or int(qs["station_id"][0]) != station_id:
            continue
        for key, vals in qs.items():
            if key in ("station_id", "date"):
                continue
            for v in vals:
                if v.isdigit():
                    lst = ordered_values.setdefault(key, [])
                    if v not in lst:
                        lst.append(v)

    if ordered_values:
        best_key = max(ordered_values, key=lambda k: len(ordered_values[k]))
        values = ordered_values[best_key]
        log(f"    Pagination param mila: '{best_key}' -> {len(values)} pages")

        page_urls = []
        if "1" in values:
            for v in values:
                page_urls.append(f"{BASE}/page?station_id={station_id}&date={date_str}&{best_key}={v}")
        else:
            page_urls.append(f"{BASE}/page?station_id={station_id}&date={date_str}")
            for v in values:
                page_urls.append(f"{BASE}/page?station_id={station_id}&date={date_str}&{best_key}={v}")
        return page_urls

    log("    HTML mein pagination link nahi mila, common URL patterns guess kar rahe hain...")
    page1_default_url = f"{BASE}/page?station_id={station_id}&date={date_str}"
    page1_content = download_and_verify_image(session, page1_img_url)
    seen_hashes = set()
    if page1_content:
        seen_hashes.add(hashlib.sha256(page1_content).hexdigest())

    for param in FALLBACK_PAGE_PARAMS:
        found_any = False
        confirmed = [page1_default_url]
        local_hashes = set(seen_hashes)
        for n in range(2, MAX_PAGES_FALLBACK + 1):
            url = f"{BASE}/page?station_id={station_id}&date={date_str}&{param}={n}"
            r = http_get(session, url)
            if r is None:
                break
            img_url = extract_full_image_url(r.text)
            if img_url is None:
                break
            content = download_and_verify_image(session, img_url)
            if content is None:
                break
            h = hashlib.sha256(content).hexdigest()
            if h in local_hashes:
                break
            local_hashes.add(h)
            confirmed.append(url)
            found_any = True

        if found_any:
            log(f"    '{param}' param se {len(confirmed)} pages mil gaye.")
            return confirmed

    log("    Koi pagination pattern kaam nahi aaya - sirf page 1 milegi.")
    return [page1_default_url]


# ===================== DOWNLOAD =====================

def process_edition(edition_name, station_id, outdir, keep_images):
    log(f"\n==> {edition_name} (station_id={station_id}): page 1 fetch kar rahe hain...")
    session = make_session()
    date_str = today_pkt_str()

    page1_url = f"{BASE}/page?station_id={station_id}&date={date_str}"
    r = http_get(session, page1_url)
    if r is None:
        log(f"==> {edition_name}: page 1 hi fetch nahi hui, skip.")
        return None

    page1_img_url = extract_full_image_url(r.text)
    if page1_img_url is None:
        log(f"==> {edition_name}: image URL nahi mili -- --debug-dump {station_id} chalaen.")
        return None

    page_urls = discover_pages(session, station_id, date_str, r.text, page1_img_url)
    log(f"==> {edition_name}: {len(page_urls)} pages mile.")

    def worker(idx_url):
        idx, url = idx_url
        rr = http_get(session, url)
        img_url = extract_full_image_url(rr.text) if rr is not None else None
        if img_url is None:
            log(f"    [{edition_name}] page {idx+1}: image URL nahi mili (skip)")
            return idx, None, None
        content = download_and_verify_image(session, img_url)

        if content is None:
            log(f"    [{edition_name}] page {idx+1}: download fail, fresh refetch...")
            time.sleep(2.0)
            rr2 = http_get(session, url)
            img_url2 = extract_full_image_url(rr2.text) if rr2 is not None else None
            if img_url2 is not None:
                img_url = img_url2
                content = download_and_verify_image(session, img_url)

        if content is None:
            log(f"    [{edition_name}] page {idx+1}: download FAIL (skip)")
        else:
            log(f"    [{edition_name}] page {idx+1}/{len(page_urls)}: OK ({len(content)} bytes)")
        return idx, content, img_url

    downloaded = [None] * len(page_urls)
    with concurrent.futures.ThreadPoolExecutor(max_workers=THREADS_PER_EDITION) as ex:
        for idx, content, _img_url in ex.map(worker, enumerate(page_urls)):
            downloaded[idx] = content

    seen_hashes = set()
    for idx in range(len(page_urls)):
        content = downloaded[idx]
        if content is None:
            continue
        h = hashlib.sha256(content).hexdigest()
        if h in seen_hashes:
            log(f"    [{edition_name}] page {idx+1}: duplicate content, dropping.")
            downloaded[idx] = None
        else:
            seen_hashes.add(h)

    # Memory-safe: sirf EK page ek waqt mein decode hota hai (agar valid
    # RGB JPEG already hai to bilkul decode nahi hota, bytes seedha PDF
    # mein wrap ho jaate hain). Pehle poori list RGB PIL Image objects
    # se bharti thi -- 20-30 high-res pages ke liye ye "memory quota
    # exceeded" crash ki sabse badi wajah thi.
    jpeg_pages = []
    if keep_images:
        tmp_dir = os.path.join(outdir, "_raw", f"{edition_name}_{date_str}")
        os.makedirs(tmp_dir, exist_ok=True)

    for idx, content in enumerate(downloaded):
        if content is None:
            continue
        try:
            im = Image.open(io.BytesIO(content))
            im.load()
            if im.format == "JPEG" and im.mode == "RGB":
                jpeg_bytes = content
            else:
                im = im.convert("RGB")
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=95)
                jpeg_bytes = buf.getvalue()
            if keep_images:
                with open(os.path.join(tmp_dir, f"{idx+1:02d}.jpg"), "wb") as fh:
                    fh.write(jpeg_bytes)
        except Exception as e:
            log(f"    [{edition_name}] page {idx+1}: open error, skip: {e}")
            continue
        jpeg_pages.append(jpeg_bytes)

    if not jpeg_pages:
        log(f"==> {edition_name}: koi bhi page download nahi hua, PDF skip.")
        return None

    os.makedirs(outdir, exist_ok=True)
    pretty_date = datetime.now(PKT).strftime("%d%B")
    pdf_name = f"Ausaf {edition_name.replace('_', ' ')} {pretty_date}.pdf"
    pdf_path = os.path.join(outdir, pdf_name)
    with open(pdf_path, "wb") as f:
        f.write(img2pdf.convert(jpeg_pages))
    log(f"==> {edition_name}: PDF ban gayi -> {pdf_path}  ({len(jpeg_pages)}/{len(page_urls)} pages)")
    jpeg_pages = None
    gc.collect()
    return pdf_path


def main():
    parser = argparse.ArgumentParser(description="Daily Ausaf Epaper auto downloader -> PDF")
    parser.add_argument("--editions", nargs="+", default=None,
                         help="Sirf in editions ko download karein.")
    parser.add_argument("--outdir", default=os.path.join(os.getcwd(), "Ausaf_Epaper_PDFs"),
                         help="PDF output folder")
    parser.add_argument("--keep-images", action="store_true",
                         help="Har page ki alag JPG bhi rakhein.")
    parser.add_argument("--list-editions", action="store_true",
                         help="Sirf editions discover kar ke dikhaye.")
    parser.add_argument("--debug-dump", metavar="STATION_ID", default=None,
                         help="Debug mode: station_id ki HTML save karega.")
    parser.add_argument("--rediscover", action="store_true",
                         help="Editions cache ignore karein.")
    args = parser.parse_args()

    session = make_session()

    if args.debug_dump:
        sid = int(args.debug_dump)
        url = f"{BASE}/page?station_id={sid}&date={today_pkt_str()}"
        r = http_get(session, url)
        if r is None:
            sys.exit(f"Page fetch nahi ho saka: {url}")
        with open("ausaf_debug_page.html", "w", encoding="utf-8") as f:
            f.write(r.text)
        found = extract_full_image_url(r.text)
        log(f"Raw HTML save: ausaf_debug_page.html ({len(r.text)} chars)")
        log(f"Extractor result: {found or 'KUCH NAHI MILA'}")
        return

    log("Editions discover kar rahe hain...")
    editions = discover_editions(session, force=args.rediscover)
    if not editions:
        sys.exit("Koi edition nahi mila.")

    if EXCLUDE_STATIONS:
        editions = {sid: name for sid, name in editions.items() if sid not in EXCLUDE_STATIONS}
        if not editions:
            sys.exit("EXCLUDE_STATIONS ke baad koi edition nahi bacha.")

    # Force include stations
    for sid in FORCE_INCLUDE_STATIONS:
        if sid in EXCLUDE_STATIONS:
            continue
        if sid not in editions:
            log(f"station_id={sid}: force-include kar rahe hain.")
            editions[sid] = MANUAL_EDITION_NAMES.get(sid) or f"Station_{sid}"

    for sid, manual_name in MANUAL_EDITION_NAMES.items():
        if manual_name and sid in editions:
            editions[sid] = manual_name.title().replace(" ", "_")

    edition_names = {sid: name for sid, name in editions.items()}

    if args.list_editions:
        log("Mile hue editions:")
        for sid, name in edition_names.items():
            log(f"  {name}  (station_id={sid})")
        return

    if args.editions:
        chosen = {sid: name for sid, name in edition_names.items() if name in args.editions}
        if not chosen:
            sys.exit(f"Diye gaye editions nahi milay. Available: {list(edition_names.values())}")
    else:
        chosen = edition_names

    os.makedirs(args.outdir, exist_ok=True)
    log(f"Output folder: {args.outdir}")
    log(f"Tareekh: {today_pkt_str()}")
    log(f"Editions ({len(chosen)}): {', '.join(chosen.values())}")

    results = {}
    for i, (sid, name) in enumerate(chosen.items()):
        if i > 0:
            time.sleep(EDITION_DELAY)
        try:
            path = process_edition(name, sid, args.outdir, args.keep_images)
            results[name] = path
        except Exception as e:
            log(f"==> {name}: ERROR -> {e}")
            results[name] = None

    log("")
    log("===================== SUMMARY =====================")
    ok = 0
    for name, path in results.items():
        status = path if path else "FAILED"
        log(f"{name:16s} -> {status}")
        if path:
            ok += 1
    log(f"Total: {ok}/{len(results)} editions successful.")
    log("=====================================================")


if __name__ == "__main__":
    main()
