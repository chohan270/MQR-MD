/**
 * ⚡ MQR MD AUTOFORWARD BOT ⚡
 * Auto-Forward Command with Global Support
 * MQR MD WhatsApp automation
 */
const { malik_updateGroupSettings, malik_getGroupSettings, malik_getGlobalAutoForward, malik_updateGlobalAutoForward, malik_getEpaperConfig, malik_updateEpaperConfig, malik_clearEpaperSentToday } = require('../maliklib/database');
const epaperEngine = require('../maliklib/epaperEngine');
const pdfQueue = require('../maliklib/pdfQueue');

/**
 * Helper: extract JIDs from free-form text. Pulls out digit-sequences that
 * look like a JID (with or without an @g.us/@s.whatsapp.net suffix already
 * attached) and ignores any stray words typed around them — e.g.
 * "target jid 12345-6789@g.us" still correctly yields "12345-6789@g.us".
 */
function parseJids(input) {
    const matches = input.match(/\d{5,}(-\d+)?(@g\.us|@s\.whatsapp\.net)?/g) || [];
    const jids = matches.map((m) => {
        if (m.includes('@')) return m;
        return m.includes('-') ? `${m}@g.us` : `${m}@s.whatsapp.net`;
    });
    return [...new Set(jids)];
}

function commandPanel(title, lines) {
    return `╭━━━〔 🔄 *${title}* 〕━━━╮\n${lines.map((line) => `┃ ${line}`).join('\n')}\n╰━━━━━━━━━━━━━━━━━━━━━━╯`;
}

