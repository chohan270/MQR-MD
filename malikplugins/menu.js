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
        for (const [key, plugin] of malik_plugins.entries()) {
            if (handledCommands.has(plugin.name)) continue;
            handledCommands.add(plugin.name);
            
            const category = plugin.category || 'General';
            if (!categories[category]) categories[category] = [];
            categories[category].push(plugin);
        }

        let menuText = `+================================+\n`;
        menuText += `|        MALIK COMMANDS         |\n`;
        menuText += `+--------------------------------+\n`;
        menuText += `| User: @${malik_sender.split('@')[0]}\n`;
        menuText += `| Prefix: .   Total: ${handledCommands.size}\n`;
        menuText += `+================================+\n\n`;
        
        for (const [category, plugins] of Object.entries(categories)) {
            menuText += `+--[ ${category.toUpperCase()} ]----------------+\n`;
            plugins.forEach(cmd => {
                menuText += `| .${cmd.name.padEnd(18)} ${(cmd.desc || '').slice(0, 13)}\n`;
            });
            menuText += `+--------------------------------+\n\n`;
        }
        
        menuText += `- Malik MD / focused forwarding -`;

        await malik_sock.sendMessage(malik_origin, { 
            text: menuText,
            mentions: [malik_sender]
        });
    }
};
