'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
    normalizeSharedPdfName,
    sharedPdfMatchesPaperKeyword,
    sharedPdfMatchesPaperIssue
} = require('../maliklib/database');
const {
    buildMwArgs,
    buildSocialCleanerArgs,
    filterTargetGroups,
    isExcludedPdfSource,
    sanitizePdfFileName,
    DEFAULT_EXCLUDED_PDF_SOURCES
} = require('../maliklib/pdfQueue');

test('normalizes MW and filename punctuation for shared duplicate matching', () => {
    assert.equal(
        normalizeSharedPdfName('The Express MW - Lahore 6 Oct.PDF'),
        normalizeSharedPdfName('the_express---lahore 6 OCT.pdf')
    );
});

test('matches MW titles against newspaper keys recorded by the epaper sender', () => {
    assert.equal(sharedPdfMatchesPaperKeyword('Jang Sunday Magazine Lahore 7Oct.pdf', 'jang'), true);
    assert.equal(sharedPdfMatchesPaperKeyword('Express Lahore 7Oct.pdf', 'express'), true);
    assert.equal(sharedPdfMatchesPaperKeyword('Ummat Karachi 7Oct.pdf', 'ummat'), true);
    assert.equal(sharedPdfMatchesPaperKeyword('Jinnah Lahore 7Oct.pdf', 'jinnah'), true);
    assert.equal(sharedPdfMatchesPaperKeyword('Pakistan Observer 7Oct.pdf', 'pakobserver'), true);
    assert.equal(sharedPdfMatchesPaperKeyword('Daily Pakistan Lahore 7Oct.pdf', 'dailypakistan'), true);
    assert.equal(sharedPdfMatchesPaperKeyword('The Patriot ISB 7Oct.pdf', 'thepatriot'), true);
    assert.equal(sharedPdfMatchesPaperKeyword('Mashriq Akhbar 7Oct.pdf', 'mashriqakhbar'), true);
    assert.equal(sharedPdfMatchesPaperKeyword('Dawn Karachi 7Oct.pdf', 'jang'), false);
    assert.equal(sharedPdfMatchesPaperKeyword('Expressway Lahore 7Oct.pdf', 'express'), false);
});

test('cross-filename duplicate matching requires the same newspaper issue date', () => {
    assert.equal(
        sharedPdfMatchesPaperIssue('Express Lahore 8October.pdf', 'The Express MW - Lahore 8 Oct.pdf', 'express'),
        true
    );
    assert.equal(
        sharedPdfMatchesPaperIssue('Express Lahore 8October.pdf', 'The Express MW - Lahore 7 Oct.pdf', 'express'),
        false
    );
    assert.equal(
        sharedPdfMatchesPaperIssue('Express Lahore 8October.pdf', 'The News Lahore 8 Oct.pdf', 'express'),
        false
    );
    assert.equal(
        sharedPdfMatchesPaperIssue('Express Lahore 8October.pdf', 'Express Lahore.pdf', 'express'),
        false
    );
});

test('moves a leading day/month/year into the newspaper filename suffix', () => {
    assert.equal(sanitizePdfFileName('7 Oct 92 News Lahore.pdf'), '92 News Lahore 7Oct.pdf');
});

test('enables reference-image skipping in both automatic and manual MW queue runs', () => {
    assert.deepEqual(buildMwArgs('/tmp/input.pdf', '/tmp/output.pdf').slice(-6), [
        '--input', '/tmp/input.pdf', '--output', '/tmp/output.pdf',
        '--skip-reference-images', '--reference-images-checked'
    ]);
});

test('runs the social watermark cleaner before MW processing and keeps reference-image skipping', () => {
    assert.deepEqual(
        buildSocialCleanerArgs('/tmp/input.pdf', '/tmp/cleaned.pdf').slice(-4),
        ['/tmp/input.pdf', '/tmp/cleaned.pdf', '--skip-reference-images']
    );
});

test('does not deliver an MW PDF back to its source group', () => {
    assert.deepEqual(
        filterTargetGroups(['120363@g.us', '12345@g.us'], '120363@g.us'),
        ['12345@g.us']
    );
});

test('excludes the configured senders only in the configured groups', () => {
    assert.equal(isExcludedPdfSource({
        key: {
            remoteJid: '120363026226973835@g.us',
            participant: '81131932283065@lid'
        }
    }), true);
    assert.equal(isExcludedPdfSource({
        key: {
            remoteJid: '923489517717-1546053015@g.us',
            participantAlt: '87424696897621@lid'
        }
    }), true);
    assert.equal(isExcludedPdfSource({
        key: {
            remoteJid: '120363026226973835@g.us',
            participant: '923456789012@s.whatsapp.net'
        }
    }), false);
    assert.equal(isExcludedPdfSource({
        key: {
            remoteJid: '120363000000000000@g.us',
            participant: '81131932283065@lid'
        }
    }), false);
});

test('supports persisted custom MW exclusion pairs without affecting other groups or senders', () => {
    const exclusions = [
        { groupJid: '120363000000000000@g.us', senderJids: ['123456789012@lid'] }
    ];
    assert.equal(isExcludedPdfSource({
        key: {
            remoteJid: '120363000000000000@g.us',
            participantAlt: '123456789012@lid'
        }
    }, exclusions), true);
    assert.equal(isExcludedPdfSource({
        key: {
            remoteJid: '120363000000000001@g.us',
            participant: '123456789012@lid'
        }
    }, exclusions), false);
    assert.equal(isExcludedPdfSource({
        key: {
            remoteJid: '120363000000000000@g.us',
            participant: '987654321098@lid'
        }
    }, exclusions), false);
});

test('an explicitly empty exclusion list disables the legacy defaults', () => {
    assert.equal(DEFAULT_EXCLUDED_PDF_SOURCES.length, 2);
    assert.equal(isExcludedPdfSource({
        key: {
            remoteJid: '120363026226973835@g.us',
            participant: '81131932283065@lid'
        }
    }, []), false);
});
