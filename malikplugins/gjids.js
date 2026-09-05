/**
 * ⚡ MQR MD AUTOFORWARD BOT ⚡
 * Groups JID Utility
 * MQR MD WhatsApp automation
 */
module.exports = {
    name: 'gjids',
    aliases: ['gjid'],
    category: 'Tools',
    desc: 'List all groups and their JIDs',
    malik_handler: async (malik_sock, malik_sender) => {
        try {
            // Fetch all participating groups
            const allGroupsObj = await malik_sock.groupFetchAllParticipating(); 
            const groupChats = Object.values(allGroupsObj); // convert object to array

            if (groupChats.length === 0) {
                return await malik_sock.sendMessage(malik_sender, { text: '╭━━━〔 🧰 *GROUP DIRECTORY* 〕━━━╮\n┃ ℹ️ No groups found.\n╰━━━━━━━━━━━━━━━━━━━━━━╯' });
            }

            // Build the message
            let msg = '╭━━━〔 🧰 *GROUP DIRECTORY* 〕━━━╮\n┃ 📚 *YOUR GROUPS & JIDS*\n╰━━━━━━━━━━━━━━━━━━━━━━╯\n\n';
            groupChats.forEach((group, index) => {
                msg += `${index + 1}. ${group.subject} — ${group.id}\n`;
            });

            // Send the message
            await malik_sock.sendMessage(malik_sender, { text: msg });
        } catch (error) {
            console.error(error);
            await malik_sock.sendMessage(malik_sender, { text: '╭━━━〔 🧰 *GROUP DIRECTORY* 〕━━━╮\n┃ ❌ Could not fetch groups.\n╰━━━━━━━━━━━━━━━━━━━━━━╯' });
        }
    }
};
