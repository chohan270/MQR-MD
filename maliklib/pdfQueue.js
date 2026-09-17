'use strict';

const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');
const { downloadMediaMessage } = require('@whiskeysockets/baileys');
const {
    malik_addPdfQueueItem,
    malik_listPdfQueue,
    malik_claimPdfQueueItem,
    malik_updatePdfQueueItem,
    malik_getEpaperConfig
} = require('./database');

const PDF_QUEUE_RETENTION_HOURS = 8;
const RETENTION_MS = PDF_QUEUE_RETENTION_HOURS * 60 * 60 * 1000;
const messageCache = new Map();
let processingTail = Promise.resolve();

function sanitizePdfFileName(fileName) {
    const raw = String(fileName || '').trim();
    if (!raw) return 'document.pdf';
    const extMatch = raw.match(/(\.[A-Za-z0-9]+)$/);
    const extension = extMatch ? extMatch[1].toLowerCase() : '.pdf';
    const base = extMatch ? raw.slice(0, -extMatch[1].length) : raw;
    const cleaned = base
        .replace(/(?i)(?:^|[\s._-])mw(?:[\s._-]|$)/g, ' ')
        .replace(/(?i)(?:^|[\s._-])m\.?w\.?(?:[\s._-]|$)/g, ' ')
        .replace(/[\s._-]+/g, ' ')
        .replace(/^\s+|\s+$/g, '')
        .replace(/^[._-]+|[._-]+$/g, '');
    return `${cleaned || 'document'}${extension}`;
}

function messageKey(key) {
    return `${key.remoteJid || ''}:${key.id || ''}`;
}

function rememberPdf(message) {
    const document = message?.message?.documentMessage;
    if (!document || document.mimetype !== 'application/pdf' && !document.fileName?.toLowerCase().endsWith('.pdf')) return null;
    const key = messageKey(message.key);
    const fileName = sanitizePdfFileName(document.fileName || `${message.key.id}.pdf`);
    messageCache.set(key, { message, expiresAt: Date.now() + RETENTION_MS });
    return {
        messageKey: key,
        remoteJid: message.key.remoteJid,
        messageId: message.key.id,
        participant: message.key.participant || '',
        fileName,
        mimetype: document.mimetype || 'application/pdf',
        receivedAt: new Date(message.messageTimestamp ? Number(message.messageTimestamp) * 1000 : Date.now())
    };
}

async function rememberAndQueue(sessionId, message) {
    const item = rememberPdf(message);
    return item ? malik_addPdfQueueItem(sessionId, item) : null;
}

async function resolveMessage(sock, item) {
    const cached = messageCache.get(item.messageKey);
    if (cached && cached.expiresAt > Date.now()) return cached.message;
    messageCache.delete(item.messageKey);

    const key = { remoteJid: item.remoteJid, id: item.messageId, participant: item.participant || undefined };
    if (typeof sock.loadMessage === 'function') {
        try {
            const loaded = await sock.loadMessage(item.remoteJid, item.messageId);
            if (loaded?.message) return loaded;
        } catch (error) {
            console.warn(`[PDF-QUEUE] message lookup failed: ${error.message}`);
        }
    }
    if (typeof sock.fetchMessageHistory === 'function') {
        try {
            const history = await sock.fetchMessageHistory(100, key, 0);
            const found = history?.find((entry) => entry.key?.id === item.messageId && entry.message);
            if (found) return found;
        } catch (error) {
            console.warn(`[PDF-QUEUE] history lookup failed: ${error.message}`);
        }
    }
    return null;
}

function runMw(inputPath, outputPath) {
    return new Promise((resolve, reject) => {
        const python = process.env.PYTHON_BIN || 'python3';
        const script = path.join(__dirname, '..', 'scripts', 'mw.py');
        const child = spawn(python, [script, '--input', inputPath, '--output', outputPath], { cwd: path.dirname(script) });
        let stderr = '';
        child.stderr.on('data', (chunk) => { stderr += chunk.toString(); });
        child.on('error', reject);
        child.on('close', (code) => code === 0 ? resolve() : reject(new Error(stderr || `mw.py exited with ${code}`)));
    });
}

async function processOne(sock, sessionId, item, targets) {
    const claimed = await malik_claimPdfQueueItem(sessionId, item._id);
    if (!claimed) return { status: 'skipped' };

    const workDir = path.join('/tmp', 'mqr_pdf_queue');
    const safeName = String(claimed.fileName).replace(/[^a-zA-Z0-9._-]/g, '_');
    const base = `${Date.now()}-${safeName}`;
    const inputPath = path.join(workDir, `input-${base}`);
    const outputPath = path.join(workDir, `output-${base}`);
    const thumbPath = outputPath.replace(/\.pdf$/i, '.thumb.jpg');
    try {
        const source = await resolveMessage(sock, claimed);
        if (!source) throw new Error('Original PDF message is no longer available on WhatsApp');
        const buffer = await downloadMediaMessage(source, 'buffer', {}, { logger: console });
        await fs.promises.mkdir(workDir, { recursive: true });
        await fs.promises.writeFile(inputPath, buffer);
        await runMw(inputPath, outputPath);
        let jpegThumbnail;
        try {
            jpegThumbnail = await fs.promises.readFile(thumbPath);
        } catch {
            jpegThumbnail = undefined;
        }
        for (const targetJid of targets) {
            await sock.sendMessage(targetJid, {
                document: { url: outputPath },
                mimetype: 'application/pdf',
                fileName: claimed.fileName,
                ...(jpegThumbnail ? { jpegThumbnail } : {})
            });
        }
        await malik_updatePdfQueueItem(sessionId, claimed._id, 'sent');
        return { status: 'sent', fileName: claimed.fileName };
    } catch (error) {
        await malik_updatePdfQueueItem(sessionId, claimed._id, 'failed', error.message);
        return { status: 'failed', fileName: claimed.fileName, error: error.message };
    } finally {
        await fs.promises.rm(inputPath, { force: true }).catch(() => {});
        await fs.promises.rm(outputPath, { force: true }).catch(() => {});
        await fs.promises.rm(thumbPath, { force: true }).catch(() => {});
    }
}

async function processItems(sock, sessionId, ids) {
    const cfg = await malik_getEpaperConfig(sessionId);
    const targets = cfg?.targetJids || [];
    if (!targets.length) throw new Error('E-paper target groups are not configured');
    const items = await malik_listPdfQueue(sessionId, new Date(Date.now() - RETENTION_MS));
    const selected = ids === 'all'
        ? items
        : items.filter((item, index) => ids.includes(String(index + 1)) || ids.includes(String(item._id)));
    const run = processingTail.then(async () => {
        const results = [];
        for (const item of selected) results.push(await processOne(sock, sessionId, item, targets));
        return results;
    });
    processingTail = run.catch(() => {});
    return run;
}

function listItems(sessionId) {
    return malik_listPdfQueue(sessionId, new Date(Date.now() - RETENTION_MS));
}

function cleanupMemory() {
    const now = Date.now();
    for (const [key, value] of messageCache) if (value.expiresAt <= now) messageCache.delete(key);
}
setInterval(cleanupMemory, 10 * 60 * 1000).unref();

module.exports = { rememberAndQueue, listItems, processItems };
