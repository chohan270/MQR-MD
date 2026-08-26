/**
 * ⚡ MALIK MD AUTOFORWARD BOT — LIVE NEWS RECORDING AUTOMATION ⚡
 *
 * Pipeline (per requirements):
 *   Scheduled slots (Asia/Karachi): 06:00, 08:00, 10:00, 12:00, 15:00,
 *   18:00, 21:00, 00:00 -> every enabled channel is REQUESTED to record
 *   (ffmpeg, watermarked, low-bitrate live capture straight from the
 *   Tamasha CDN).
 *
 *   Safety cap: every recording auto-stops + saves + uploads after
 *   `maxDurationMinutes` (default 30) MAX -- even if nobody sends the
 *   manual stop command. This applies to every slot, including 00:00.
 *
 *   Manual stop: `.news stop <key|all>` sends SIGINT to the ffmpeg
 *   process, which finalizes the mp4 immediately -- then it is uploaded
 *   right away (no need to wait for the 30-minute cap).
 *
 *   Delivery order: primaryGroups FIRST, then the remaining targetJids
 *   ("baqi" groups) -- exactly like the epaper engine's group ordering,
 *   but primary-groups-first is specific to this feature.
 *
 * ---------------------------------------------------------------------------
 * R14 (MEMORY QUOTA EXCEEDED) PROTECTION -- IMPORTANT
 * ---------------------------------------------------------------------------
 * A live ffmpeg re-encode is far heavier than a PDF download. Launching all
 * 5 channels at the exact same second on a 512MB Heroku dyno is exactly how
 * you get an R14 crash. So this engine NEVER just spawns everything at once:
 *
 *   - `maxConcurrentRecordings` (default 2, tunable via `.news concurrency`)
 *     caps how many ffmpeg processes may run AT THE SAME TIME.
 *   - Every recording request (scheduled OR manual) goes through
 *     `requestRecording()`. If a free slot exists it starts immediately;
 *     otherwise it waits in an in-memory queue.
 *   - The instant any recording finishes (auto 30-min cap, manual stop, or
 *     a stream error), `processQueue()` immediately pulls the next queued
 *     channel into that freed slot -- so a 5-channel run with concurrency=2
 *     completes in ~3 waves instead of 1 memory-crushing wave.
 *   - When a NEW scheduled slot fires, any channels still sitting
 *     unstarted in the queue from the PREVIOUS slot are dropped (logged)
 *     instead of piling up forever -- already-recording processes are
 *     left alone and finish normally.
 *
 * Tune `maxConcurrentRecordings` to match the dyno: 512MB dynos should
 * stay at 1-2; a 1GB+ dyno can usually handle 3-4 safely.
 */
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs-extra');
const cron = require('node-cron');

const {
    malik_getNewsConfig,
    malik_updateNewsConfig
} = require('./database');

const ASSETS_DIR = path.join(__dirname, '..', 'scripts', 'assets', 'news');
const WORKDIR = '/tmp/news_work';
const FFMPEG_PATH = process.env.FFMPEG_PATH || 'ffmpeg';
const TZ_OPTS = { timezone: 'Asia/Karachi' };

fs.ensureDirSync(WORKDIR);

let currentSock = null;
let currentSessionId = null;
let cronRegistered = false;

