const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class FakeElement {
    constructor() {
        this.value = '';
        this.textContent = '';
        this.disabled = false;
        this.hidden = false;
        this.dataset = {};
        this.attributes = {};
        this.listeners = {};
        this.events = [];
        this.classList = {
            add: value => { this.dataset[value] = true; },
            remove: value => { delete this.dataset[value]; },
            toggle: (value, enabled) => { enabled ? this.classList.add(value) : this.classList.remove(value); }
        };
    }

    addEventListener(name, listener) {
        this.listeners[name] = listener;
    }

    setAttribute(name, value) {
        this.attributes[name] = value;
    }

    dispatchEvent(event) {
        this.events.push(event.type);
    }
}

class FakeMediaRecorder {
    static isTypeSupported(type) {
        return type === 'audio/webm;codecs=opus';
    }

    constructor(stream, options) {
        this.stream = stream;
        this.mimeType = options.mimeType;
        this.state = 'inactive';
    }

    start(timeslice) {
        this.timeslice = timeslice;
        this.state = 'recording';
    }

    stop() {
        this.state = 'inactive';
        queueMicrotask(() => {
            this.ondataavailable({ data: new Blob(['audio'], { type: this.mimeType }) });
            this.onstop();
        });
    }
}

class HeaderOnlyMediaRecorder extends FakeMediaRecorder {
    stop() {
        this.state = 'inactive';
        queueMicrotask(() => {
            this.ondataavailable({ data: new Blob([new Uint8Array(110)], { type: this.mimeType }) });
            this.onstop();
        });
    }
}

class FakeAudioContext {
    constructor() {
        this.sampleRate = 48_000;
        this.destination = {};
    }

    createMediaStreamSource() {
        return { connect() {}, disconnect() {} };
    }

    createScriptProcessor() {
        return { connect() {}, disconnect() {}, onaudioprocess: null };
    }

    createGain() {
        return { connect() {}, disconnect() {}, gain: { value: 1 } };
    }

    async resume() {}
    async close() {}
}

function makeHarness({ transcript = 'Xin chào', failure = null, MediaRecorder = FakeMediaRecorder, SpeechRecognition = null } = {}) {
    const track = { stopped: false, stop() { this.stopped = true; } };
    const stream = { getTracks: () => [track] };
    const calls = [];
    const repository = {
        async transcribe(blob) {
            calls.push(blob);
            if (failure) throw failure;
            return { data: { text: transcript } };
        }
    };
    const dom = {
        button: new FakeElement(),
        cancelButton: new FakeElement(),
        listening: new FakeElement(),
        elapsed: new FakeElement(),
        status: new FakeElement(),
        input: new FakeElement(),
        form: { requestSubmitCalls: 0, requestSubmit() { this.requestSubmitCalls += 1; } }
    };
    dom.listening.hidden = true;
    const timers = [];
    const platform = {
        Blob,
        Event: class { constructor(type) { this.type = type; } },
        MediaRecorder,
        AudioContext: FakeAudioContext,
        mediaDevices: { getUserMedia: async () => stream },
        SpeechRecognition,
        setTimeout: callback => { timers.push(callback); return timers.length; },
        clearTimeout: () => {}
    };
    const controller = new context.DictationController(repository, dom, platform);
    controller.init();
    return { calls, controller, dom, timers, track };
}

const context = { Blob, console };
vm.createContext(context);
vm.runInContext(
    `${fs.readFileSync('static/dictationController.js', 'utf8')}\nglobalThis.DictationController = DictationController;`,
    context
);

(async () => {
    const success = makeHarness();
    success.dom.input.value = 'Bản nháp';
    await success.controller.start();
    assert.equal(success.controller.state, 'recording');
    assert.equal(success.controller.recorder.timeslice, 250);
    assert.equal(success.dom.listening.hidden, false);
    assert.equal(success.dom.input.hidden, true);
    assert.equal(success.dom.elapsed.textContent, '0:00');
    assert.equal(success.dom.button.attributes['aria-label'], 'Dừng nhập bằng giọng nói');
    const successCompletion = success.controller.stop();
    assert.equal(success.track.stopped, false, 'track must stay live until MediaRecorder finishes');
    await successCompletion;
    assert.equal(success.calls[0].type, 'audio/webm;codecs=opus');
    assert.equal(success.dom.input.value, 'Bản nháp Xin chào');
    assert.deepEqual(success.dom.input.events, ['input']);
    assert.equal(success.dom.form.requestSubmitCalls, 0, 'dictation must never submit the form');
    assert.equal(success.track.stopped, true);

    const wavFallback = makeHarness({ MediaRecorder: HeaderOnlyMediaRecorder });
    await wavFallback.controller.start();
    wavFallback.controller.processor.onaudioprocess({
        inputBuffer: { getChannelData: () => Float32Array.from([0, 0.25, -0.25, 0]) }
    });
    await wavFallback.controller.stop();
    assert.equal(wavFallback.calls[0].type, 'audio/wav');
    assert.ok(wavFallback.calls[0].size > 44);

    const cancelled = makeHarness();
    await cancelled.controller.start();
    await cancelled.controller.cancel();
    assert.equal(cancelled.calls.length, 0);
    assert.equal(cancelled.track.stopped, true);
    assert.equal(cancelled.controller.state, 'idle');

    const failed = makeHarness({ failure: new Error('offline') });
    failed.dom.input.value = 'Không được mất';
    await failed.controller.start();
    await failed.controller.stop();
    assert.equal(failed.dom.input.value, 'Không được mất');
    assert.equal(failed.controller.state, 'error');
    assert.match(failed.dom.status.textContent, /thử lại/i);

    const timeout = makeHarness();
    await timeout.controller.start();
    const completion = timeout.controller.completion;
    timeout.timers[0]();
    await completion;
    assert.equal(timeout.calls.length, 1);
    const webSpeechHarness = makeHarness({
        SpeechRecognition: class {
            constructor() {
                this.onstart = null;
                this.onresult = null;
                this.onend = null;
            }
            start() {
                queueMicrotask(() => {
                    this.onstart?.();
                    this.onresult?.({
                        resultIndex: 0,
                        results: [
                            Object.assign([{ transcript: 'Tôi đang nói' }], { isFinal: true })
                        ]
                    });
                });
            }
            stop() { this.onend?.(); }
            abort() { this.onend?.(); }
        }
    });
    assert.equal(webSpeechHarness.controller.engine, 'web_speech');
    await webSpeechHarness.controller.start();
    await new Promise(r => setImmediate(r));
    assert.equal(webSpeechHarness.dom.input.value, 'Tôi đang nói');
    await webSpeechHarness.controller.stop();
    assert.equal(webSpeechHarness.controller.state, 'success');

    console.log('dictation contract checks passed');
})().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
