/**
 * ⚡ MALIK MD AUTOFORWARD BOT ⚡
 * Uptime Command
 * Developed by Mr Malik (ixxmalik)
 */
module.exports = {
    name: 'uptime',
    category: 'Information',
    desc: 'Show the bot uptime',
    malik_handler: async (malik_sock, malik_origin, context) => {
        const uptimeSeconds = process.uptime();
        const days = Math.floor(uptimeSeconds / (3600 * 24));
        const hours = Math.floor((uptimeSeconds % (3600 * 24)) / 3600);
        const minutes = Math.floor((uptimeSeconds % 3600) / 60);
        const seconds = Math.floor(uptimeSeconds % 60);

        let uptimeStr = `┏━ ⏱️ *SYSTEM UPTIME* ━┓\n┃ 🤖 Malik MD is online\n┃ `;
        if (days > 0) uptimeStr += `📅 ${days}d `;
        if (hours > 0) uptimeStr += `🕒 ${hours}h `;
        if (minutes > 0) uptimeStr += `⏳ ${minutes}m `;
        uptimeStr += `⚡ ${seconds}s\n┗━━━━━━━━━━━━━━━━━━━━┛`;

        await malik_sock.sendMessage(malik_origin, { text: uptimeStr });
    }
};
