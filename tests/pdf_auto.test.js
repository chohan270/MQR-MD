'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { normalizeSharedPdfName } = require('../maliklib/database');
const { isExcludedPdfSource } = require('../maliklib/pdfQueue');

test('normalizes MW and filename punctuation for shared duplicate matching', () => {
    assert.equal(
        normalizeSharedPdfName('The Express MW - Lahore 6 Oct.PDF'),
        normalizeSharedPdfName('the_express---lahore 6 OCT.pdf')
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