// -----------------------------------------------------------------------------
// CHANNEL DEFINITIONS (mirrors the ffmpeg commands supplied by the owner)
// -----------------------------------------------------------------------------
const CHANNELS = {
    samaa: {
        key: 'samaa',
        label: 'Samaa TV',
        urduLabel: 'سماء',
        url: 'https://cdn05khi.tamashaweb.com:8087/jazzauth/samaaTV-abr/live/vsat-123M/chunks.m3u8',
        watermark: 'kk360.png',
        buildArgs(inputUrl, watermarkPath, outPath, durationSec) {
            return [
                '-y',
                '-threads', '1',
                '-reconnect', '1',
                '-reconnect_streamed', '1',
                '-reconnect_at_eof', '1',
                '-reconnect_delay_max', '10',
                '-i', inputUrl,
                '-i', watermarkPath,
                '-t', String(durationSec),
                '-filter_complex', '[0:v]scale=450:360,setsar=1,eq=brightness=0.00:saturation=1.6[bg];[1:v]scale=450:360[wm];[bg][wm]overlay=0:0',
                '-c:v', 'libx264',
                '-preset', 'veryfast',
                '-crf', '30',
                '-r', '7',
                '-c:a', 'aac',
                '-ac', '1',
                '-b:a', '32k',
                '-ar', '44100',
                '-movflags', '+faststart',
                outPath
            ];
        }
    },
    geo: {
        key: 'geo',
        label: 'Geo News',
        urduLabel: 'جیو',
        url: 'https://cdn07lhr.tamashaweb.com:8087/jazzauth/vsat-geonews-abr/live/vsat-93M/chunks.m3u8',
        watermark: 'kk480.png',
        buildArgs(inputUrl, watermarkPath, outPath, durationSec) {
            return [
                '-y',
                '-threads', '1',
                '-reconnect', '1',
                '-reconnect_streamed', '1',
                '-reconnect_at_eof', '1',
                '-reconnect_delay_max', '10',
                '-i', inputUrl,
                '-i', watermarkPath,
                '-t', String(durationSec),
                '-filter_complex', '[0:v]scale=600:480,setsar=1,eq=brightness=0.00:saturation=1.6[bg];[1:v]scale=600:480[wm];[bg][wm]overlay=0:0',
                '-c:v', 'libx264',
                '-preset', 'veryfast',
                '-crf', '32',
                '-r', '7',
                '-b:v', '64k',
                '-c:a', 'aac',
                '-ac', '1',
                '-b:a', '32k',
                '-ar', '44100',
                '-aspect', '5:4',
                '-movflags', '+faststart',
                outPath
            ];
        }
    },
    express: {
        key: 'express',
        label: 'Express News',
        urduLabel: 'ایکسپریس',
        url: 'https://cdn23lhr.tamashaweb.com:8087/jazzauth/expressnews-abr/live/vsat-91M/chunks.m3u8',
        watermark: 'kk360.png',
        buildArgs(inputUrl, watermarkPath, outPath, durationSec) {
            return [
                '-y',
                '-threads', '1',
                '-fflags', '+genpts+discardcorrupt',
                '-i', inputUrl,
                '-i', watermarkPath,
                '-t', String(durationSec),
                '-filter_complex', '[0:v]scale=450:360,setsar=1,eq=brightness=0.00:saturation=1.6[bg];[1:v]scale=450:360[wm];[bg][wm]overlay=0:0',
                '-c:v', 'libx264',
                '-preset', 'veryfast',
                '-crf', '30',
                '-r', '7',
                '-c:a', 'aac',
                '-ac', '1',
                '-b:a', '32k',
                '-ar', '44100',
                '-aspect', '5:4',
                '-movflags', '+faststart',
                outPath
            ];
        }
    },
    ary: {
        key: 'ary',
        label: 'ARY News',
        urduLabel: 'اے آر وائی',
        url: 'https://cdn07lhr.tamashaweb.com:8087/jazzauth/vsat-arynews-abr/live/vsat-arynews-L/chunks_dvr_timeshift-0-3600.m3u8',
        watermark: 'kk360.png',
        buildArgs(inputUrl, watermarkPath, outPath, durationSec) {
            return [
                '-y',
                '-threads', '1',
                '-i', inputUrl,
                '-i', watermarkPath,
                '-t', String(durationSec),
                '-filter_complex', 'overlay=0:0:enable=between(t\\,15\\,480),setsar=1,eq=brightness=0.0:saturation=1.9,scale=ih*4/3:ih',
                '-aspect', '4:3',
                '-ac', '1',
                '-c:v', 'libx264',
                '-crf', '34',
                '-b:v', '0.044m',
                '-b:a', '48k',
                '-r', '5',
                '-ar', '48k',
                '-preset', 'veryfast',
                '-strict', '-2',
                '-movflags', '+faststart',
                outPath
            ];
        }
    },
    khyber: {
        key: 'khyber',
        label: 'Khyber News',
        urduLabel: 'خیبر',
        url: 'https://cdn22lhr.tamashaweb.com:8087/jazzauth/KhyberNews-abr/live/160L/chunks.m3u8',
        watermark: 'kk360.png',
        buildArgs(inputUrl, watermarkPath, outPath, durationSec) {
            return [
                '-y',
                '-threads', '1',
                '-reconnect', '1',
                '-reconnect_streamed', '1',
                '-reconnect_at_eof', '1',
                '-reconnect_delay_max', '10',
                '-i', inputUrl,
                '-i', watermarkPath,
                '-t', String(durationSec),
                '-filter_complex', '[0:v]scale=450:360,setsar=1,eq=brightness=0.00:saturation=1.6[bg];[1:v]scale=450:360[wm];[bg][wm]overlay=0:0',
                '-c:v', 'libx264',
                '-preset', 'veryfast',
                '-crf', '30',
                '-r', '7',
                '-c:a', 'aac',
                '-ac', '1',
                '-b:a', '32k',
                '-ar', '44100',
                '-movflags', '+faststart',
                outPath
            ];
        }
    }
};
const CHANNEL_KEYS = Object.keys(CHANNELS);

