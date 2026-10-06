# MQR MD — Epaper Auto-Forward WhatsApp Bot (Heroku)

Ye repo aapka mojooda Baileys bot hai + **poora automated Epaper system**
add kiya gaya hai (27 newspapers: Express, Jang, The News, Dawn, Nawaiwaqt,
Jasarat, Khabrain waghera).

## 🧠 Kaise kaam karta hai

```
Node.js bot (index.js)
    │
    │  node-cron schedule fire hota hai (Asia/Karachi time)
    ▼
maliklib/epaperEngine.js
    │
    │  spawn: python3 scripts/epaper_scheduler.py --batch express|baqi
    ▼
scripts/epaper_scheduler.py
    │  1. Har newspaper script chalata hai (/tmp/epaper_work/<name>/ mein)
    │  2. Har script ki PDF(s) dhoondta hai
    │  3. scripts/wm.py se watermark karta hai
    │  4. Watermarked PDFs /tmp/epaper_outbox/ mein rakhta hai
    │  5. Result JSON print karta hai (EPAPER_RESULT_JSON:{...})
    ▼
epaperEngine.js wapis control leta hai
    │  1. Primary group set ho to pehle wahan upload karta hai, phir baqi
    │     target groups ko forward karta hai; warna har target par direct send
    │  2. MongoDB mein "sent" mark karta hai (duplicate-skip)
    │  3. /tmp se file delete karta hai (WhatsApp group se NAHI)
    │  4. Jo newspaper fail ho, use "pendingRetries" list mein daal deta hai
    ▼
Har 15 minute (3AM–10AM) retryTick() sirf failed newspapers dobara try
karta hai, jab tak maxRetries (default 4) khatam na ho.
```

### Schedule (Asia/Karachi time)

| Time | Kaam |
|---|---|
| 3:00 AM (Mon–Sat) | Express: 11 editions **ek sath (parallel)** download → jo bhi pehle ban jaye turant send |
| 5:30 AM (Sunday only) | Express (Sunday ko baad mein) |
| 4:30 AM (daily) | Early baqi newspapers download + watermark; late papers apne publication window tak hold |
| 5:00 AM (daily) | Baqi 25 newspapers: jo ban chuki unko send + delete |
| 8:00 AM ke baad | Mashriq, Pakistan Today, Islamk, Aaj, Nai Baat, Nawaiwaqt, Ausaf, The Nation, PakObserver, Jasarat, Khabrain: aaj ki copy available hone par retry/send; Khabrain ke liye 2+ pages lazmi |
| 8:00 AM ke baad | Lead Pakistan aur The Patriot: website par aaj ki edition milte hi retry/send |
| 10:00 AM ke baad | Mashriq Akhbar: aaj ki copy available hone par retry/send |
| 3:00 PM ke baad | Kawish: aaj ki copy available hone par retry/send |
| Har 15 min, 3AM–11:45PM | Sirf FAILED newspapers dobara try — **koi attempt-limit nahi**, lekin har paper apne publication window se pehle run nahi hota |

Newspapers ab **ek ek karke nahi, balke ek sath (parallel, max 6 simultaneously)**
chalte hain — is se do fayde hain:
1. **Speed** — 26 scripts sequentially ~30-60 min lagte, ab parallel mein bohat
   kam waqt (fast newspapers jaldi ban kar chali jati hain).
2. **Koi ek atki hui newspaper baaki ko block nahi karti** — agar "X" newspaper
   ka server slow hai ya down hai, "Y", "Z" waghera sath mein chalte rehte hain
   aur apni waqt par ban kar WhatsApp par chali jati hain. Sirf "X" retry-queue
   mein chali jati hai aur har 15 min try hoti rehti hai **jab tak ban na
   jaye** — chahe pura din lag jaye.


---

## 📲 WhatsApp Commands

Sab commands **owner-only** hain (jis number se bot connect hai, wahi use
kar sakta hai — ya `.env`/DB mein defined sudo).

```
.af epaper set 12345@g.us, 67890@g.us    → target groups set karo (multiple, comma-separated)
.af epaper primary 12345@g.us            → pehle is group mein upload, phir baqi targets ko forward
.af epaper primary off                   → primary group clear karo
.af epaper on                            → auto-system ON
.af epaper off                           → auto-system OFF
.af epaper run                           → abhi turant Express + Baqi + retries chalao (manual)
.af epaper                               → status dekho (ON/OFF, targets, last run, pending retries)
.mw menu                                 → automatic PDF controls dekho
.mw auto status                          → .mw auto processing aur duplicate records ka status
.mw auto on / .mw auto off               → new group PDFs ki automatic processing on/off
.mw list                                 → recent manual/retry PDF queue dekho
.mw process all                          → pending PDFs manually process karo
```

### Automatic group PDF workflow

Automatic processing default-on hai. Nayi group PDF aate hi bot `mw.py` se usay
process karke `.af epaper set` wale target groups mein bhejta hai. `.mw auto off`
automatic sending rok kar nayi PDFs manual queue mein rakhta hai; `.mw auto on`
usay dobara chalu karta hai.

In do groups mein configured dono sender IDs ki PDFs queue/process nahi hotin:
`120363026226973835@g.us` aur `923489517717-1546053015@g.us`. Baqi group
members ki PDFs normal process hoti hain.

