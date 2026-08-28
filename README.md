# Malik Newspapers

Malik Newspapers is a WhatsApp e-paper delivery bot for Pakistani newspaper editions. It downloads the current issue, builds a PDF, applies the project watermark, and delivers it to configured groups through a persistent Baileys session.

## Reliability

- MongoDB-backed WhatsApp authentication preserves the existing session across Heroku restarts.
- Every PDF gets one atomic delivery claim, so overlapping cron runs and retries cannot send the same file twice.
- Failed downloads and failed deliveries remain retryable without re-sending a completed file.
- Each downloader runs in an isolated temporary folder, preventing edition files from colliding.
- The News files use names such as `TheNews Lahore 28August.pdf`.

## Commands

| Command | Purpose |
| --- | --- |
| `.menu` / `.help` | Show the command deck. |
| `.af` | Configure auto-forwarding for the current chat. |
| `.af epaper set jid1,jid2` | Set e-paper destination groups. |
| `.af epaper on` / `.off` | Enable or pause scheduled delivery. |
| `.af epaper run` | Run an immediate e-paper pass. |
| `.af epaper` | Show e-paper status and pending retries. |
| `.f` | Forward a replied message to selected JIDs. |
| `.gjids` | List group names and JIDs. |
| `.jid` | Show the current chat JID. |

## Run locally

Requirements: Node.js 20+, Python 3, and MongoDB.

```powershell
npm install
npm start
```

Set `SESSION_ID` and `MONGODB_URI` in the environment. Keep the existing values when redeploying an already-linked bot.

## Deploy to Heroku

```powershell
git push heroku master
heroku ps:scale web=1 -a epapers
heroku logs --tail -a epapers
```

On the first deploy date, a one-time guard allows only Aaj, Daily Ausaf, and Kawish, preventing another resend of papers already delivered today. Normal delivery resumes automatically on the next Pakistan date. Deployment does not clear session data or MongoDB authentication records.

## Layout

- `index.js`: web process and WhatsApp connection lifecycle
- `maliklib/epaperEngine.js`: scheduling, retries, and delivery claims
- `maliklib/database.js`: MongoDB models and persistence
- `scripts/`: newspaper downloaders and e-paper scheduler
- `malikplugins/`: WhatsApp command plugins