// In-memory registry of currently-running recordings: key -> state
const activeRecordings = new Map();

// In-memory FIFO queue of channels waiting for a free recording slot.
// Each entry: { key, opts, slotTag }
const pendingQueue = [];

// Cached so processQueue() (called from an ffmpeg 'close' event, i.e.
// outside any request context) knows the current concurrency cap without
// an extra DB round-trip every time. Refreshed every time requestRecording
// or runScheduledSlot reads the config.
let cachedMaxConcurrent = 2;
let concurrencySetManually = false;

// -----------------------------------------------------------------------------
// TIME HELPERS (Pakistan Standard Time, independent of the dyno's UTC clock)
// -----------------------------------------------------------------------------
function pktNow() {
    return new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Karachi' }));
}

const URDU_WEEKDAYS = ['اتوار', 'پیر', 'منگل', 'بدھ', 'جمعرات', 'جمعہ', 'ہفتہ'];
const URDU_MONTHS = ['جنوری', 'فروری', 'مارچ', 'اپریل', 'مئی', 'جون', 'جولائی', 'اگست', 'ستمبر', 'اکتوبر', 'نومبر', 'دسمبر'];
const BOLD_DIGITS = { '0': '𝟬', '1': '𝟭', '2': '𝟮', '3': '𝟯', '4': '𝟰', '5': '𝟱', '6': '𝟲', '7': '𝟳', '8': '𝟴', '9': '𝟵' };
function toBoldDigits(numStr) {
    return String(numStr).split('').map((c) => BOLD_DIGITS[c] || c).join('');
}

// Maps a 24h hour (the scheduled slot) to the Urdu time-of-day word + a
// decorative emoji, following exactly the "Subha 06,08,10 / Dhupair 12,03 /
// Sham 6 / Raat 9,00:00" grouping the owner specified.
function timeOfDayInfo(hour24) {
    if ([6, 8, 10].includes(hour24)) return { word: 'صبح', emoji: '🌅' };
    if ([12, 15].includes(hour24)) return { word: 'دوپہر', emoji: '🌤️' };
    if (hour24 === 18) return { word: 'شام', emoji: '🌇' };
    // 21 and 0 (midnight)
    return { word: 'رات', emoji: '🎋' };
}

function hour12Display(hour24) {
    let h = hour24 % 12;
    if (h === 0) h = 12;
    return String(h).padStart(2, '0');
}

