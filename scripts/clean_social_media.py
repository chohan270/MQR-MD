#!/usr/bin/env python3
"""
Action Karachi PDF cleaner  --  FULL SCAN + LOSSLESS REMOVAL
============================================================
Ye script PDF ke andar (content stream) ka har text scan karti hai aur
"0342-4938217" number (poora ya adhoora: 0342 / 4938217 / 217...) aur
"Social Media Pakistan" jahan bhi likha ho usay jad se nikaal deti hai:

  * kisi bhi jagah:   center, top-left, top-right, bottom, side, corner
  * kisi bhi colour:  kala, safed, gray, rang-birangi
  * kisi bhi opacity / rotation / font size / invisible text
  * patti ke andar ho ya patti se bahar alag likha ho
  * 10 baar overlap kiya hua "pakka" vector watermark bhi
  * nested Form XObject ke andar chhupa hua text bhi (recursive scan)
  * annotations / stamps / watermark annotations bhi

Koi box ya white shape nahi lagti, newspaper ka text/photo touch nahi hota.
Patti (rectangle) ko edge se detect kar ke hata deti hai aur page crop karti hai.
Jin pages me newspaper layer nahi hoti (kale Social Media Pakistan rules/ad pages)
wo drop ho jate hain.

NOTE: Agar watermark kisi image ke pixels me "baked" ho (scan hua hua), to usay
bina quality kharab kiye nikaalna mumkin nahi -- script us page par warning dikha
kar page waisa hi rakhti hai (aap ki is PDF me watermark vector hai, is liye perfect hat jata hai).

Install:   pip install pypdf
Use:       python clean_action_pdf.py
           python clean_action_pdf.py input.pdf
           python clean_action_pdf.py input.pdf "Action Karachi 10Oct.pdf"
Options:   --extra "WORD"      aur koi lafz/number blacklist me daalo (kai baar de sakte ho)
           --keep-ad-pages     kale ad/rules pages drop na karo
           --debug             har cheez ki detail print karo
"""

import argparse
import json
import re
import sys

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ContentStream, DictionaryObject, NameObject, RectangleObject, ArrayObject,
    TextStringObject, ByteStringObject,
)

import mw

# ---------------------------------------------------------------- SETTINGS --
INPUT_PDF = "9_Oct_Action_Karachi.pdf"
OUTPUT_PDF = "Action Karachi 9Oct.pdf"

# Lafz/number jo har haal me hat'ne chahiye. Match normalize ho kar hota hai:
# lowercase + sirf letters/digits (space, dash, dot, bracket sab ignore).
BLACKLIST = [
    "03424938217",          # poora number
    "4938217",              # number ka main hissa
    "0342",                 # code
    "38217",                # adhoora hissa
    "socialmediapakistan",  # naam
    "socialmedia",
    "whatsappgroup",
]
# Chhote tukdon (jaise sirf "217") ke liye sirf tab match karo jab poora text
# (BT..ET) isi se milta julta ho:
SHORT_ONLY_IF_WHOLE = ["217", "pakistan"]

# Patti (filled rectangle) detection
STRIP_MAX_FRAC = 0.12      # patti page ke 12% se patli ho
STRIP_MIN_SPAN = 0.85      # aur page ki 85% chaudai/lambai cover kare
EDGE_TOL = 2.5             # page edge se kitna door tak "touching" maane (pt)
PAGE_XOBJECT_PREFIX = "/EmbeddedPdfPage"
# ----------------------------------------------------------------------------

SHOW_OPS = {b"Tj", b"TJ", b"'", b'"'}
PAINT_OPS = {b"f", b"F", b"f*", b"S", b"s", b"B", b"B*", b"b", b"b*", b"sh",
             b"Do", b"BI", b"EI", b"ID"} | SHOW_OPS
