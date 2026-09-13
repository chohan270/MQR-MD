/**
 * ⚡ MQR MD AUTOFORWARD BOT ⚡
 * JID Utility
 * MQR MD WhatsApp automation
 */
module.exports = {
    name: 'jid',
    category: 'Debug',
    desc: 'Get the JID of the current chat',
    malik_handler: async (malik_sock, malik_sender) => {
        try {
            await malik_sock.sendMessage(malik_sender, { text: `╭━━━〔 🧪 *CHAT IDENTIFIER* 〕━━━╮\n┃ 🔗 ${malik_sender}\n╰━━━━━━━━━━━━━━━━━━━━━━╯` });
        } catch (error) {
            console.error('[JID] reply failed:', error.message);
        }
    }
};