// Builds the caption exactly in the owner's requested style, dynamically
// filled in with the channel name + current date/time/day every single run.
function buildCaption(channelKey, scheduledHour) {
    const ch = CHANNELS[channelKey];
    const now = pktNow();
    const hour24 = (typeof scheduledHour === 'number') ? scheduledHour : now.getHours();
    const { word: todWord, emoji: todEmoji } = timeOfDayInfo(hour24);
    const hh = hour12Display(hour24);

    const day = String(now.getDate()).padStart(2, '0');
    const month = URDU_MONTHS[now.getMonth()];
    const year = toBoldDigits(now.getFullYear());
    const weekday = URDU_WEEKDAYS[now.getDay()];

    let text = `*${ch.urduLabel}🗞️ نیـوز (ہیڈلائنـز)|𝗔𝗗𝗦™| ${todWord} ${hh} بجــے ${todEmoji}*\n\n`;
    text += `*تاریـخ ${day} ${month} ${year}*🇵🇰👆🏻📡💯\n`;
    text += `*🌞🌾بــروز ${weekday}🪀🌦*`;
    return text;
}

// -----------------------------------------------------------------------------
// RECORDING: START / STOP (queue-aware -- see R14 protection note up top)
// -----------------------------------------------------------------------------
function outputFileFor(key) {
    const stamp = pktNow().toISOString().replace(/[:.]/g, '-');
    return path.join(WORKDIR, `${key}_${stamp}.mp4`);
}

// Actually spawns ffmpeg for ONE channel. Only ever called when a
// concurrency slot is confirmed free (from requestRecording / processQueue).
function spawnRecording(key, { scheduledHour = null, maxDurationMinutes = 30 } = {}) {
    const ch = CHANNELS[key];
    const watermarkPath = path.join(ASSETS_DIR, ch.watermark);
    const outPath = outputFileFor(key);
    const durationSec = Math.max(60, Math.round(maxDurationMinutes * 60));
    const args = ch.buildArgs(ch.url, watermarkPath, outPath, durationSec);

    console.log(`[news] ▶️ starting recording: ${key} -> ${outPath} (max ${maxDurationMinutes} min) [active: ${activeRecordings.size + 1}/${cachedMaxConcurrent}, queued: ${pendingQueue.length}]`);
    const proc = spawn(FFMPEG_PATH, args, { cwd: ASSETS_DIR });

    const state = {
        key,
        proc,
        outPath,
        startedAt: Date.now(),
        scheduledHour,
        maxDurationMinutes,
        stoppedManually: false,
        finished: false,
        stderrTail: ''
    };
    activeRecordings.set(key, state);

    proc.stderr.on('data', (d) => {
        state.stderrTail = (state.stderrTail + d.toString()).slice(-4000);
    });

    proc.on('close', (code) => {
        state.finished = true;
        activeRecordings.delete(key);
        handleRecordingFinished(state, code).catch((e) => {
            console.error(`[news] post-processing error for ${key}:`, e.message);
        });
        // A slot just freed up -- immediately pull the next queued channel
        // in, if any. This is what turns "5 channels" into safe waves of
        // `maxConcurrentRecordings` instead of one memory-crushing burst.
        processQueue();
    });
    proc.on('error', (err) => {
        console.error(`[news] ffmpeg failed to start for ${key}:`, err.message);
        state.finished = true;
        activeRecordings.delete(key);
        processQueue();
    });
}

// Starts as many queued channels as current free capacity allows.
function processQueue() {
    while (activeRecordings.size < cachedMaxConcurrent && pendingQueue.length > 0) {
        const next = pendingQueue.shift();
        // Guard: don't double-start if it somehow already began recording
        // (e.g. manually started while queued).
        if (activeRecordings.has(next.key)) continue;
        spawnRecording(next.key, next.opts);
    }
}

