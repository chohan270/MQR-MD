# 🗞️ Malik Newspapers | Newsroom Console

Malik Newspapers is a WhatsApp e-paper automation bot built for fast, tidy and dependable newspaper delivery. It collects the day’s editions, turns pages into PDFs, applies the project watermark and sends them to selected WhatsApp groups.

This is an operations-focused bot: automatic delivery can be paused at any time, individual papers can be requested manually, and a paper that has already been sent stays locked until the owner deliberately clears its record.

## 📣 Auto-Forward Desk

The main bot workflow is message forwarding. Configure sources, targets and group-level forwarding without changing the saved WhatsApp session.

📤 **Direct forwarding** — Send a replied message to selected chats with `.f`.

🔁 **Group forwarding** — Turn forwarding on or off for the current group.

🌐 **Global forwarding** — Manage owner-controlled source and target groups from `.af global`.

🧽 **Clean relay** — Forwarded labels and configured text replacements are handled by the bot’s cleaning layer.

## 📰 Newspaper Desk

📡 **Scheduled delivery** — Run newspaper downloads in Pakistan Standard Time.

🎯 **Target control** — Choose one or more WhatsApp groups for e-paper delivery.

🧾 **Duplicate lock** — Each date and PDF filename receives one atomic MongoDB sent record. Retries, restarts and manual runs cannot send that same file again.

🧹 **Controlled reset** — Use `.af epaper clearsent` when a same-day paper genuinely needs to be sent again.

🧩 **Isolated downloads** — Every newspaper works in its own temporary workspace, so editions do not overwrite one another.

📰 **Readable filenames** — The News editions follow names such as `TheNews Lahore 28August.pdf`.

## 🎛️ E-Paper Control Desk

All e-paper controls are owner-only.

| Command | Action |
| --- | --- |
| `.af epaper` | Open the e-paper control/status page. |
| `.af epaper on` | Turn automatic newspaper uploading on. |
| `.af epaper off` | Pause automatic uploading. |
| `.af epaper set jid1,jid2` | Set destination groups. |
| `.af epaper run` | Start a complete manual pass. |
| `.af epaper run jasarat` | Download/send one selected newspaper. |
| `.af epaper keys` | Show available newspaper keys. |
| `.af epaper clearsent` | Clear today’s sent records and allow those PDFs again. |

Manual runs remain available when automatic uploading is off. Turning automatic uploading off does not delete targets, sent records or the WhatsApp session.

## 🧭 Everyday Commands

| Command | Action |
| --- | --- |
| `.menu` / `.help` | Open the formatted command index. |
| `.af` | Open the group forwarding control desk. |
| `.af on` / `.af off` | Enable or pause forwarding for the current group. |
| `.af set jid1,jid2` | Save forwarding targets for the current group. |
| `.af global` | View global forwarding status. |
| `.f <jids>` | Send a replied message to selected chats. |
| `.gjids` | List participating groups and their JIDs. |
| `.jid` | Show the current chat JID. |
| `.ping` | Check response and server latency. |
| `.uptime` | Show how long the bot has been online. |

## 🛡️ Delivery Rules

1. A completed PDF is claimed atomically before delivery, preventing overlapping runs from sending it twice.
2. A failed delivery releases its claim and remains eligible for retry.
3. A successful delivery is recorded by Pakistan date and filename.
4. The record remains effective across Heroku restarts and redeploys.
5. Only `.af epaper clearsent` removes today’s sent records.

## 🧰 Local Setup

Requirements: Node.js 20+, Python 3 and MongoDB.

```powershell
npm install
npm start
```

Configure `SESSION_ID` and `MONGODB_URI` through the environment. For an already-linked deployment, preserve the existing values so the same WhatsApp session and MongoDB data continue to be used.

## 🚀 Heroku Release

The project is deployed to the existing `epapers` app:

```powershell
git push heroku master
heroku ps:scale web=1 -a epapers
heroku logs --tail -a epapers
```

Deployment does not clear the WhatsApp session, MongoDB authentication, target groups or sent-file records.

<p align="center"><b>Built for clean editions, calm retries and one delivery per file.</b></p>
