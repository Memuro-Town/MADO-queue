// Execute the real display.html script with synthetic API responses and Web Audio.
// No npm packages, production DB, printer, or physical audio device are used.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../templates/display.html'), 'utf8');
const script = [...source.matchAll(/<script>([\s\S]*?)<\/script>/g)][0][1];
const ticket = (id, number = 1, seconds = 0) => ({
    processing_id: id, category: 'A', number, seconds_since: seconds,
});
const flush = () => new Promise(resolve => setImmediate(resolve));

async function display(initial = []) {
    const elements = new Map();
    let response = {calling: initial, waiting_count: 0};
    let fail = false;
    let tones = 0;
    const errors = [];
    const audio = {
        state: 'running', currentTime: 0, destination: {},
        createOscillator() {
            tones++;
            return {frequency: {setValueAtTime() {}}, connect() {}, start() {}, stop() {}};
        },
        createGain() {
            return {gain: {setValueAtTime() {}, exponentialRampToValueAtTime() {}}, connect() {}};
        },
    };
    const context = vm.createContext({
        window: {AudioContext: function() {return audio;}},
        document: {getElementById(id) {
            if (!elements.has(id)) elements.set(id, {style: {}, innerHTML: '', textContent: ''});
            return elements.get(id);
        }},
        fetch: async () => {
            if (fail) throw new Error('synthetic network failure');
            return {json: async () => response};
        },
        setInterval() {},
        console: {error(e) {errors.push(e);}},
    });
    vm.runInContext(script, context);
    await flush();
    vm.runInContext('unlockAudio()', context);
    tones = 0; // Ignore the user-initiated audio-unlock sample.
    return {
        chimes: () => tones / 5,
        cards: () => elements.get('callingCards').innerHTML,
        async poll(calling, options = {}) {
            response = {calling, waiting_count: 0};
            fail = !!options.fail;
            vm.runInContext('updateDisplay()', context);
            await flush();
        },
        errors,
    };
}

test('reused category/number with a new processing ID rings and renders both cards', async () => {
    const page = await display([ticket(1)]);
    await page.poll([ticket(1), ticket(2)]);
    assert.equal(page.chimes(), 1);
    assert.equal((page.cards().match(/card-number/g) || []).length, 2);
    await page.poll([ticket(1), ticket(2)]);
    assert.equal(page.chimes(), 1);
});

test('first new call after an empty baseline rings', async () => {
    const page = await display();
    await page.poll([ticket(1)]);
    assert.equal(page.chimes(), 1);
});

test('initial existing calls are not replayed after audio unlock', async () => {
    const page = await display([ticket(1)]);
    await page.poll([ticket(1)]);
    assert.equal(page.chimes(), 0);
});

test('cached API response does not ring again; recovery with a new ID rings', async () => {
    const page = await display([ticket(1)]);
    await page.poll([ticket(1)]);
    assert.equal(page.chimes(), 0);
    await page.poll([ticket(1), ticket(2)]);
    assert.equal(page.chimes(), 1);
});

test('cancel/recall with a new processing ID rings even at the same number', async () => {
    const page = await display([ticket(1)]);
    await page.poll([ticket(2)]);
    assert.equal(page.chimes(), 1);
});

test('network failure preserves the baseline for recovery', async () => {
    const page = await display([ticket(1)]);
    await page.poll([], {fail: true});
    assert.equal(page.errors.length, 1);
    assert.equal(page.chimes(), 0);
    await page.poll([ticket(1), ticket(2)]);
    assert.equal(page.chimes(), 1);
});

test('expired calls and removal do not ring; subsequent call from empty rings', async () => {
    const page = await display([ticket(1)]);
    await page.poll([ticket(1, 1, 60)]);
    assert.equal(page.chimes(), 0);
    assert.ok(page.cards().includes('現在呼び出し中の番号はありません'));
    await page.poll([ticket(2)]);
    assert.equal(page.chimes(), 1);
});