// Public entry point for BOTH the cron scheduler and manual `.news start`.
// If a concurrency slot is free, recording begins immediately; otherwise
// the channel waits in the queue and starts automatically the moment a
// slot frees up (see processQueue()).
function requestRecording(key, opts = {}) {
    if (!CHANNELS[key]) return { started: false, queued: false, reason: 'unknown-channel' };
    if (activeRecordings.has(key)) return { started: false, queued: false, reason: 'already-recording' };
    if (pendingQueue.some((q) => q.key === key)) return { started: false, queued: true, reason: 'already-queued' };

    if (activeRecordings.size < cachedMaxConcurrent) {
        spawnRecording(key, opts);
        return { started: true, queued: false };
    }
    pendingQueue.push({ key, opts, slotTag: opts.slotTag || null });
    console.log(`[news] ⏳ queued (concurrency limit ${cachedMaxConcurrent} reached): ${key} [queue length: ${pendingQueue.length}]`);
    return { started: false, queued: true };
}

// Gracefully stops a recording early -- SIGINT tells ffmpeg to finish
// encoding and close the mp4 properly (same as pressing 'q'/Ctrl+C). If the
// channel is only sitting in the queue (never actually started), it's
// simply removed from the queue instead.
function stopRecording(key) {
    const queuedIdx = pendingQueue.findIndex((q) => q.key === key);
    if (queuedIdx !== -1) {
        pendingQueue.splice(queuedIdx, 1);
        return { stopped: true, wasQueued: true };
    }

    const state = activeRecordings.get(key);
    if (!state) return { stopped: false, reason: 'not-recording' };
    state.stoppedManually = true;
    try {
        state.proc.kill('SIGINT');
    } catch (e) {
        console.error(`[news] failed to signal ffmpeg for ${key}:`, e.message);
        return { stopped: false, reason: e.message };
    }
    return { stopped: true, wasQueued: false };
}

function stopAll() {
    const activeKeys = [...activeRecordings.keys()];
    const queuedKeys = pendingQueue.map((q) => q.key);
    activeKeys.forEach((k) => stopRecording(k));
    pendingQueue.length = 0; // clear whatever was still waiting
    return { stoppedActive: activeKeys, removedFromQueue: queuedKeys };
}

function getActiveStatus() {
    const now = Date.now();
    const active = [...activeRecordings.values()].map((s) => ({
        key: s.key,
        label: CHANNELS[s.key].label,
        elapsedSeconds: Math.round((now - s.startedAt) / 1000),
        maxDurationMinutes: s.maxDurationMinutes
    }));
    const queued = pendingQueue.map((q) => ({ key: q.key, label: CHANNELS[q.key].label }));
    return { active, queued };
}

// -----------------------------------------------------------------------------
// AFTER A RECORDING FINISHES (auto 30-min cap OR manual stop) -> UPLOAD
// -----------------------------------------------------------------------------
async function handleRecordingFinished(state, exitCode) {
    const { key, outPath, scheduledHour, stoppedManually } = state;
    const reason = stoppedManually ? 'manual stop' : `auto ${state.maxDurationMinutes}-min cap`;
    console.log(`[news] ⏹️ recording finished: ${key} (${reason}, ffmpeg exit ${exitCode})`);

    const exists = await fs.pathExists(outPath);
    const sizeOk = exists && (await fs.stat(outPath)).size > 10 * 1024; // guard against empty/broken files
    if (!sizeOk) {
        console.error(`[news] ❌ ${key}: output file missing or too small, not uploading (stream may have failed to connect).`);
        await fs.remove(outPath).catch(() => {});
        return;
    }

    const caption = buildCaption(key, scheduledHour);
    const sentCount = await deliverFile(outPath, caption, `${key}_${path.basename(outPath)}`);

    await fs.remove(outPath).catch(() => {});

    await malik_updateNewsConfig(currentSessionId, {
        lastRun: new Date(),
        lastRunSummary: `${CHANNELS[key].label}: ${sentCount} group(s) sent (${reason})`
    });
}

