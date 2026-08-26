const REACTION_EMOJIS = [
    '👍', '😊', '😍', '👾', '🤖', '✍️', '⭐', '💫', '✨', '⚡', '💥', '🔥', '🌙',
    '📝', '🎈', '🎊', '📚', '🖊️', '🔍', '💝', '❤️‍🔥', '💯', '⚜️', '🔰', '♻️',
    '🌀', 'Ⓜ️', '💠', '❇️', '🆗', '☑️', '✔️', '♠️', '♣️', '🇵🇰'
];

let enabled = false;

function setEnabled(value) {
    enabled = Boolean(value);
    return enabled;
}

function isEnabled() {
    return enabled;
}

function randomEmoji() {
    return REACTION_EMOJIS[Math.floor(Math.random() * REACTION_EMOJIS.length)];
}

module.exports = { setEnabled, isEnabled, randomEmoji };