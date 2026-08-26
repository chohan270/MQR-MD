import requests
from PIL import Image
import img2pdf
import gc
from io import BytesIO
from datetime import datetime
import os
from concurrent.futures import ThreadPoolExecutor

# ===== TODAY DATE =====

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

today = datetime.now()
DAY = today.strftime("%d")
MONTH_NUM = today.strftime("%m")
YEAR = str(today.year)
MONTH_SHORT = today.strftime("%b")

# ===== EDITIONS & LINKS =====
# All editions use a double slash before "images" (matches live site URLs)
BASE = "https://ummat.net/cdn/{year}/{month}/{day}//images/{filename}"

editions = {
    "Karachi": lambda page: f"page-{page}.jpg",
    "Pindi": lambda page: f"page{page}.jpg",
    "Peshawer": lambda page: f"page{page:02d}.jpg",   # matches page01.jpg, page02.jpg ... as given
    "Hyderabad": lambda page: f"page_{page}.jpg",
}

MAX_PAGES = 30
SAVE_FOLDER = "Ummat_PDFs"
os.makedirs(SAVE_FOLDER, exist_ok=True)

# ===== Function =====
def download_edition(edition, filename_fn):
    print(f"\n📖 Downloading {edition} newspaper...")
    images = []
    found_any = False

    for page in range(1, MAX_PAGES + 1):
        filename = filename_fn(page)
        url = BASE.format(year=YEAR, month=MONTH_NUM, day=DAY, filename=filename)
        try:
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                break

            img = _page_to_jpeg_bytes(r.content)
            images.append(img)
            found_any = True
            print(f"{edition} - Page {page} added")

        except:
            break

    if found_any:
        pdf_name = f"Ummat {edition} {DAY}{MONTH_SHORT}.pdf"
        pdf_path = os.path.join(SAVE_FOLDER, pdf_name)
        with open(pdf_path, "wb") as _f:
            _f.write(img2pdf.convert(images))
        print(f"✅ {edition} PDF ready: {pdf_path}")
    else:
        print(f"❌ {edition} pages not found")

# ===== Run all editions =====
with ThreadPoolExecutor(max_workers=4) as executor:
    for edition, filename_fn in editions.items():
        executor.submit(download_edition, edition, filename_fn)
