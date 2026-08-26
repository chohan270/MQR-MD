/**
 * ⚡ MALIK MD AUTOFORWARD BOT ⚡
 * Live News Recording Auto-System Command
 * Developed by Mr Malik (ixxmalik)
 */
const { malik_getNewsConfig, malik_updateNewsConfig } = require('../maliklib/database');
const newsEngine = require('../maliklib/newsEngine');

/**
 * Helper: extract JIDs from free-form text (same pattern used by .af).
 */
function parseJids(input) {
    const matches = input.match(/\d{5,}(-\d+)?(@g\.us|@s\.whatsapp\.net)?/g) || [];
    const jids = matches.map((m) => {
        if (m.includes('@')) return m;
        return m.includes('-') ? `${m}@g.us` : `${m}@s.whatsapp.net`;
    });
    return [...new Set(jids)];
}

module.exports = {
    name: 'news',
    description: 'Auto live-news recording + upload system (Samaa/Geo/Express/ARY/Khyber)',
    aliases: ['newsrecord'],
    category: 'Group',
    malik_handler: async (sock, from, context) => {
        const { malik_msg, malik_args, malik_isOwner, sessionId } = context;

        const action = malik_args[0]?.toLowerCase();
        const sub = malik_args[1]?.toLowerCase();

        if (!malik_isOwner) {
            // Status is safe to show to anyone; everything else is owner-only.
            if (!action) {
                const statusText = await newsEngine.getStatusText(sessionId);
                return await sock.sendMessage(from, { text: statusText }, { quoted: malik_msg });
            }
            return await sock.sendMessage(from, { text: '❌ Only the bot owner can manage the news recording system.' }, { quoted: malik_msg });
        }

        // ─────────────────────────────────────────────────────────────────
        // .news  (no args) -> status
        // ─────────────────────────────────────────────────────────────────
        if (!action) {
            const statusText = await newsEngine.getStatusText(sessionId);
            return await sock.sendMessage(from, { text: statusText }, { quoted: malik_msg });
        }

        // ─────────────────────────────────────────────────────────────────
        // .news on / off  -> toggle the auto (cron) schedule
        // ─────────────────────────────────────────────────────────────────
        if (action === 'on' || action === 'off') {
            await malik_updateNewsConfig(sessionId, { enabled: action === 'on' });
            return await sock.sendMessage(from, { text: `✅ News auto-recording schedule *${action.toUpperCase()}*.` }, { quoted: malik_msg });
        }

        // ─────────────────────────────────────────────────────────────────
        // .news set jid1, jid2  -> other ("baqi") target groups
        // ─────────────────────────────────────────────────────────────────
        if (action === 'set') {
            const raw = malik_args.slice(1).join(' ');
            if (!raw) {
                return await sock.sendMessage(from, {
                    text: '❌ Provide target group JIDs.\nExample:\n`.news set 12345@g.us, 67890@g.us`'
                }, { quoted: malik_msg });
            }
            const jids = parseJids(raw);
            if (!jids.length) {
                return await sock.sendMessage(from, { text: '❌ No valid JIDs found.' }, { quoted: malik_msg });
            }
            await malik_updateNewsConfig(sessionId, { targetJids: jids });
            return await sock.sendMessage(from, {
                text: `✅ *News target groups updated* (${jids.length})\n\n${jids.map((j, i) => `${i + 1}. ${j}`).join('\n')}\n\n_These receive the video AFTER the primary groups._`
            }, { quoted: malik_msg });
        }

        // ─────────────────────────────────────────────────────────────────
        // .news channels -> list keys + which are enabled for auto schedule
        // ─────────────────────────────────────────────────────────────────
        if (action === 'channels') {
            const cfg = await malik_getNewsConfig(sessionId);
            const enabled = cfg?.enabledChannels?.length ? cfg.enabledChannels : newsEngine.CHANNEL_KEYS;
            const lines = newsEngine.CHANNEL_KEYS.map((k) => {
                const ch = newsEngine.CHANNELS[k];
                const on = enabled.includes(k) ? '🟢' : '🔴';
                return `${on} \`${k}\` — ${ch.label} (${ch.urduLabel})`;
            });
            return await sock.sendMessage(from, {
                text: `📋 *News Channels*\n\n${lines.join('\n')}\n\nUse \`.news enable <key>\` / \`.news disable <key>\` to toggle a channel in the auto schedule.`
            }, { quoted: malik_msg });
        }

        // ─────────────────────────────────────────────────────────────────
        // .news enable/disable <key> -> which channels participate in cron
        // ─────────────────────────────────────────────────────────────────
        if (action === 'enable' || action === 'disable') {
            const key = sub;
            if (!key || !newsEngine.CHANNELS[key]) {
                return await sock.sendMessage(from, {
                    text: `❌ Unknown channel key.\nAvailable: ${newsEngine.CHANNEL_KEYS.join(', ')}`
                }, { quoted: malik_msg });
            }
            const cfg = await malik_getNewsConfig(sessionId);
            let list = cfg?.enabledChannels?.length ? [...cfg.enabledChannels] : [...newsEngine.CHANNEL_KEYS];
            if (action === 'enable') {
                if (!list.includes(key)) list.push(key);
            } else {
                list = list.filter((k) => k !== key);
            }
            await malik_updateNewsConfig(sessionId, { enabledChannels: list });
            return await sock.sendMessage(from, {
                text: `✅ *${key}* is now *${action === 'enable' ? 'ENABLED' : 'DISABLED'}* for the auto schedule.\n\nActive channels: ${list.length ? list.join(', ') : 'none'}`
            }, { quoted: malik_msg });
        }

        // ─────────────────────────────────────────────────────────────────
        // .news concurrency <n>  -> how many channels may record at once
        // (the main R14/memory-quota safety knob)
        // ─────────────────────────────────────────────────────────────────
        if (action === 'concurrency') {
            const n = parseInt(sub, 10);
            if (!sub || isNaN(n) || n < 1 || n > 5) {
                const cfg = await malik_getNewsConfig(sessionId);
                return await sock.sendMessage(from, {
                    text: `❌ Usage: \`.news concurrency <1-5>\`\n\nCurrent value: *${cfg?.maxConcurrentRecordings || 2}*\n\n_Lower = safer on small (512MB) dynos but takes longer to get through all channels. Higher = faster but more risk of an R14 (memory quota exceeded) crash._`
                }, { quoted: malik_msg });
            }
            await malik_updateNewsConfig(sessionId, { maxConcurrentRecordings: n });
            const applied = newsEngine.setMaxConcurrent(n);
            return await sock.sendMessage(from, {
                text: `✅ Max concurrent recordings set to *${applied}*. Applied immediately — any queued channels will start now if a slot is free.`
            }, { quoted: malik_msg });
        }

        // ─────────────────────────────────────────────────────────────────
        // .news start <key|all>  -> manual start (works anytime, not just
        // at the scheduled slots). Queues automatically if the concurrency
        // limit is already reached.
        // ─────────────────────────────────────────────────────────────────
        if (action === 'start') {
            if (!sub) {
                return await sock.sendMessage(from, {
                    text: `❌ Usage: \`.news start <key|all>\`\nAvailable keys: ${newsEngine.CHANNEL_KEYS.join(', ')}`
                }, { quoted: malik_msg });
            }
            const cfg = await malik_getNewsConfig(sessionId);
            const maxDurationMinutes = cfg?.maxDurationMinutes || 30;
            newsEngine.setMaxConcurrent(cfg?.maxConcurrentRecordings || 2);

            const keysToStart = sub === 'all' ? newsEngine.CHANNEL_KEYS : [sub];
            const invalid = keysToStart.filter((k) => !newsEngine.CHANNELS[k]);
            if (invalid.length) {
                return await sock.sendMessage(from, {
                    text: `❌ Unknown key(s): ${invalid.join(', ')}\nAvailable: ${newsEngine.CHANNEL_KEYS.join(', ')}`
                }, { quoted: malik_msg });
            }

            const results = keysToStart.map((k) => ({ k, r: newsEngine.requestRecording(k, { scheduledHour: null, maxDurationMinutes }) }));
            const startedKeys = results.filter((x) => x.r.started).map((x) => x.k);
            const queuedKeys = results.filter((x) => x.r.queued && x.r.reason !== 'already-queued').map((x) => x.k);
            const alreadyKeys = results.filter((x) => x.r.reason === 'already-recording' || x.r.reason === 'already-queued').map((x) => x.k);

            let msg = '';
            if (startedKeys.length) msg += `🔴 Recording started now: ${startedKeys.join(', ')} (auto-stop in ${maxDurationMinutes} min unless you \`.news stop\` first)\n`;
            if (queuedKeys.length) msg += `⏳ Queued (concurrency limit reached, will auto-start once a slot frees): ${queuedKeys.join(', ')}\n`;
            if (alreadyKeys.length) msg += `⚠️ Already recording/queued: ${alreadyKeys.join(', ')}`;
            return await sock.sendMessage(from, { text: msg.trim() || 'Nothing to start.' }, { quoted: malik_msg });
        }

        // ─────────────────────────────────────────────────────────────────
        // .news stop <key|all>  -> manual stop, saves + uploads immediately
        // ─────────────────────────────────────────────────────────────────
        if (action === 'stop') {
            if (!sub || sub === 'all') {
                const { stoppedActive, removedFromQueue } = newsEngine.stopAll();
                let msg = '';
                if (stoppedActive.length) msg += `⏹️ Stopping: ${stoppedActive.join(', ')} — file(s) will save and upload in a few seconds.\n`;
                if (removedFromQueue.length) msg += `🗑️ Removed from queue (hadn't started yet): ${removedFromQueue.join(', ')}`;
                return await sock.sendMessage(from, { text: msg.trim() || 'ℹ️ Nothing is currently recording or queued.' }, { quoted: malik_msg });
            }
            const r = newsEngine.stopRecording(sub);
            if (!r.stopped) {
                return await sock.sendMessage(from, { text: `ℹ️ *${sub}* is not currently recording or queued.` }, { quoted: malik_msg });
            }
            return await sock.sendMessage(from, {
                text: r.wasQueued
                    ? `🗑️ *${sub}* removed from the queue (hadn't started recording yet).`
                    : `⏹️ Stopping *${sub}* — file will save and upload in a few seconds.`
            }, { quoted: malik_msg });
        }

        // ─────────────────────────────────────────────────────────────────
        // .news status
        // ─────────────────────────────────────────────────────────────────
        if (action === 'status') {
            const statusText = await newsEngine.getStatusText(sessionId);
            return await sock.sendMessage(from, { text: statusText }, { quoted: malik_msg });
        }

        return await sock.sendMessage(from, { text: '❓ Unknown action. Type `.news` for help.' }, { quoted: malik_msg });
    }
};