// Sends the recorded clip as a video message, PRIMARY groups first, then the
// remaining target ("baqi") groups -- streamed straight from disk so a big
// video never sits fully loaded in RAM.
async function deliverFile(filePath, caption, fileName) {
    if (!currentSock) {
        console.error('[news] no active WhatsApp socket, cannot deliver:', fileName);
        return 0;
    }
    const cfg = await malik_getNewsConfig(currentSessionId);
    const primary = cfg?.primaryGroups || [];
    const baqi = (cfg?.targetJids || []).filter((j) => !primary.includes(j));
    const orderedTargets = [...primary, ...baqi];

    if (!orderedTargets.length) {
        console.error('[news] no target/primary groups configured -- skipping delivery for', fileName);
        return 0;
    }

    let sentCount = 0;
    for (const jid of orderedTargets) {
        try {
            await currentSock.sendMessage(jid, {
                video: { url: filePath },
                mimetype: 'video/mp4',
                fileName,
                caption
            });
            sentCount++;
            await new Promise((r) => setTimeout(r, 800)); // gentle pacing between groups
        } catch (e) {
            console.error(`[news] send failed -> ${jid} (${fileName}):`, e.message);
        }
    }
    return sentCount;
}

// -----------------------------------------------------------------------------
// SCHEDULED AUTO-RECORDING (cron)
// -----------------------------------------------------------------------------
async function runScheduledSlot(hour24) {
    const cfg = await malik_getNewsConfig(currentSessionId);
    if (!cfg?.enabled) return;

    cachedMaxConcurrent = Math.max(1, cfg.maxConcurrentRecordings || 2);

    const enabledChannels = (cfg.enabledChannels?.length ? cfg.enabledChannels : CHANNEL_KEYS)
        .filter((k) => CHANNELS[k]);
    const maxDurationMinutes = cfg.maxDurationMinutes || 30;

    // Drop anything still waiting from a PREVIOUS slot instead of letting
    // the backlog grow forever. Already-recording channels are left alone
    // and finish normally -- only never-started, queued entries are cleared.
    if (pendingQueue.length) {
        const dropped = pendingQueue.map((q) => q.key);
        pendingQueue.length = 0;
        console.log(`[news] ⚠️ dropping stale queued channel(s) from a previous slot (never got a free concurrency slot): ${dropped.join(', ')}. Consider raising concurrency with \`.news concurrency <n>\` if this keeps happening.`);
    }

    const slotTag = `slot-${hour24}-${Date.now()}`;
    console.log(`[news] ⏰ scheduled slot ${hour24}:00 PKT -- requesting: ${enabledChannels.join(', ')} (concurrency limit: ${cachedMaxConcurrent})`);
    for (const key of enabledChannels) {
        requestRecording(key, { scheduledHour: hour24, maxDurationMinutes, slotTag });
    }
}

function scheduleCron() {
    if (cronRegistered) return;
    cronRegistered = true;

    // Subha: 06, 08, 10 | Dhupair: 12, 15 | Sham: 18 | Raat: 21, 00 (midnight)
    const slots = [6, 8, 10, 12, 15, 18, 21, 0];
    slots.forEach((hour) => {
        cron.schedule(`0 ${hour} * * *`, () => runScheduledSlot(hour), TZ_OPTS);
    });

    console.log('📹 News-recording cron registered (Asia/Karachi): 06,08,10,12,15,18,21,00 -- each recording auto-stops & uploads after the configured max duration (default 30 min) unless stopped manually first.');
}

// -----------------------------------------------------------------------------
// PUBLIC API
// -----------------------------------------------------------------------------
function init(sock, sessionId) {
    currentSock = sock;
    currentSessionId = sessionId;
    // Load the configured concurrency cap right away so even a
    // dyno-restart-then-immediate-manual-start respects it correctly.
    // Guarded so it can never clobber a `.news concurrency <n>` command
    // that runs before this DB read resolves.
    malik_getNewsConfig(sessionId).then((cfg) => {
        if (concurrencySetManually) return;
        cachedMaxConcurrent = Math.max(1, cfg?.maxConcurrentRecordings || 2);
    }).catch(() => {});
    scheduleCron();
}

// Lets the WhatsApp command layer push a live concurrency change (from
// `.news concurrency <n>`) without waiting for the next scheduled slot.
function setMaxConcurrent(n) {
    concurrencySetManually = true;
    cachedMaxConcurrent = Math.max(1, Math.min(5, Number(n) || 2));
    processQueue(); // in case the cap just went up and channels are waiting
    return cachedMaxConcurrent;
}

