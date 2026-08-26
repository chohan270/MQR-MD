const { malik_getBotConfig, malik_updateBotConfig } = require('../maliklib/database');
const autoReact = require('../maliklib/autoReact');

module.exports = {
    name: 'autoreact',
    aliases: ['ar'],
    category: 'Tools',
    desc: 'React to incoming messages with random emojis',
    malik_handler: async (sock, from, context) => {
        const { malik_msg, malik_args, malik_isOwner, sessionId } = context;
        if (!malik_isOwner) {
            return await sock.sendMessage(from, { text: '❌ Owner access required.' }, { quoted: malik_msg });
        }

        const action = malik_args[0]?.toLowerCase();
        if (action !== 'on' && action !== 'off') {
            const cfg = await malik_getBotConfig(sessionId);
            const status = cfg?.autoReact ? '🟢 ON' : '🔴 OFF';
            return await sock.sendMessage(from, {
                text: `┏━ 🤝 *AUTO REACT* ━┓\n┃ Status: ${status}\n┃ Usage: .autoreact on/off\n┗━━━━━━━━━━━━━━━━━━┛`
            }, { quoted: malik_msg });
        }

        const active = action === 'on';
        autoReact.setEnabled(active);
        const saved = await malik_updateBotConfig(sessionId, { autoReact: active });
        return await sock.sendMessage(from, {
            text: `┏━ 🤝 *AUTO REACT* ━┓\n┃ ${active ? '✅ Random reactions enabled.' : '🛑 Random reactions disabled.'}\n┃ ${saved ? '💾 Setting saved.' : '⚠️ Runtime only; database save failed.'}\n┗━━━━━━━━━━━━━━━━━━┛`
        }, { quoted: malik_msg });
    }
};