/**
 * Malik command hub.
 */
module.exports = {
    name: 'menu',
    aliases: ['help', 'h'],
    category: 'Information',
    desc: 'Show all available commands',
    malik_handler: async (malik_sock, malik_origin, context) => {
        const { malik_plugins, malik_sender } = context;
        
        const categories = {};
        const handledCommands = new Set();
        const categoryIcons = {
            Group: '👥',
            Tools: '🧰',
            Debug: '🧪',
            Information: '📚',
            General: '🧩'
        };
        
        for (const [key, plugin] of malik_plugins.entries()) {
            if (handledCommands.has(plugin.name)) continue;
            handledCommands.add(plugin.name);
            
            const category = plugin.category || 'General';
            if (!categories[category]) categories[category] = [];
            categories[category].push(plugin);
        }

        let menuText = `╭━━━〔 *MALIK COMMAND DECK* 〕━━━╮\n`;
        menuText += `┃ 👤 @${malik_sender.split('@')[0]}\n`;
        menuText += `┃ ⚙️ Prefix: .  •  ${handledCommands.size} commands\n`;
        menuText += `╰━━━━━━━━━━━━━━━━━━━━━━╯\n\n`;
        
        for (const category in categories) {
            const icon = categoryIcons[category] || categoryIcons.General;
            menuText += `╭─ ${icon} *${category.toUpperCase()}* ─╮\n`;
            categories[category].forEach(cmd => {
                menuText += `│  ${icon}  .${cmd.name}\n`;
            });
            menuText += `╰──────────────────╯\n\n`;
        }
        
        menuText += `> _Crafted for smooth forwarding • Malik MD_`;

        await malik_sock.sendMessage(malik_origin, { 
            text: menuText,
            mentions: [malik_sender]
        });
    }
};