function updateSocket(sock) {
    currentSock = sock; // called again after a reconnect so sends use the fresh socket
}

async function getStatusText(sessionId) {
    const cfg = await malik_getNewsConfig(sessionId);
    if (!cfg) return '❌ Database not connected -- news status unavailable.';

    const status = cfg.enabled ? '🟢 ON' : '🔴 OFF';
    const primary = cfg.primaryGroups?.length ? cfg.primaryGroups.map((j, i) => `  ${i + 1}. ${j}`).join('\n') : '  None set (`.setprimarygroup jid1, jid2`)';
    const targets = cfg.targetJids?.length ? cfg.targetJids.map((j, i) => `  ${i + 1}. ${j}`).join('\n') : '  None set (`.news set jid1, jid2`)';
    const enabledChannels = cfg.enabledChannels?.length ? cfg.enabledChannels : CHANNEL_KEYS;
    const maxConcurrent = cfg.maxConcurrentRecordings || 2;
    const { active, queued } = getActiveStatus();
    const activeText = active.length
        ? active.map((a) => `  • ${a.label} — ${Math.floor(a.elapsedSeconds / 60)}m ${a.elapsedSeconds % 60}s / ${a.maxDurationMinutes}m`).join('\n')
        : '  None currently recording';
    const queuedText = queued.length
        ? queued.map((q) => `  • ${q.label} (waiting for a free slot)`).join('\n')
        : '  None waiting';

    let text = `📹 *NEWS RECORDING AUTO-SYSTEM*\n\n`;
    text += `*Status:* ${status}\n`;
    text += `*Max duration:* ${cfg.maxDurationMinutes || 30} minute(s) (auto-stop safety cap)\n`;
    text += `*Max concurrent recordings:* ${maxConcurrent} (prevents R14/memory-quota crashes)\n\n`;
    text += `*Primary Groups (uploaded first):*\n${primary}\n\n`;
    text += `*Other Target Groups:*\n${targets}\n\n`;
    text += `*Enabled Channels:* ${enabledChannels.join(', ')}\n`;
    text += `*All Channels:* ${CHANNEL_KEYS.join(', ')}\n\n`;
    text += `*Currently Recording (${active.length}/${maxConcurrent}):*\n${activeText}\n\n`;
    text += `*Waiting in Queue:*\n${queuedText}\n\n`;
    text += `*Last Run:* ${cfg.lastRun ? new Date(cfg.lastRun).toLocaleString('en-US', { timeZone: 'Asia/Karachi' }) : 'Never'}\n`;
    text += `*Last Summary:* ${cfg.lastRunSummary || '—'}\n\n`;
    text += `*Schedule (Asia/Karachi):* 06:00, 08:00, 10:00 (صبح) • 12:00, 15:00 (دوپہر) • 18:00 (شام) • 21:00, 00:00 (رات)\n\n`;
    text += `*Commands:*\n`;
    text += `• \`.setprimarygroup jid1, jid2\` — set primary groups (sent first)\n`;
    text += `• \`.news set jid1, jid2\` — set other target groups\n`;
    text += `• \`.news on / off\` — enable/disable the auto schedule\n`;
    text += `• \`.news start <key|all>\` — start recording right now (manual, queues if busy)\n`;
    text += `• \`.news stop <key|all>\` — stop + save + upload right now\n`;
    text += `• \`.news concurrency <n>\` — how many channels may record at once (default 2)\n`;
    text += `• \`.news enable <key>\` / \`.news disable <key>\` — toggle a channel in the auto schedule\n`;
    text += `• \`.news channels\` — list channel keys`;

    return text;
}

module.exports = {
    init,
    updateSocket,
    requestRecording,
    stopRecording,
    stopAll,
    getActiveStatus,
    setMaxConcurrent,
    CHANNELS,
    CHANNEL_KEYS,
    getStatusText
};
