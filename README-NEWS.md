# Malik MD — Live News Recording Auto-System

Ye feature **epaper system jese hi pattern** par bani hai — sirf newspapers
ki jagah 5 live TV news channels (Tamasha CDN streams) ko record, watermark
aur WhatsApp groups mein auto-upload karti hai.

## 🧠 Kaise kaam karta hai

```
Node.js bot (index.js)
    │
    │  node-cron schedule fire hota hai (Asia/Karachi time)
    ▼
maliklib/newsEngine.js
    │  spawn: ffmpeg (live stream -> watermark overlay -> mp4)
    │  har channel apna alag, independent ffmpeg process hai
    ▼
Recording rukti hai jab:
    1. Max duration (default 30 min) poora ho jaye (auto-stop), YA
    2. `.news stop <key|all>` se manually stop kiya jaye (turant)
    ▼
newsEngine.js:
    1. Caption banata hai (channel + date + time + day, Urdu, dynamic)
    2. Pehle PRIMARY groups ko video bhejta hai (.setprimarygroup se set)
    3. Phir baqi target groups ko (.news set se set)
    4. /tmp se file delete kar deta hai (WhatsApp se NAHI)
```

### Channels

| Key | Channel | Watermark | Notes |
|---|---|---|---|
| `samaa` | Samaa TV | kk360.png | 450x360, crf30, r7 |
| `geo` | Geo News | kk480.png | 600x480, aspect 5:4 |
| `express` | Express News | kk360.png | 450x360, aspect 5:4 |
| `ary` | ARY News | kk360.png | 4:3, timed overlay |
| `khyber` | Khyber News | kk360.png | 450x360, crf30, r7 |

Watermark files: `scripts/assets/news/kk360.png` aur `kk480.png` (already
bundled in this zip).

### Schedule (Asia/Karachi time)

| Time | Urdu label |
|---|---|
| 06:00, 08:00, 10:00 | صبح (Subha) |
| 12:00, 15:00 | دوپہر (Dhupair) |
| 18:00 | شام (Sham) |
| 21:00, 00:00 | رات (Raat) |

Har scheduled slot par sab **enabled** channels record start karte hain —
lekin **ek sath sab nahi**. R14 (memory quota exceeded) se bachne ke liye
ek concurrency limit hai (default **2 channels ek waqt mein**); baqi
channels queue mein wait karte hain aur jaise hi koi slot khali hota hai
(kisi channel ki recording khatam hoti hai), agla queue wala khud hi shuru
ho jata hai. Har recording ki hard safety cap **30 minute** hai — agar
koi manually stop na kare to khud hi save + upload ho jayegi. 00:00
(raat) wali recording ke liye bhi yehi rule hai.

### ⚠️ R14 / Memory-Quota Safety

512MB Heroku dyno par 5 ffmpeg live-encodes ek sath chalana crash (R14)
ka sabse bada risk hai. Isliye:

- `maxConcurrentRecordings` (default **2**) — sirf itne channels ek waqt
  record karte hain; baqi automatically queue mein rehte hain aur turant
  shuru ho jate hain jaise hi ek slot free ho.
- `.news concurrency <1-5>` se ye limit kabhi bhi badal/kam kar sakte ho —
  chota (512MB) dyno ho to 1-2 rakho, bada dyno (1GB+) ho to 3-4 tak try
  kar sakte ho.
- `.news stop <key|all>` queue mein wait kar rahe channels ko bhi hata
  deta hai (agar wo abhi record shuru nahi hue).
- Agar koi channel poori tarah queue mein hi rah jaye (kabhi slot na
  mile) to agla scheduled time aane par wo purana queue entry drop ho
  jata hai (log mein warning aati hai) — taake backlog hamesha ke liye na
  badhta rahe. Jo channel already record ho raha hai use ye affect nahi
  karta, wo apni recording poori karta hai.
- Har ffmpeg process `-threads 1` ke sath chalta hai taake CPU/memory
  usage predictable rahe.

## 📲 WhatsApp Commands (owner-only, jaisa `.af`/`.af epaper` hai)

```
.setprimarygroup jid1, jid2      → Primary group(s) set karo (video sabse pehle inhe milta hai)
.setprimarygroup clear           → Primary group list clear karo

.news                            → Status dikhata hai (schedule, groups, current recording)
.news on / off                   → Auto schedule ON/OFF
.news set jid1, jid2             → Baqi (secondary) target groups set karo
.news channels                   → Sab channel keys aur unka ON/OFF status
.news enable <key>               → Channel ko auto schedule mein shamil karo
.news disable <key>              → Channel ko auto schedule se hatao
.news start <key|all>            → Abhi recording shuru karo (manual/test, queue-aware)
.news stop <key|all>             → Abhi recording rok kar save+upload karo (ya queue se hata do)
.news concurrency <1-5>          → Kitne channels ek sath record ho sakte hain (default 2, R14 safety)
.news status                     → `.news` jesa hi
```

Available keys: `samaa`, `geo`, `express`, `ary`, `khyber`

## 🚀 Deployment

Koi naya package chahiye nahi — `ffmpeg` pehle se `Aptfile` mein hai, aur
`fs-extra` / `node-cron` pehle se `package.json` mein hain (epaper system
inhi ko use karta hai). Koi extra environment variable bhi nahi chahiye —
sab kuch WhatsApp commands se MongoDB mein save hota hai, bilkul epaper
system ki tarah.