module.exports = {
    name: 'autoforward',
    description: 'Auto-forward messages from source groups to targets — works even without admin',
    aliases: ['af', 'autof', 'mw'],
    category: 'Group',
    malik_handler: async (sock, from, context) => {
        const { malik_msg, malik_args, malik_command, malik_isAdmin, malik_isOwner, malik_isSudo, malik_isGroup, sessionId } = context;

        const action = malik_args[0]?.toLowerCase();
        const sub = malik_args[1]?.toLowerCase();

        // ─────────────────────────────────────────────────────────────────────
        // OWNER PDF QUEUE (works from the owner's private chat)
        // ─────────────────────────────────────────────────────────────────────
        if (malik_command === 'mw' || action === 'mw') {
            if (!malik_isOwner) {
                return await sock.sendMessage(from, { text: '❌ Owner access required.' }, { quoted: malik_msg });
            }
            if (malik_isGroup) {
                return await sock.sendMessage(from, { text: 'ℹ️ PDF commands sirf bot ki private chat mein use karein.' }, { quoted: malik_msg });
            }

            const mwArgs = malik_command === 'mw' ? malik_args : malik_args.slice(1);
            const mwAction = mwArgs[0]?.toLowerCase();
            const items = await pdfQueue.listItems(sessionId);
            if (!mwAction || mwAction === 'list') {
                if (!items.length) return await sock.sendMessage(from, { text: '📥 Last 24 hours mein koi pending PDF nahi hai.' }, { quoted: malik_msg });
                const lines = items.map((item, index) => {
                    const source = item.remoteJid?.endsWith('@g.us') ? `group ${item.remoteJid}` : `chat ${item.remoteJid}`;
                    return `${index + 1}. ${item.fileName}\n   ${source} | ${new Date(item.receivedAt).toLocaleString('en-GB', { timeZone: 'Asia/Karachi' })}`;
                });
                return await sock.sendMessage(from, {
                    text: `📋 *PDF Queue (last 24 hours)*\n\n${lines.join('\n')}\n\nUse: *.mw process 1,2,3* or *.mw process all*`
                }, { quoted: malik_msg });
            }

            if (mwAction === 'process') {
                const selection = mwArgs.slice(1).join('').toLowerCase();
                if (!selection) return await sock.sendMessage(from, { text: '❌ Use `.mw process 1,2,3` or `.mw process all`.' }, { quoted: malik_msg });
                const ids = selection === 'all' ? 'all' : [...new Set(selection.split(',').map((value) => value.trim()).filter(Boolean))];
                await sock.sendMessage(from, { text: `⏳ ${selection === 'all' ? 'All pending PDFs' : `PDFs ${ids.join(', ')}`} queue mein process ho rahi hain...` }, { quoted: malik_msg });
                pdfQueue.processItems(sock, sessionId, ids).then(async (results) => {
                    const sent = results.filter((result) => result.status === 'sent').length;
                    const failed = results.filter((result) => result.status === 'failed');
                    let report = `✅ Complete\n📤 Sent: ${sent}`;
                    if (failed.length) report += `\n❌ Failed: ${failed.map((result) => `${result.fileName}: ${result.error}`).join('\n')}`;
                    await sock.sendMessage(from, { text: report }).catch(() => {});
                }).catch(async (error) => {
                    await sock.sendMessage(from, { text: `❌ PDF queue failed: ${error.message}` }).catch(() => {});
                });
                return;
            }

            return await sock.sendMessage(from, { text: '❓ Use `.mw list`, `.mw process 1,2` or `.mw process all`.' }, { quoted: malik_msg });
        }

        // ─────────────────────────────────────────────────────────────────────
        // GLOBAL SET COMMANDS (owner-only)
        // ─────────────────────────────────────────────────────────────────────
        if (action === 'set' && (sub === 'source_jids' || sub === 'target_jids')) {
            if (!malik_isOwner) {
                return await sock.sendMessage(from, { text: commandPanel('GLOBAL FORWARD', ['❌ Owner access required.']) }, { quoted: malik_msg });
            }

            const raw = malik_args.slice(2).join(' ');
            if (!raw) {
                return await sock.sendMessage(from, {
                    text: commandPanel('GLOBAL FORWARD', [`❌ Provide JIDs.`, `Example: .af set ${sub} 12345@g.us, 67890@g.us`])
                }, { quoted: malik_msg });
            }

            const jids = parseJids(raw);
            if (!jids.length) {
                return await sock.sendMessage(from, { text: commandPanel('GLOBAL FORWARD', ['❌ No valid JIDs found.']) }, { quoted: malik_msg });
            }

            const field = sub === 'source_jids' ? 'sourceJids' : 'targetJids';
            await malik_updateGlobalAutoForward(sessionId, { [field]: jids });

            return await sock.sendMessage(from, {
                text: commandPanel('GLOBAL FORWARD', [`✅ ${sub} updated`, '', ...jids.map((j, i) => `${i + 1}. ${j}`)])
            }, { quoted: malik_msg });
        }

        // ─────────────────────────────────────────────────────────────────────
        // EPAPER AUTOMATION (owner-only)
        // ─────────────────────────────────────────────────────────────────────
        if (action === 'epaper') {
            if (!malik_isOwner) {
                return await sock.sendMessage(from, { text: commandPanel('EPAPER CONTROL', ['❌ Owner access required.']) }, { quoted: malik_msg });
            }

            if (sub === 'set') {
                const raw = malik_args.slice(2).join(' ');
                if (!raw) {
                    return await sock.sendMessage(from, {
                        text: commandPanel('EPAPER CONTROL', ['❌ Provide target group JIDs.', 'Example: .af epaper set 12345@g.us, 67890@g.us'])
                    }, { quoted: malik_msg });
                }
                const jids = parseJids(raw);
                if (!jids.length) {
                    return await sock.sendMessage(from, { text: commandPanel('EPAPER CONTROL', ['❌ No valid JIDs found.']) }, { quoted: malik_msg });
                }
                await malik_updateEpaperConfig(sessionId, { targetJids: jids });
                return await sock.sendMessage(from, {
                    text: commandPanel('EPAPER CONTROL', [`✅ Target groups updated (${jids.length})`, ...jids.map((j, i) => `${i + 1}. ${j}`)])
                }, { quoted: malik_msg });
            }

            if (sub === 'on' || sub === 'off') {
                await malik_updateEpaperConfig(sessionId, { enabled: sub === 'on' });
                return await sock.sendMessage(from, { text: commandPanel('EPAPER CONTROL', [`✅ Auto-system ${sub.toUpperCase()}.`]) }, { quoted: malik_msg });
            }

            if (sub === 'run') {
                const testKeys = malik_args.slice(2).map((k) => k.toLowerCase()).filter(Boolean);

                if (testKeys.length) {
                    const invalid = testKeys.filter((k) => !epaperEngine.EPAPER_KEYS.includes(k));
                    if (invalid.length) {
                        return await sock.sendMessage(from, {
                            text: `❌ Unknown key(s): ${invalid.join(', ')}\n\nType \`.af epaper keys\` to see the full list.`
                        }, { quoted: malik_msg });
                    }
                    await sock.sendMessage(from, { text: `🧪 Testing: *${testKeys.join(', ')}* — download shuru ho gaya, thora wait karein...` }, { quoted: malik_msg });
                    epaperEngine.runSpecific(testKeys)
                        .then(async ({ sentCount, okKeys, failedKeys }) => {
                            let report = `🧪 *Test Result*\n\n`;
                            if (okKeys.length) report += `✅ Success: ${okKeys.join(', ')}\n`;
                            if (failedKeys.length) report += `❌ Failed: ${failedKeys.join(', ')} (retry queue mein daal diya)\n`;
                            report += `\n📤 Files sent: ${sentCount}`;
                            await sock.sendMessage(from, { text: report }, { quoted: malik_msg }).catch(() => {});
                        })
                        .catch((e) => console.error('[epaper] test run error:', e));
                    return;
                }

                await sock.sendMessage(from, { text: '🚀 Manual epaper run start ho gaya — Express, Baqi aur pending retries sab abhi chalenge. Har newspaper WhatsApp par khud hi aa jayegi jaise ready hogi.' }, { quoted: malik_msg });
                epaperEngine.manualRun().catch((e) => console.error('[epaper] manual run error:', e));
                return;
            }

            if (sub === 'keys') {
                return await sock.sendMessage(from, {
                    text: `📋 *Available Epaper Keys*\n\n${epaperEngine.EPAPER_KEYS.map((k) => `• ${k}`).join('\n')}\n\nExample: \`.af epaper run jang\` or \`.af epaper run jang dawn\``
                }, { quoted: malik_msg });
            }

            if (sub === 'clearsent') {
                const today = new Date().toLocaleString('en-CA', { timeZone: 'Asia/Karachi' }).split(',')[0];
                const count = await malik_clearEpaperSentToday(sessionId, today);
                return await sock.sendMessage(from, {
                    text: `🧹 Aaj ke ${count} "sent" record(s) clear kar diye — ab dobara test/send ho sakega.`
                }, { quoted: malik_msg });
            }

            // No sub-command -> show status
            const statusText = await epaperEngine.getStatusText(sessionId);
            return await sock.sendMessage(from, { text: statusText }, { quoted: malik_msg });
        }

        // ─────────────────────────────────────────────────────────────────────
        // GLOBAL STATUS & TOGGLE
        // ─────────────────────────────────────────────────────────────────────
        if (action === 'global') {
            if (!malik_isOwner) {
                return await sock.sendMessage(from, { text: '❌ Only the bot owner can manage global auto-forward.' }, { quoted: malik_msg });
            }

            if (sub === 'on' || sub === 'off') {
                await malik_updateGlobalAutoForward(sessionId, { enabled: sub === 'on' });
                return await sock.sendMessage(from, {
                    text: commandPanel('GLOBAL FORWARD', [`✅ Auto-forward ${sub.toUpperCase()}.`])
                }, { quoted: malik_msg });
            }

            if (sub === 'timestamp') {
                const state = malik_args[2]?.toLowerCase();
                if (state !== 'on' && state !== 'off') return await sock.sendMessage(from, { text: commandPanel('GLOBAL FORWARD', ['❌ Usage: .af global timestamp on/off']) }, { quoted: malik_msg });
                await malik_updateGlobalAutoForward(sessionId, { autoForwardTimestamp: state === 'on' });
                return await sock.sendMessage(from, { text: commandPanel('GLOBAL FORWARD', [`✅ Timestamp ${state.toUpperCase()}.`]) }, { quoted: malik_msg });
            }

            // Show global status
            const gcfg = await malik_getGlobalAutoForward(sessionId);
            const status = gcfg?.enabled ? '🟢 ON' : '🔴 OFF';
            const tsStatus = gcfg?.autoForwardTimestamp ? '🟢 ON' : '🔴 OFF';
            const srcs = gcfg?.sourceJids?.length ? gcfg.sourceJids.join('\n  ') : 'None';
            const tgts = gcfg?.targetJids?.length ? gcfg.targetJids.join('\n  ') : 'None';

            const text = commandPanel('GLOBAL FORWARD', [
                `📡 Status: ${status}`,
                `🕒 Timestamp: ${tsStatus}`,
                '',
                `📥 Sources: ${srcs}`,
                `📤 Targets: ${tgts}`,
                '',
                'Commands: .af global on/off | .af global timestamp on/off',
                'Owner only: .af set source_jids / target_jids'
            ]);

            return await sock.sendMessage(from, { text }, { quoted: malik_msg });
        }

        // ─────────────────────────────────────────────────────────────────────
        // PER-GROUP COMMANDS
        // ─────────────────────────────────────────────────────────────────────
        if (!action) {
            const globalCfg = await malik_getGlobalAutoForward(sessionId);
            const gStatus = globalCfg?.enabled ? '🟢 ON' : '🔴 OFF';

            let text = commandPanel('FORWARD MANAGER', [`📡 Global mode: ${gStatus}`]);

            if (malik_isGroup) {
                const current = await malik_getGroupSettings(sessionId, from) || {};
                const pStatus = current.autoForward ? '🟢 ON' : '🔴 OFF';
                const targets = current.autoForwardTargets || [];

                text += `\n📌 This group: ${pStatus}\n`;
                text += `🎯 Targets: ${targets.length ? targets.join(', ') : 'None'}\n`;
            }

            text += `\n🧭 Commands\n┃ .af on/off • .af set jid1, jid2\n┃ Owner: .af global • .af epaper\n┗━━━━━━━━━━━━━━━━━━━━┛`;

            return await sock.sendMessage(from, { text }, { quoted: malik_msg });
        }

        if (!malik_isGroup) {
            return await sock.sendMessage(from, { text: '❌ Use this in a group or use `.af global`.' }, { quoted: malik_msg });
        }

        if (!malik_isAdmin && !malik_isOwner && !malik_isSudo) {
            return await sock.sendMessage(from, { text: '❌ Admin only.' }, { quoted: malik_msg });
        }

        const current = await malik_getGroupSettings(sessionId, from) || {};

        if (action === 'on') {
            if (!current.autoForwardTargets?.length) return await sock.sendMessage(from, { text: '⚠️ Set targets first.' }, { quoted: malik_msg });
            await malik_updateGroupSettings(sessionId, from, { autoForward: true });
            return await sock.sendMessage(from, { text: '✅ *Auto-Forward* enabled.' }, { quoted: malik_msg });
        }

        if (action === 'off') {
            await malik_updateGroupSettings(sessionId, from, { autoForward: false });
            return await sock.sendMessage(from, { text: '✅ *Auto-Forward* disabled.' }, { quoted: malik_msg });
        }

        if (action === 'set') {
            const input = malik_args.slice(1).join(' ');
            if (!input) return await sock.sendMessage(from, { text: '❌ Usage: `.af set jid1, jid2`' }, { quoted: malik_msg });
            const targets = parseJids(input);
            await malik_updateGroupSettings(sessionId, from, { autoForwardTargets: targets });
            return await sock.sendMessage(from, { text: `✅ Targets updated (${targets.length} JIDs).` }, { quoted: malik_msg });
        }

        if (action === 'clear') {
            await malik_updateGroupSettings(sessionId, from, {
                autoForwardTargets: [],
                autoForward: false
            });
            return await sock.sendMessage(from, { text: '✅ All group Auto-Forward settings cleared.' }, { quoted: malik_msg });
        }

        return await sock.sendMessage(from, { text: '❓ Unknown action. Type `.af` for help.' }, { quoted: malik_msg });
    }
};
