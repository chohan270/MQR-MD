import gc
import requests
import img2pdf
from PIL import Image
from io import BytesIO
from datetime import datetime
import os

# ===== TODAY DATE =====
today = datetime.now()
DATE_STR = f"{today.month}-{today.day}-{today.year}"  # example: 7-12-2026
# Pretty date for the OUTPUT filename only (e.g. "26August") -- keeps names
# human-readable AND, critically, prefixed with "TheNews" below so the file
# never collides with Jang's (or anyone else's) PDF of the same edition/date.
PRETTY_DATE = today.strftime("%d%B")


def _page_to_jpeg_bytes(raw_bytes):
    """
    Ek dafa mein sirf EK page RAM mein decode hota hai (memory-safe --
    pehle poori list RGB PIL Image objects se bhar jaati thi, jo 25-30
    high-res pages ke liye 500MB+ RAM le leta tha aur "memory quota
    exceeded" crash deta tha). Agar image already ek plain RGB JPEG hai
    to bina re-encode kiye seedha wapis kar deta hai (fastest, no
    decode at all).
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
        return None

# ===== EDITIONS =====
# The News sirf 3 shehron se print hoti hai (Jang ki tarah 5 nahi)
EDITIONS = {
    "Karachi": "karachi",
    "Lahore": "lahore",
    "Rawalpindi": "pindi"
}

BASE_URL = "https://e.thenews.pk/static_pages/{date}/{edition}/mainpage/page"
MAX_PAGES = 30

headers = {
    "User-Agent": "Mozilla/5.0"
}

os.makedirs("thenews_pdfs", exist_ok=True)

for name, edition in EDITIONS.items():
    print(f"\n📘 {name} edition start")
    jpeg_pages = []  # compressed JPEG bytes only -- NOT decoded PIL images

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
                    page_bytes = _page_to_jpeg_bytes(r.content)
                    if page_bytes is None:
                        continue
                    jpeg_pages.append(page_bytes)
                    print(f"✅ Page {page} add ho gaya ({ext})")
                    mila = True
                    break
            except:
                pass

        if not mila:
            print(f"❌ {name} page {page} nahi mila, edition complete")
            break

    if jpeg_pages:
        # "TheNews" prefix + edition + pretty date -> e.g.
        # "TheNews Lahore 26August.pdf". Prefix ki wajah se ye kabhi bhi
        # Jang ki usi edition-naam wali PDF se collide/duplicate nahi hoti
        # (pehle dono "Lahore_<date>.pdf" bante thay -- isi se TheNews
        # "already sent" samajh kar skip/duplicate ho jaata tha).
        pdf_path = f"thenews_pdfs/TheNews {name} {PRETTY_DATE}.pdf"
        with open(pdf_path, "wb") as f:
            f.write(img2pdf.convert(jpeg_pages))
        print(f"📕 PDF ban gayi: {pdf_path}")
    else:
        print(f"⚠️ {name} ki koi page nahi mila")

    jpeg_pages = None
    gc.collect()
