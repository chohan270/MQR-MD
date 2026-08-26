import re
import sys
import os
import time
from io import BytesIO
from datetime import datetime

import gc
import requests
import img2pdf
from PIL import Image

# curl_cffi impersonates a real browser's TLS/HTTP2 fingerprint, which
# regular `requests` can't do — this is usually why Cloudflare returns 403
# even when the User-Agent header looks correct.
try:
    from curl_cffi import requests as cf_requests
except ImportError:
    cf_requests = None


def _page_to_jpeg_bytes(raw_bytes):
    """
    Memory-safe: sirf EK page RAM mein decode hota hai (poori list decode
    RGB PIL Image objects se bhar kar RAM mein rakhna hi "memory quota
    exceeded" crash ki sabse badi wajah thi). Agar image already ek plain
    RGB JPEG hai to bina re-encode kiye seedha wapis kar deta hai.
    """
    try:
        img = Image.open(BytesIO(raw_bytes))
        if img.format == "JPEG" and img.mode == "RGB":
            img.close()
            return raw_bytes
        img = img.convert("RGB")
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=92)
        img.close()
        return buf.getvalue()
    except Exception:
        return raw_bytes


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 13; Mobile) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Mobile Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Referer": "https://epaper.dawn.com/",
}


def make_session():
    # ===== Proxy support (sirf agar zaroorat pade) =====
    # Agar Dawn geo-block ya IP-block kare, to Termux/Heroku dono jagah
    # bina code chhede ye env variables set kar ke proxy laga sakte hain:
    #
    #   export DAWN_PROXY="http://user:pass@proxy-host:port"
    #
    # Ya alag http/https proxy chahiye ho to:
    #
    #   export DAWN_PROXY_HTTP="http://user:pass@proxy-host:port"
    #   export DAWN_PROXY_HTTPS="http://user:pass@proxy-host:port"
    #
    # Kuch nahi set kiya to script bilkul normal (bina proxy) chalegi.
    proxy_url = os.environ.get("DAWN_PROXY")
    proxies = None
    if proxy_url:
        proxies = {"http": proxy_url, "https": proxy_url}
    elif os.environ.get("DAWN_PROXY_HTTP") or os.environ.get("DAWN_PROXY_HTTPS"):
        proxies = {
            "http": os.environ.get("DAWN_PROXY_HTTP", ""),
            "https": os.environ.get("DAWN_PROXY_HTTPS", ""),
        }

    if cf_requests:
        try:
            s = cf_requests.Session(impersonate="chrome124")
            s.headers.update(HEADERS)
            if proxies:
                s.proxies.update(proxies)
                print("🌐 Proxy laga di gayi hai (curl_cffi session).")
            return s
        except Exception as e:
            print("curl_cffi session bana nahi (fallback to requests):", e)

    s = requests.Session()
    s.headers.update(HEADERS)
    if proxies:
        s.proxies.update(proxies)
        print("🌐 Proxy laga di gayi hai (requests session).")
    return s


SESSION = make_session()
_WARMED_UP = False


def warm_up():
    """Homepage visit karo pehle taake Cloudflare cookies/session mil jayein."""
    global _WARMED_UP
    if _WARMED_UP:
        return
    try:
        SESSION.get("https://epaper.dawn.com/", timeout=30)
    except Exception:
        pass
    _WARMED_UP = True


def safe_get(url, tries=3):
    warm_up()
    for i in range(tries):
        try:
            r = SESSION.get(url, timeout=30)
            if r.status_code == 200:
                return r
            print(f"HTTP {r.status_code}, retry {i+1}/{tries}")
        except Exception as e:
            print("Connection error:", e)

        time.sleep(3)

    return None


def get_today_date_str():
    today = datetime.now()
    return f"{today.day:02d}_{today.month:02d}_{today.year}"


def get_page_list(date_str):
    listing_url = f"https://epaper.dawn.com/?page={date_str}_001"
    print("Fetching page list:", listing_url)

    r = safe_get(listing_url)

    if not r:
        raise RuntimeError(
            "Dawn listing page open nahi hui. Internet ya website block check karein."
        )

    html = r.text

    matches = re.findall(
        r'\?page=' + re.escape(date_str) + r'_(\d+)',
        html
    )

    seen = []
    for m in matches:
        if m not in seen:
            seen.append(m)

    if not seen:
        raise RuntimeError(
            "Page numbers nahi mile. Date available nahi ho sakti."
        )

    return seen


def download_dawn_epaper(date_str=None):
    if date_str is None:
        date_str = get_today_date_str()

    day, month, year = date_str.split("_")

    page_numbers = get_page_list(date_str)

    print(
        f"📄 Total {len(page_numbers)} pages mili: "
        f"{', '.join(page_numbers)}\n"
    )

    pdf_images = []

    os.makedirs("dawn_pages", exist_ok=True)

    for pnum in page_numbers:

        img_url = (
            f"https://e.dawn.com/{year}/{month}/{day}/pages/"
            f"{date_str}_{pnum}.jpg"
        )

        print("Downloading:", img_url)

        r = safe_get(img_url)

        if r:
            try:
                jpeg_bytes = _page_to_jpeg_bytes(r.content)
                pdf_images.append(jpeg_bytes)

                with open(f"dawn_pages/{pnum}.jpg", "wb") as _pf:
                    _pf.write(jpeg_bytes)
                print(f"✅ Page {pnum} saved")

            except Exception as e:
                print(f"❌ Image error {pnum}: {e}")

        else:
            print(f"❌ Page {pnum} download failed")


    if pdf_images:

        os.makedirs("dawn_pdfs", exist_ok=True)

        pdf_path = f"dawn_pdfs/Dawn_{date_str}.pdf"

        with open(pdf_path, "wb") as _f:
            _f.write(img2pdf.convert(pdf_images))

        print("\n📕 PDF ready:", pdf_path)

    else:
        print("\n⚠️ Koi page download nahi hui.")


if __name__ == "__main__":

    if len(sys.argv) > 1:

        arg = sys.argv[1]

        m = re.search(r'(\d{2}_\d{2}_\d{4})', arg)

        date_arg = m.group(1) if m else arg

        download_dawn_epaper(date_arg)

    else:
        download_dawn_epaper()
