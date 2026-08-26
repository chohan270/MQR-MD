import requests
from PIL import Image
import img2pdf
import gc
from io import BytesIO
from datetime import datetime
import os

# ===== TODAY DATE (M-D-YYYY) =====

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
DATE_STR = f"{today.month}-{today.day}-{today.year}"  # example: 7-12-2026

# ===== EDITIONS =====
EDITIONS = {
    "Lahore": "lahore",
    "Karachi": "karachi",
    "Rawalpindi": "pindi",
    "Multan": "multan",
    "Quetta": "quetta"
}

# Sunday Magazine ki images bhi "mainpage" folder ke andar hoti hain,
# bas filename "sunday-magazine-pageN.jpg" hota hai (normal "pageN.jpg" nahi)
BASE_URL = "https://e.jang.com.pk/static_pages/{date}/{edition}/mainpage/sunday-magazine-page"
MAX_PAGES = 20  # Sunday magazine usually 15 pages tak hoti hai, thora buffer rakha hai

headers = {
    "User-Agent": "Mozilla/5.0"
}

os.makedirs("jang_sunday_magazine_pdfs", exist_ok=True)

for name, edition in EDITIONS.items():
    print(f"\n📘 {name} Sunday Magazine start")
    pdf_images = []

    for page in range(1, MAX_PAGES + 1):
        mila = False

        for ext in ["jpg", "png"]:
            url = BASE_URL.format(
                date=DATE_STR,
                edition=edition
            ) + f"{page}.{ext}"

            print("Try:", url)

            try:
                r = requests.get(url, headers=headers, timeout=10)

                if r.status_code == 200:
                    img = _page_to_jpeg_bytes(r.content)
                    pdf_images.append(img)
                    print(f"✅ Page {page} add ho gaya ({ext})")
                    mila = True
                    break
            except:
                pass

        if not mila:
            print(f"❌ {name} Sunday Magazine page {page} nahi mila, edition complete")
            break

    if pdf_images:
        pdf_path = f"jang_sunday_magazine_pdfs/{name}_SundayMagazine_{DATE_STR}.pdf"
        with open(pdf_path, "wb") as _f:
            _f.write(img2pdf.convert(pdf_images))
        print(f"📕 PDF ban gayi: {pdf_path}")
    else:
        print(f"⚠️ {name} Sunday Magazine ki koi page nahi mili")
