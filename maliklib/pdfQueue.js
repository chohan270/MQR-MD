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
    malik_deletePdfQueueItem,
    malik_getEpaperConfig,
    malik_claimSharedPdf,
    malik_markSharedPdfSent,
    malik_releaseSharedPdfClaim
} = require('./database');

const PDF_QUEUE_RETENTION_HOURS = 6;
const RETENTION_MS = PDF_QUEUE_RETENTION_HOURS * 60 * 60 * 1000;
const messageCache = new Map();
let processingTail = Promise.resolve();
const EXCLUDED_PDF_SOURCES = new Map([
    ['120363026226973835@g.us', new Set(['81131932283065@lid', '87424696897621@lid'])],
    ['923489517717-1546053015@g.us', new Set(['81131932283065@lid', '87424696897621@lid'])]
]);

function normalizeJid(jid) {
    return String(jid || '').toLowerCase().replace(/:\d+(?=@)/, '');
}

function isExcludedPdfSource(message) {
    const excludedSenders = EXCLUDED_PDF_SOURCES.get(normalizeJid(message?.key?.remoteJid));
    if (!excludedSenders) return false;
    const senders = [
        message.key.participant,
        message.key.participantAlt,
        message.key.participantPn,
        message.key.participantLid
    ].map(normalizeJid);
    return senders.some((sender) => sender && excludedSenders.has(sender));
}

function sanitizePdfFileName(fileName) {
    const raw = String(fileName || '').trim();
    if (!raw) return 'document.pdf';
    const extMatch = raw.match(/(\.[A-Za-z0-9]+)$/);
    const extension = extMatch ? extMatch[1].toLowerCase() : '.pdf';
    const base = extMatch ? raw.slice(0, -extMatch[1].length) : raw;
    const cleaned = base
        .replace(/(?:^|[\s._-])mw(?:[\s._-]|$)/gi, ' ')
        .replace(/(?:^|[\s._-])m\.?w\.?(?:[\s._-]|$)/gi, ' ')
        .replace(/[\s._-]+/g, ' ')
        .replace(/^\s+|\s+$/g, '')
        .replace(/^[._-]+|[._-]+$/g, '');
    const months = 'Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|June|July|August|September|October|November|December';
    const dateFirst = cleaned.match(new RegExp(`^(\\d{1,2})\\s+(${months})\\s+(.+)$`, 'i'));
    const normalized = dateFirst
        ? `${dateFirst[3].trim()} ${dateFirst[1]}${dateFirst[2]}`
        : cleaned;
    return `${normalized || 'document'}${extension}`;
}

function filterTargetGroups(targets, sourceJid) {
    const source = normalizeJid(sourceJid);
    return targets.filter((targetJid) => normalizeJid(targetJid) !== source);
}

function unwrapMessage(message) {
    let current = message;
    const wrappers = [
        'ephemeralMessage',
        'viewOnceMessage',
        'viewOnceMessageV2',
        'viewOnceMessageV2Extension',
        'documentWithCaptionMessage'
    ];
    while (current) {
        const wrapper = wrappers.find((name) => current[name]?.message);
        if (!wrapper) return current;
        current = current[wrapper].message;
    }
    return {};
}

function messageKey(key) {
    return `${key.remoteJid || ''}:${key.id || ''}`;
}