FILL_OPS = {b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"}

DEBUG = False


def dbg(*a):
    if DEBUG:
        print("   [dbg]", *a)


def norm(s):
    return re.sub(r"[^0-9a-z\u0600-\u06ff]", "", s.lower())


class Matcher:
    def __init__(self, extra=None):
        self.words = [norm(w) for w in BLACKLIST + list(extra or []) if norm(w)]
        self.short = [norm(w) for w in SHORT_ONLY_IF_WHOLE]
        self.detected = set()

    def hit(self, text, whole=True):
        t = norm(text)
        if not t:
            return False
        for w in self.words:
            if w in t:
                if any(char.isdigit() for char in w):
                    self.detected.add("Phone-number watermark")
                elif "socialmedia" in w:
                    self.detected.add("Social Media Pakistan watermark")
                else:
                    self.detected.add("WhatsApp/group-promotion watermark")
                return True
        if whole:
            for w in self.short:
                if t == w or (len(t) <= len(w) + 3 and w in t):
                    self.detected.add("Short phone/text watermark fragment")
                    return True
        return False


# ------------------------------------------------------ font -> unicode map --
class FontDecoder:
    """Bytes ko unicode text me badalta hai (ToUnicode CMap use karta hai)."""

    def __init__(self, font):
        self.map = {}
        self.codelen = 1
        try:
            font = font.get_object()
            if "/ToUnicode" in font:
                self._parse(font["/ToUnicode"].get_object().get_data().decode("latin1"))
            sub = str(font.get("/Subtype", ""))
            if sub == "/Type0":
                self.codelen = 2
        except Exception as e:  # noqa
            dbg("font decode init failed", e)

    def _parse(self, s):
        def h2u(h):
            try:
                return bytes.fromhex(h).decode("utf-16-be", "ignore")
            except Exception:
                return ""
        for block in re.findall(r"beginbfchar(.*?)endbfchar", s, re.S):
            for src, dst in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
                self.map[int(src, 16)] = h2u(dst)
                self.codelen = max(self.codelen, len(src) // 2)
        for block in re.findall(r"beginbfrange(.*?)endbfrange", s, re.S):
            for a, b, c in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", block):
                lo, hi = int(a, 16), int(b, 16)
                base = h2u(c)
                if base and hi - lo < 65536:
                    for i in range(hi - lo + 1):
                        self.map[lo + i] = base[:-1] + chr(ord(base[-1]) + i)
                self.codelen = max(self.codelen, len(a) // 2)

    def decode(self, raw):
        """Return list of candidate decodings; matcher checks all."""
        if isinstance(raw, (TextStringObject,)):
            raw = str(raw).encode("latin1", "ignore")
        elif not isinstance(raw, (bytes, bytearray)):
            raw = bytes(raw)
        outs = [raw.decode("latin1", "ignore")]
        if len(raw) % 2 == 0:
            outs.append(raw.decode("utf-16-be", "ignore"))
        if self.map:
            n = self.codelen
            s = ""
            for i in range(0, len(raw), n):
                code = int.from_bytes(raw[i:i + n], "big")
                s += self.map.get(code, "")
            outs.append(s)
        return outs


def show_text_candidates(operands, op, dec):
    """Ek show-text operator ke saare mumkina text decodings (list of str)."""
    parts = []
    if op == b"TJ":
        items = [x for x in operands[0] if isinstance(x, (TextStringObject, ByteStringObject, bytes))]
        if not items:
            return [""]
        per = [dec.decode(x) for x in items]
        k = max(len(p) for p in per)
        for j in range(k):
            parts.append("".join(p[j] if j < len(p) else p[-1] for p in per))
    elif op == b'"':
        parts = dec.decode(operands[-1])
    else:
        parts = dec.decode(operands[0])
    return parts


# --------------------------------------------------------- matrix / geometry --
def mmul(a, b):
    return (a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
            a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
            a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5])


def apply(m, x, y):
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def block_fill_bbox(block):
    """Agar block sirf filled path hai to uska bbox (x0,y0,x1,y1) lautao."""
    m = (1, 0, 0, 1, 0, 0)
    pts, filled = [], False
    for operands, op in block:
        if op == b"cm":
            m = mmul(tuple(float(v) for v in operands), m)
        elif op == b"m" or op == b"l":
            pts.append(apply(m, float(operands[0]), float(operands[1])))
        elif op == b"re":
            x, y, w, h = [float(v) for v in operands]
            for px, py in ((x, y), (x + w, y), (x, y + h), (x + w, y + h)):
                pts.append(apply(m, px, py))
        elif op in FILL_OPS:
            filled = True
    if not pts or not filled:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def top_level_blocks(ops):
    blocks, cur, depth = [], [], 0
    for operands, op in ops:
        if op == b"q":
            depth += 1
        cur.append((operands, op))
        if op == b"Q":
            depth -= 1
            if depth <= 0:
                blocks.append(cur)
                cur, depth = [], 0
    if cur:
        blocks.append(cur)
    return blocks


def has_paint(block):
    return any(op in PAINT_OPS for _, op in block)


# ------------------------------------------------------- content stream scan --
def scrub_ops(ops, resources, matcher, stats):
    """
    Text-showing ops ko BT..ET ke hisaab se check karo; match ho to hata do.
    Return: new ops list.
    """
    fonts = {}
    fres = resources.get("/Font") if resources else None
    if fres is not None:
        fres = fres.get_object()
        for k in fres:
            fonts[str(k)] = FontDecoder(fres[k])

    cur_font = FontDecoder(DictionaryObject())
    out = list(ops)
    remove_idx = set()

    in_bt, bt_ops = False, []   # bt_ops: (index, [candidate strings])
    bt_start = None

    def flush(end_idx):
        nonlocal bt_ops
        if not bt_ops:
            return
        ncand = max(len(c) for _, c in bt_ops)
        joined = []
        for j in range(ncand):
            joined.append("".join(c[j] if j < len(c) else c[-1] for _, c in bt_ops if c))
        whole_hit = any(matcher.hit(t, whole=True) for t in joined)
        if whole_hit:
            for idx, c in bt_ops:
                remove_idx.add(idx)
            stats["text_removed"] += len(bt_ops)
            dbg("removed text object:", [t[:40] for t in joined][:2])
        else:
            for idx, c in bt_ops:
                if any(matcher.hit(t, whole=False) for t in c):
                    remove_idx.add(idx)
                    stats["text_removed"] += 1
                    dbg("removed text op:", [t[:40] for t in c][:2])
        bt_ops = []

    for i, (operands, op) in enumerate(ops):
        if op == b"Tf":
            cur_font = fonts.get(str(operands[0]), cur_font)
        elif op == b"BT":
            in_bt, bt_ops = True, []
        elif op == b"ET":
            flush(i)
            in_bt = False
        elif op in SHOW_OPS:
            try:
                cands = show_text_candidates(operands, op, cur_font)
            except Exception as e:  # noqa
                cands = [""]
                dbg("decode fail", e)
            if in_bt:
                bt_ops.append((i, cands))
            else:
                if any(matcher.hit(t, whole=True) for t in cands):
                    remove_idx.add(i)
                    stats["text_removed"] += 1
    if in_bt:
        flush(len(ops))

    return [x for k, x in enumerate(out) if k not in remove_idx]


def write_stream(obj, data):
    obj = obj.get_object()
    try:
        obj.set_data(data)
    except Exception:
        from pypdf.generic import DecodedStreamObject
        new = DecodedStreamObject()
        new.set_data(data)
        for k, v in obj.items():
            if k not in ("/Filter", "/DecodeParms", "/Length"):
                new[NameObject(k)] = v
        obj.clear()
        obj.update(new)
        obj._data = data


def scrub_form(reader, form, matcher, stats, seen, depth=0):
    """Form XObject (aur uske andar ke forms) ko recursively scan karo."""
    form = form.get_object()
    ident = id(form)
    if ident in seen or depth > 6:
        return
    seen.add(ident)
    res = form.get("/Resources")
    res = res.get_object() if res is not None else None
    if form.get("/Subtype") != "/Form":
        return
    try:
        cs = ContentStream(form, reader)
    except Exception as e:  # noqa
        dbg("form parse fail", e)
        return
    before = stats["text_removed"]
    new_ops = scrub_ops(cs.operations, res, matcher, stats)
    if stats["text_removed"] != before:
        cs.operations = new_ops
        write_stream(form, cs.get_data())
    if res is not None and "/XObject" in res:
        xo = res["/XObject"].get_object()
        for k in xo:
            scrub_form(reader, xo[k], matcher, stats, seen, depth + 1)


# ------------------------------------------------------------- annotations --
def scrub_annots(page, matcher, stats):
    if "/Annots" not in page:
        return
    keep = ArrayObject()
    for a in page["/Annots"]:
        o = a.get_object()
        text = " ".join(str(o.get(k, "")) for k in ("/Contents", "/T", "/Subj", "/RC"))
        sub = str(o.get("/Subtype", ""))
        kill = sub == "/Watermark" or matcher.hit(text, whole=False)
        if not kill and "/AP" in o:
            try:
                n = o["/AP"].get("/N")
                if n is not None:
                    data = n.get_object().get_data().decode("latin1")
                    strs = re.findall(r"<([0-9A-Fa-f]+)>\s*Tj|\(((?:\\.|[^\\)])*)\)\s*Tj", data)
                    joined = "".join(
                        (bytes.fromhex(h).decode("latin1") if h else s) for h, s in strs)
                    kill = matcher.hit(joined, whole=False)
            except Exception:
                pass
        if kill:
            stats["annots_removed"] += 1
        else:
            keep.append(a)
    page[NameObject("/Annots")] = keep


# ---------------------------------------------------------------- page level --
def main_form_name(xobjs):
    for n in xobjs:
        if str(n).startswith(PAGE_XOBJECT_PREFIX):
            return str(n)
    return None


def clean_page(reader, page, matcher, stats):
    """Return 'ok' | 'image-only' for the page (page is edited in place)."""
    mb = page.mediabox
    px0, py0, px1, py1 = float(mb.left), float(mb.bottom), float(mb.right), float(mb.top)
    W, H = px1 - px0, py1 - py0

    res = page.get("/Resources")
    res = res.get_object() if res is not None else DictionaryObject()
    xobjs = res.get("/XObject")
    xobjs = xobjs.get_object() if xobjs is not None else {}
    main = main_form_name(xobjs)

    # recursive scan of forms (newspaper layer ke andar chhupa text bhi)
    seen = set()
    for k in list(xobjs.keys()):
        scrub_form(reader, xobjs[k], matcher, stats, seen)

    scrub_annots(page, matcher, stats)

    cs = ContentStream(page.get_contents(), reader)
    ops = scrub_ops(cs.operations, res, matcher, stats)

    # --- patti / strip rectangles (edge se touching, patli, lambi) ---
    # Op-level scan: CTM track karte hue har filled path ko check karo
    PATH_OPS = {b"m", b"l", b"c", b"v", b"y", b"h", b"re"}
    ctm, stack = (1, 0, 0, 1, 0, 0), []
    path_idx, pts = [], []
    drop, crop = set(), [0.0, 0.0, 0.0, 0.0]   # crop = left,bottom,right,top
    for i, (operands, op) in enumerate(ops):
        if op == b"q":
            stack.append(ctm)
        elif op == b"Q":
            ctm = stack.pop() if stack else (1, 0, 0, 1, 0, 0)
        elif op == b"cm":
            ctm = mmul(tuple(float(v) for v in operands), ctm)
        elif op in PATH_OPS:
            path_idx.append(i)
            if op in (b"m", b"l"):
                pts.append(apply(ctm, float(operands[0]), float(operands[1])))
            elif op == b"re":
                x, y, w, h = [float(v) for v in operands]
                for qx, qy in ((x, y), (x + w, y), (x, y + h), (x + w, y + h)):
                    pts.append(apply(ctm, qx, qy))
            elif op == b"c":
                for j in (0, 2, 4):
                    pts.append(apply(ctm, float(operands[j]), float(operands[j + 1])))
        elif op in FILL_OPS or op in (b"S", b"s", b"n"):
            if op in FILL_OPS and pts:
                xs, ys = [q[0] for q in pts], [q[1] for q in pts]
                x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
                w, h = x1 - x0, y1 - y0
                hit = None
                if h <= H * STRIP_MAX_FRAC and w >= W * STRIP_MIN_SPAN:
                    if y0 <= py0 + EDGE_TOL:
                        hit = (1, y1 - py0)
                    elif y1 >= py1 - EDGE_TOL:
                        hit = (3, py1 - y0)
                if hit is None and w <= W * STRIP_MAX_FRAC and h >= H * STRIP_MIN_SPAN:
                    if x0 <= px0 + EDGE_TOL:
                        hit = (0, x1 - px0)
                    elif x1 >= px1 - EDGE_TOL:
                        hit = (2, px1 - x0)
                if hit:
                    crop[hit[0]] = max(crop[hit[0]], hit[1])
                    drop.update(path_idx)
                    drop.add(i)
                    stats["strips_removed"] += 1
            path_idx, pts = [], []
    ops = [x for k, x in enumerate(ops) if k not in drop]

    kept = [b for b in top_level_blocks(ops) if has_paint(b)]   # khali blocks hata do

    cs.operations = [op for b in kept for op in b]
    page.replace_contents(cs)

    # --- page box: newspaper layer ka exact size, warna patti ke hisaab se crop ---
    box = None
    if main is not None:
        form = xobjs[NameObject(main)].get_object()
        m = (1, 0, 0, 1, 0, 0)
        for operands, op in cs.operations:
            if op == b"cm":
                m = mmul(tuple(float(v) for v in operands), m)
            if op == b"Do" and str(operands[0]) == main:
                break
        if "/BBox" in form:
            bx0, by0, bx1, by1 = [float(v) for v in form["/BBox"]]
            c1, c2 = apply(m, bx0, by0), apply(m, bx1, by1)
            box = RectangleObject([min(c1[0], c2[0]), min(c1[1], c2[1]),
                                   max(c1[0], c2[0]), max(c1[1], c2[1])])
    if box is None and any(crop):
        box = RectangleObject([px0 + crop[0], py0 + crop[1], px1 - crop[2], py1 - crop[3]])
    if box is not None:
        for b in ("/MediaBox", "/CropBox", "/TrimBox", "/BleedBox", "/ArtBox"):
            if b in page:
                del page[b]
        page.mediabox = box
        page.cropbox = box

    # unused resources saaf (fonts/opacity states jo ab kaam ke nahi)
    used = set()
    for operands, op in cs.operations:
        if op in (b"Tf", b"gs", b"Do") and operands:
            used.add(str(operands[0]))
    for key in ("/Font", "/ExtGState", "/XObject"):
        if key in res:
            d = res[key].get_object()
            for n in list(d.keys()):
                if str(n) not in used:
                    del d[n]
            if not len(d):
                del res[key]

    # Image-only pages are preserved because they may be normal newspaper scans.
    if main is None and stats["text_removed"] == 0 and "/XObject" in res:
        return "image-only"
    return "ok"


def main():
    global DEBUG
    ap = argparse.ArgumentParser(description="Action Karachi PDF cleaner")
    ap.add_argument("input", nargs="?", default=INPUT_PDF)
    ap.add_argument("output", nargs="?", default=OUTPUT_PDF)
    ap.add_argument("--extra", action="append", default=[], help="extra blacklist word/number")
    ap.add_argument("--keep-ad-pages", action="store_true")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--skip-reference-images", action="store_true")
    args = ap.parse_args()
    DEBUG = args.debug

    matcher = Matcher(args.extra)
    if args.skip_reference_images and mw.contains_reference_ad(args.input):
        result = {
            "status": "reference-image-skipped",
            "watermarkTypes": [],
            "bakedPages": [],
            "reason": "Reference/ad image matched the existing MW full-PDF skip rules.",
        }
        print(f"CLEAN_SOCIAL_MEDIA_RESULT:{json.dumps(result)}", flush=True)
        return 0

    reader = PdfReader(args.input)
    writer = PdfWriter()
    total, kept = len(reader.pages), 0
    totals = {"text_removed": 0, "strips_removed": 0, "annots_removed": 0}
    image_only_pages = []

    for i, page in enumerate(reader.pages, 1):
        stats = {"text_removed": 0, "strips_removed": 0, "annots_removed": 0}
        kind = clean_page(reader, page, matcher, stats)
        for k in totals:
            totals[k] += stats[k]
        if kind == "image-only":
            image_only_pages.append(i)
        writer.add_page(page)
        kept += 1
        msg = (f"text objects removed: {stats['text_removed']}, "
               f"strips removed: {stats['strips_removed']}")
        if stats["annots_removed"]:
            msg += f", annotations removed: {stats['annots_removed']}"
        if kind == "image-only":
            msg += "  | image-only page preserved (no selectable text to inspect)"
        print(f"[{i}/{total}] cleaned  ({msg})")

    result = {
        "status": "cleaned",
        "watermarkTypes": sorted(matcher.detected),
        "imageOnlyPages": image_only_pages,
        "pages": total,
        "keptPages": kept,
        "removed": totals,
    }
    if kept == 0:
        result["status"] = "failed"
        result["reason"] = "Cleaner removed all pages; output was not sent."
        print(f"CLEAN_SOCIAL_MEDIA_RESULT:{json.dumps(result)}", flush=True)
        return 4
    writer.add_metadata({"/Title": args.output.rsplit(".", 1)[0]})
    writer.compress_identical_objects(remove_identicals=True, remove_orphans=True)
    with open(args.output, "wb") as f:
        writer.write(f)
    remaining = Matcher(args.extra)
    cleaned_reader = PdfReader(args.output)
    for page in cleaned_reader.pages:
        remaining.hit(page.extract_text() or "", whole=False)
    if remaining.detected:
        result["status"] = "watermark-not-removed"
        result["watermarkTypes"] = sorted(remaining.detected)
        result["reason"] = "Target watermark text remains after cleanup; output was not sent."
        print(f"CLEAN_SOCIAL_MEDIA_RESULT:{json.dumps(result)}", flush=True)
        return 3
    print(f"\nDone: {kept}/{total} pages -> {args.output}")
    print(f"Total: {totals['text_removed']} text ops, {totals['strips_removed']} strips, "
          f"{totals['annots_removed']} annots removed")
    print(f"CLEAN_SOCIAL_MEDIA_RESULT:{json.dumps(result)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