`.mw` aur `.af epaper` dono MongoDB ke shared filename record se deduplicate
hote hain: normalized same filename successful send ke baad 24 ghante tak
dobara process/send nahi hota. Record atomic claim se banta hai, taake alag
groups se ek hi waqt aane wali copies bhi double na bheji jayen. `.af epaper
clearsent` current Pakistan-day ke records (shared records samet) clear karta
hai.

Automatic/manual PDF work FIFO mein one-by-one process hota hai. Agar
automatic mode off ho ya processing/send fail ho, pending PDF `.mw list` mein
manual retry ke liye rehti hai. `.mw process all` queue ki PDFs process karta
hai; pehle se delivered duplicate skip hoti hai.

Group ka JID nikalne ke liye group mein `.af` bhej dein — ya jo bhi purana
JID-finder command (`gjids`/`jid`) already bot mein hai, wahi use karein.

---

## 🚀 Heroku Deployment — Step by Step

### 1. Repo push karein
```bash
git init
git add .
git commit -m "Epaper auto-system added"
heroku git:remote -a qasimraza
git push heroku main
```

### 2. Buildpacks (agar app.json se auto na lagein to manually)
```bash
heroku buildpacks:clear -a qasimraza
heroku buildpacks:add heroku-community/apt -a qasimraza
heroku buildpacks:add heroku/python -a qasimraza
heroku buildpacks:add heroku/nodejs -a qasimraza
```
> Order zaroori hai: pehle **apt** (system package: git),
> phir **python** (requirements.txt: pypdf, pillow, requests, curl_cffi),
> phir **nodejs** (package.json: node-cron, fs-extra waghera).
> Sab kuch build ke waqt khud install ho jayega — kuch bhi manually
> download karne ki zaroorat nahi.

### 3. Config Vars (SIRF YE DO — koi aur nahi chahiye)
```bash
heroku config:set SESSION_ID=your-session-id -a qasimraza
heroku config:set MONGODB_URI="mongodb+srv://user:pass@cluster.mongodb.net/db" -a qasimraza
```

### 4. Dyno chalayein
```bash
heroku ps:scale web=1 -a qasimraza
heroku logs --tail -a qasimraza
```

### 5. Pehli dafa connect karein
Deploy hone ke baad `https://qasimraza-<hash>.herokuapp.com/` khol kar QR
scan karein (ya pairing code route use karein — jo pehle se app mein hai).
Connect hote hi terminal mein ye line dikhegi:
```
🗞️  Epaper cron registered (Asia/Karachi): Express 3:00 AM (Sun 5:30 AM) | Baqi 4:30/5:00 AM | retries every 15 min till 10 AM
```

### 6. WhatsApp se target groups set karein
```
.af epaper set 923001234567-1234567890@g.us
.af epaper on
.af epaper run     ← (test ke liye — abhi turant chala kar dekh lein)
```

---

## ⚠️ Zaroori note — Dyno neend (sleep)

Eco/Basic dynos 30 min ki inactivity ke baad so jate hain — agar dyno so
gaya to 3AM/4:30AM ka cron miss ho sakta hai. Isse bachne ke liye:
- Heroku **Eco/Basic dyno** use karein (paid, sleep nahi hota), **ya**
- Koi external uptime-pinger (UptimeRobot/cron-job.org) har 10-15 min
  par aapke app ke root URL (`/`) ko ping karta rahay, taake dyno
  hamesha jaaga rahe aur node-cron waqt par fire ho.

Ye system ka koi hissa nahi hai jo aapse manually control ho — bas dyno
ka uthe rehna zaroori hai taake cron chal sake.

---

## 📁 Naye/Modified files ka summary

| File | Kya kiya |
|---|---|
| `scripts/*.py` (26 files) | Aapki original scripts, **bina kisi tabdeeli ke** copy |
| `scripts/wm.py` | Same watermark logic, sirf paths portable (Heroku-safe) |
| `scripts/assets/{express.png, pbk.png, pbk.pdf}` | Watermark assets |
| `scripts/epaper_registry.py` | **NEW** — har newspaper ka mode/batch/Sunday config |
| `scripts/epaper_scheduler.py` | **NEW** — download+watermark orchestrator |
| `requirements.txt`, `.python-version` | **NEW** — Python deps + version |
| `Aptfile` | python3-pip/venv add kiya |
| `app.json` | `heroku/python` buildpack add kiya |
| `package.json` | `node-cron`, `fs-extra` add kiye |
| `maliklib/database.js` | `EpaperConfig` + `EpaperSentFile` schemas/functions add |
| `maliklib/epaperEngine.js` | **NEW** — cron, python-spawn, WhatsApp send, retry logic |
| `scripts/mw.py` | Owner reaction wali PDFs ka cleanup, two-PNG watermark aur merge pipeline |
| `scripts/leadpakistan.py` | Current-date Lead Pakistan downloader |
| `malikplugins/autoforward.js` | `.af epaper set/on/off/run` commands add |
| `index.js` | Connection open hone par `epaperEngine.init()` call |
| `.env.example` | Sirf `SESSION_ID` + `MONGODB_URI` |

Baaki files (`malikplugins/forward.js`, `gjids.js`, `jid.js`, `menu.js`,
`ping.js`, `uptime.js`, `maliklib/session.js`, `mongoAuth.js`,
`cleaner.js`, `public/index.html`, `Dockerfile`, `Procfile`,
`ecosystem.config.json`) **bilkul waisi hi hain jaisi aapki original zip
mein thi** — kuch chhera nahi gaya.
