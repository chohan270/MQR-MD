/**
 * ⚡ MALIK MD AUTOFORWARD BOT ⚡
 * Set Primary Group(s) for the News Recording Auto-System
 * Usage: .setprimarygroup jid1, jid2
 * These groups always receive the recorded news video FIRST, before any
 * of the other ("baqi") groups set via `.news set`.
 * Developed by Mr Malik (ixxmalik)
 */
const { malik_getNewsConfig, malik_updateNewsConfig } = require('../maliklib/database');

function parseJids(input) {
    const matches = input.match(/\d{5,}(-\d+)?(@g\.us|@s\.whatsapp\.net)?/g) || [];
    const jids = matches.map((m) => {
        if (m.includes('@')) return m;
        return m.includes('-') ? `${m}@g.us` : `${m}@s.whatsapp.net`;
    });
    return [...new Set(jids)];
}

module.exports = {
    name: 'setprimarygroup',
    aliases: ['spg', 'setprimarygroups'],
    category: 'Group',
    desc: 'Set the primary group(s) that receive the recorded news video first',
    malik_handler: async (sock, from, context) => {
        const { malik_msg, malik_args, malik_isOwner, sessionId } = context;

        if (!malik_isOwner) {
            return await sock.sendMessage(from, { text: '❌ Only the bot owner can set the primary group(s).' }, { quoted: malik_msg });
        }

        const raw = malik_args.join(' ');

        if (!raw) {
            const cfg = await malik_getNewsConfig(sessionId);
            const current = cfg?.primaryGroups?.length ? cfg.primaryGroups.map((j, i) => `${i + 1}. ${j}`).join('\n') : 'None set';
            return await sock.sendMessage(from, {
                text: `❌ Provide JIDs.\nExample:\n\`.setprimarygroup 12345@g.us, 67890@g.us\`\n\n*Current primary group(s):*\n${current}`
            }, { quoted: malik_msg });
        }

        if (raw.toLowerCase() === 'clear') {
            await malik_updateNewsConfig(sessionId, { primaryGroups: [] });
            return await sock.sendMessage(from, { text: '✅ Primary group list cleared.' }, { quoted: malik_msg });
        }

        const jids = parseJids(raw);
        if (!jids.length) {
            return await sock.sendMessage(from, { text: '❌ No valid JIDs found.' }, { quoted: malik_msg });
        }

        await malik_updateNewsConfig(sessionId, { primaryGroups: jids });
        return await sock.sendMessage(from, {
            text: `✅ *Primary group(s) set* (${jids.length}) — these get every recorded news video FIRST:\n\n${jids.map((j, i) => `${i + 1}. ${j}`).join('\n')}\n\n_Other groups (set via \`.news set\`) receive it right after._`
        }, { quoted: malik_msg });
    }
};