function rememberPdf(message) {
    if (isExcludedPdfSource(message)) return null;
    const document = unwrapMessage(message?.message).documentMessage;
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

function buildMwArgs(inputPath, outputPath) {
    const script = path.join(__dirname, '..', 'scripts', 'mw.py');
    return [script, '--input', inputPath, '--output', outputPath, '--skip-reference-images'];
}

function runMw(inputPath, outputPath) {
    return new Promise((resolve, reject) => {
        const python = process.env.PYTHON_BIN || 'python3';
        const script = path.join(__dirname, '..', 'scripts', 'mw.py');
        const child = spawn(python, buildMwArgs(inputPath, outputPath), { cwd: path.dirname(script) });
        let stdout = '';
        let stderr = '';
        child.stdout.on('data', (chunk) => { stdout += chunk.toString(); });
        child.stderr.on('data', (chunk) => { stderr += chunk.toString(); });
        child.on('error', reject);
        child.on('close', (code) => {
            if (code !== 0) return reject(new Error(stderr || `mw.py exited with ${code}`));
            resolve({ skipped: stdout.includes('MW_SKIPPED_REFERENCE_IMAGE:') });
        });
    });
}

async function processOne(sock, sessionId, item, targets) {
    const deliveryTargets = filterTargetGroups(targets, item.remoteJid);
    if (!deliveryTargets.length) {
        await malik_deletePdfQueueItem(sessionId, item._id);
        return { status: 'source-is-only-target', fileName: item.fileName };
    }

    const claimed = await malik_claimPdfQueueItem(sessionId, item._id);
    if (!claimed) return { status: 'skipped' };

    const workDir = path.join('/tmp', 'mqr_pdf_queue');
    const safeName = String(claimed.fileName).replace(/[^a-zA-Z0-9._-]/g, '_');
    const base = `${Date.now()}-${safeName}`;
    const inputPath = path.join(workDir, `input-${base}`);
    const outputPath = path.join(workDir, `output-${base}`);
    const thumbPath = outputPath.replace(/\.pdf$/i, '.thumb.jpg');
    let sharedClaim = null;
    let deliveredAny = false;
    try {
        sharedClaim = await malik_claimSharedPdf(sessionId, claimed.fileName, 'mw');
        if (!sharedClaim) {
            await malik_deletePdfQueueItem(sessionId, claimed._id);
            return { status: 'duplicate', fileName: claimed.fileName };
        }

        const source = await resolveMessage(sock, claimed);
        if (!source) throw new Error('Original PDF message is no longer available on WhatsApp');
        const buffer = await downloadMediaMessage(source, 'buffer', {}, { logger: console });
        await fs.promises.mkdir(workDir, { recursive: true });
        await fs.promises.writeFile(inputPath, buffer);
        const processing = await runMw(inputPath, outputPath);
        if (processing.skipped) {
            const released = await malik_releaseSharedPdfClaim(sessionId, sharedClaim);
            if (!released) throw new Error('Could not release the duplicate claim after skipping a reference image');
            const removed = await malik_deletePdfQueueItem(sessionId, claimed._id);
            if (!removed) throw new Error('Could not remove the skipped reference-image PDF from the queue');
            return { status: 'reference-image-skipped', fileName: claimed.fileName };
        }
        let jpegThumbnail;
        try {
            jpegThumbnail = await fs.promises.readFile(thumbPath);
        } catch {
            jpegThumbnail = undefined;
        }
        const deliveryErrors = [];
        for (const targetJid of deliveryTargets) {
            try {
                await sock.sendMessage(targetJid, {
                    document: { url: outputPath },
                    mimetype: 'application/pdf',
                    fileName: claimed.fileName,
                    ...(jpegThumbnail ? { jpegThumbnail } : {})
                });
                deliveredAny = true;
            } catch (error) {
                deliveryErrors.push(`${targetJid}: ${error.message}`);
                console.error(`[PDF-QUEUE] send failed for ${claimed.fileName} -> ${targetJid}: ${error.message}`);
            }
        }
        if (!deliveredAny) throw new Error(`PDF send failed for every target: ${deliveryErrors.join('; ')}`);
        const recorded = await malik_markSharedPdfSent(sessionId, sharedClaim, claimed.fileName, 'mw');
        if (!recorded) throw new Error('PDF was sent, but its shared duplicate record could not be saved');
        await malik_updatePdfQueueItem(sessionId, claimed._id, 'sent');
        await malik_deletePdfQueueItem(sessionId, claimed._id);
        return { status: 'sent', fileName: claimed.fileName, deliveryErrors };
    } catch (error) {
        if (sharedClaim && !deliveredAny) {
            await malik_releaseSharedPdfClaim(sessionId, sharedClaim).catch((releaseError) => {
                console.error(`[PDF-QUEUE] could not release duplicate claim for ${claimed.fileName}: ${releaseError.message}`);
            });
        }
        await malik_updatePdfQueueItem(sessionId, claimed._id, 'failed', error.message);
        return { status: 'failed', fileName: claimed.fileName, error: error.message };
    } finally {
        await fs.promises.rm(inputPath, { force: true }).catch(() => {});
        await fs.promises.rm(outputPath, { force: true }).catch(() => {});
        await fs.promises.rm(thumbPath, { force: true }).catch(() => {});
    }
}

async function processIncomingPdf(sock, sessionId, message) {
    if (isExcludedPdfSource(message)) return { status: 'excluded' };
    const item = await rememberAndQueue(sessionId, message);
    if (!item) throw new Error('Could not save the incoming PDF in the MongoDB queue');
    if (!String(message?.key?.remoteJid || '').endsWith('@g.us')) {
        return { status: 'queued', fileName: item.fileName };
    }

    const config = await malik_getEpaperConfig(sessionId);
    if (config?.mwAutoEnabled === false) return { status: 'queued', fileName: item.fileName };

    const targets = config?.targetJids || [];
    if (!targets.length) {
        const error = 'E-paper target groups are not configured';
        await malik_updatePdfQueueItem(sessionId, item._id, 'failed', error);
        return { status: 'failed', fileName: item.fileName, error };
    }

    const run = processingTail.then(() => processOne(sock, sessionId, item, targets));
    processingTail = run.catch(() => {});
    return run;
}

async function processItems(sock, sessionId, ids) {
    const cfg = await malik_getEpaperConfig(sessionId);
    const targets = cfg?.targetJids || [];
    if (!targets.length) throw new Error('E-paper target groups are not configured');
    const items = await malik_listPdfQueue(sessionId);
    const recentItems = await malik_listPdfQueue(sessionId, new Date(Date.now() - RETENTION_MS));
    const selected = ids === 'all'
        ? items
        : recentItems.filter((item, index) => ids.includes(String(index + 1)) || ids.includes(String(item._id)));
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

module.exports = {
    rememberAndQueue,
    processIncomingPdf,
    listItems,
    processItems,
    isExcludedPdfSource,
    filterTargetGroups,
    sanitizePdfFileName,
    buildMwArgs
};
