const { spawn } = require('child_process');
const readline = require('readline');
const fs = require('fs');
const path = require('path');
const {
    malik_getCricketConfig,
    malik_updateCricketConfig
} = require('../maliklib/database');

const service = path.join(__dirname, '..', 'scripts', 'cricket_service.py');
const trackers = new Map();
const updateMessages = new Map();

function panel(title, lines) {
    return `┏━ 🏏 *${title}* ━┓\n${lines.map(line => `┃ ${line}`).join('\n')}\n┗━━━━━━━━━━━━━━━━━━┛`;
}

function parseJids(value) {
    return [...new Set(String(value || '').split(/[ ,]+/).map(item => item.trim()).filter(Boolean).map(item => {
        if (item.includes('@')) return item;
        return item.includes('-') ? `${item}@g.us` : `${item}@s.whatsapp.net`;
    }))];
}

function validStream(value) {
    try {
        const url = new URL(value);
        return ['http:', 'https:'].includes(url.protocol) && /\.m3u8(?:$|[?#])/i.test(url.pathname + url.search + url.hash);
    } catch {
        return false;
    }
}

function pythonProcess(args, env = process.env) {
    const command = process.platform === 'win32' ? 'python' : 'python3';
    return spawn(command, [service, ...args], { cwd: path.dirname(service), env, windowsHide: true });
}

async function stopTracker(sessionId) {
    const tracker = trackers.get(sessionId);
    if (!tracker) return;
    tracker.kill('SIGTERM');
    trackers.delete(sessionId);
}

async function sendClip(sock, targets, filePath, event, from, quoted) {
    if (!filePath || !fs.existsSync(filePath)) return;
    try {
        const caption = `🏏 *${event} CLIP*\n🎬 Auto cricket highlight\n© Powered By Qasim Cricket Bot`;
        for (const jid of targets) {
            await sock.sendMessage(jid, { video: { url: filePath }, mimetype: 'video/mp4', caption });
        }
    } finally {
        fs.promises.unlink(filePath).catch(() => {});
    }
}

async function startTracker(sock, from, context, cfg) {
    await stopTracker(context.sessionId);
    const tracker = pythonProcess(
        ['--track', cfg.matchId, '--stream', cfg.streamUrl, '--clips-dir', path.join(__dirname, '..', 'temp', 'cricket-clips')],
        { ...process.env, CRICKET_FOOTER: cfg.footerEnabled === false ? '' : (cfg.footer || '© Powered By Qasim Cricket Bot - 03434571953') }
    );
    trackers.set(context.sessionId, tracker);
    const lines = readline.createInterface({ input: tracker.stdout });
    lines.on('line', async line => {
        try {
            const result = JSON.parse(line);
            if (result.type !== 'update' || !result.text || !cfg.updateEnabled) return;
            const old = updateMessages.get(from);
            if (old) {
                await sock.sendMessage(from, { text: result.text, edit: old.key });
            } else {
                const sent = await sock.sendMessage(from, { text: result.text });
                updateMessages.set(from, sent);
            }
            if (result.clip) await sendClip(sock, cfg.targetJids || [], result.clip, result.event || 'HIGHLIGHT', from, context.malik_msg);
        } catch (error) {
            console.error('[cricket] tracker output error:', error.message);
        }
    });
    tracker.on('close', () => {
        if (trackers.get(context.sessionId) === tracker) trackers.delete(context.sessionId);
    });
    tracker.stderr.on('data', data => console.error(`[cricket] ${data}`));
}

async function fetchMatches(sock, from, quoted) {
    const child = pythonProcess(['--live']);
    let output = '';
    child.stdout.on('data', data => { output += data.toString(); });
    child.on('close', async () => {
        try {
            const result = JSON.parse(output.trim().split(/\r?\n/).pop());
            const lines = result.matches?.length ? result.matches.map((match, index) => `${index + 1}. ${match.name}\n   ID: ${match.id}`) : ['No live matches found.'];
            await sock.sendMessage(from, { text: panel('LIVE MATCHES', lines) }, { quoted });
        } catch {
            await sock.sendMessage(from, { text: '❌ Could not fetch live matches right now.' }, { quoted });
        }
    });
}

module.exports = {
    name: 'cricket',
    aliases: ['livematches', 'setlivematch', 'setstream', 'startupdate', 'stopupdate', 'settarget', 'setfooter'],
    category: 'Information',
    desc: 'Live cricket scores and automatic event clips',
    malik_handler: async (sock, from, context) => {
        const command = context.malik_text.trim().slice(1).split(/\s+/)[0].toLowerCase();
        const args = context.malik_args;
        if (command === 'cricket' && !args.length) {
            return sock.sendMessage(from, { text: panel('CRICKET MENU', ['`.livematches` - list live matches and IDs', '`.setlivematch 138638` - choose match', '`.setstream <m3u8>` - set direct stream', '`.settarget jid1,jid2` - clip destinations', '`.startupdate` / `.stopupdate` - score updates', '`.setfooter text` or `.setfooter off`', '`.cricket ffmpeg` - clip recorder settings']) }, { quoted: context.malik_msg });
        }
        const config = await malik_getCricketConfig(context.sessionId) || {};
        const ownerOnly = ['setlivematch', 'setstream', 'startupdate', 'stopupdate', 'settarget', 'setfooter'];
        if (ownerOnly.includes(command) && !context.malik_isOwner) {
            return sock.sendMessage(from, { text: '❌ Owner access required.' }, { quoted: context.malik_msg });
        }
        if (command === 'livematches') return fetchMatches(sock, from, context.malik_msg);
        if (command === 'setlivematch') {
            const matchId = (args[0] || '').replace(/[()]/g, '');
            if (!/^\d+$/.test(matchId)) return sock.sendMessage(from, { text: 'Usage: `.setlivematch 138638`' }, { quoted: context.malik_msg });
            await malik_updateCricketConfig(context.sessionId, { matchId });
            return sock.sendMessage(from, { text: `✅ Live match set: *${matchId}*` }, { quoted: context.malik_msg });
        }
        if (command === 'setstream') {
            const streamUrl = args.join(' ').trim();
            if (!validStream(streamUrl)) return sock.sendMessage(from, { text: '❌ Send a direct HTTP/HTTPS `.m3u8` link only.' }, { quoted: context.malik_msg });
            await malik_updateCricketConfig(context.sessionId, { streamUrl });
            return sock.sendMessage(from, { text: '✅ Direct M3U8 stream saved.' }, { quoted: context.malik_msg });
        }
        if (command === 'settarget') {
            const targetJids = parseJids(args.join(' '));
            if (!targetJids.length) return sock.sendMessage(from, { text: 'Usage: `.settarget 12345@g.us,67890@g.us`' }, { quoted: context.malik_msg });
            await malik_updateCricketConfig(context.sessionId, { targetJids });
            return sock.sendMessage(from, { text: `✅ Clip targets saved: ${targetJids.length}` }, { quoted: context.malik_msg });
        }
        if (command === 'setfooter') {
            const value = args.join(' ').trim();
            const footerEnabled = value.toLowerCase() !== 'off';
            await malik_updateCricketConfig(context.sessionId, { footer: footerEnabled ? value : config.footer, footerEnabled });
            return sock.sendMessage(from, { text: footerEnabled ? '✅ Footer updated.' : '✅ Footer disabled.' }, { quoted: context.malik_msg });
        }
        if (command === 'startupdate') {
            if (!config.matchId) return sock.sendMessage(from, { text: '❌ Set a match first: `.setlivematch 138638`' }, { quoted: context.malik_msg });
            if (!validStream(config.streamUrl)) return sock.sendMessage(from, { text: '❌ Set a direct M3U8 stream first: `.setstream <link>`' }, { quoted: context.malik_msg });
            await malik_updateCricketConfig(context.sessionId, { updateEnabled: true });
            config.updateEnabled = true;
            await startTracker(sock, from, context, config);
            return sock.sendMessage(from, { text: panel('CRICKET UPDATES', ['✅ Started', `Match: ${config.matchId}`, 'One detailed commentary per new ball', 'Use `.stopupdate` to stop']) }, { quoted: context.malik_msg });
        }
        if (command === 'stopupdate') {
            await stopTracker(context.sessionId);
            await malik_updateCricketConfig(context.sessionId, { updateEnabled: false });
            return sock.sendMessage(from, { text: '🛑 Cricket updates stopped.' }, { quoted: context.malik_msg });
        }
        if (command === 'cricket' && args[0]?.toLowerCase() === 'ffmpeg') {
            return sock.sendMessage(from, { text: panel('FFMPEG CLIPS', ['Editable file: `scripts/cricket_ffmpeg.py`', 'Clip: 10 seconds before + 25 seconds after', 'Events: WICKET, SIX, FOUR', 'Use `.setstream <direct .m3u8>` to enable recording']) }, { quoted: context.malik_msg });
        }
        return sock.sendMessage(from, { text: panel('CRICKET MENU', ['`.livematches` - list live matches and IDs', '`.setlivematch 138638` - choose match', '`.setstream <m3u8>` - set direct stream', '`.settarget jid1,jid2` - clip destinations', '`.startupdate` / `.stopupdate` - score updates', '`.setfooter text` or `.setfooter off`', '`.cricket ffmpeg` - clip recorder settings']) }, { quoted: context.malik_msg });
    }
};
