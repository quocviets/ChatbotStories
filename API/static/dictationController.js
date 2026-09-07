class DictationController {
    static MIME_TYPES = [
        'audio/webm;codecs=opus',
        'audio/webm',
        'audio/ogg;codecs=opus',
        'audio/mp4'
    ];

    constructor(repository, dom, platform = {}) {
        this.repository = repository;
        this.dom = dom;
        this.platform = {
            Blob: platform.Blob || globalThis.Blob,
            Event: platform.Event || globalThis.Event,
            MediaRecorder: platform.MediaRecorder || globalThis.MediaRecorder,
            AudioContext: platform.AudioContext || globalThis.AudioContext || globalThis.webkitAudioContext,
            mediaDevices: platform.mediaDevices || globalThis.navigator?.mediaDevices,
            SpeechRecognition: platform.SpeechRecognition || globalThis.SpeechRecognition || globalThis.webkitSpeechRecognition,
            setTimeout: platform.setTimeout || (globalThis.setTimeout ? globalThis.setTimeout.bind(globalThis) : undefined),
            clearTimeout: platform.clearTimeout || (globalThis.clearTimeout ? globalThis.clearTimeout.bind(globalThis) : undefined),
            setInterval: platform.setInterval || (globalThis.setInterval ? globalThis.setInterval.bind(globalThis) : undefined),
            clearInterval: platform.clearInterval || (globalThis.clearInterval ? globalThis.clearInterval.bind(globalThis) : undefined)
        };
        this.engine = this.platform.SpeechRecognition ? 'web_speech' : 'local_whisper';
        this.state = 'idle';
        this.operationId = 0;
        this.recorder = null;
        this.recognition = null;
        this.baseText = '';
        this.accumulatedText = '';
        this.stream = null;
        this.chunks = [];
        this.pcmChunks = [];
        this.cancelled = false;
        this.timeoutId = null;
        this.intervalId = null;
        this.completion = Promise.resolve();
    }

    init() {
        this.dom.button.addEventListener('click', () => {
            if (this.state === 'recording') this.stop();
            else this.start();
        });
        this.dom.cancelButton.addEventListener('click', () => this.cancel());
        if (this.dom.engineSelect) {
            if (!this.platform.SpeechRecognition) {
                const opt = this.dom.engineSelect.querySelector('option[value="web_speech"]');
                if (opt) opt.disabled = true;
                this.engine = 'local_whisper';
            }
            this.dom.engineSelect.value = this.engine;
            this.dom.engineSelect.addEventListener('change', event => {
                this.engine = event.target.value;
            });
        }
        const hasWebSpeech = Boolean(this.platform.SpeechRecognition);
        const hasLocal = Boolean(this.platform.MediaRecorder && this.platform.mediaDevices?.getUserMedia);
        if (!hasWebSpeech && !hasLocal) {
            this._setState('error', 'Trình duyệt này không hỗ trợ ghi âm.');
            this.dom.button.disabled = true;
            return;
        }
        this._setState('idle', '');
    }

    _mimeType() {
        return DictationController.MIME_TYPES.find(type =>
            this.platform.MediaRecorder.isTypeSupported(type)
        );
    }

    async start() {
        if (this.engine === 'web_speech' && this.platform.SpeechRecognition) {
            return this._startWebSpeech();
        }
        return this._startLocalWhisper();
    }

    _startWebSpeech() {
        const operationId = ++this.operationId;
        this.cancelled = false;
        this.baseText = this.dom.input.value.trimEnd();
        this.accumulatedText = '';
        this._setState('requesting', 'Đang kết nối microphone…');

        try {
            const SpeechRecognitionClass = this.platform.SpeechRecognition;
            const recognition = new SpeechRecognitionClass();
            recognition.lang = 'vi-VN';
            recognition.continuous = true;
            recognition.interimResults = true;
            this.recognition = recognition;

            recognition.onstart = () => {
                if (operationId !== this.operationId) {
                    try { recognition.abort(); } catch (_err) {}
                    return;
                }
                this.startedAt = Date.now();
                this.dom.elapsed.textContent = '0:00';
                this._setState('recording', 'Đang nghe… Nói xong bấm nút vuông để hoàn tất.');
                if (this.platform.setInterval) {
                    this.intervalId = this.platform.setInterval(() => {
                        const seconds = Math.min(60, Math.floor((Date.now() - this.startedAt) / 1000));
                        this.dom.elapsed.textContent = `0:${String(seconds).padStart(2, '0')}`;
                    }, 1000);
                }
                this.timeoutId = this.platform.setTimeout(() => this.stop(), 60_000);
            };

            recognition.onresult = event => {
                if (operationId !== this.operationId || this.cancelled) return;
                let interim = '';
                let final = '';
                for (let i = event.resultIndex; i < event.results.length; i += 1) {
                    const item = event.results[i];
                    if (item.isFinal) {
                        final += item[0].transcript;
                    } else {
                        interim += item[0].transcript;
                    }
                }
                if (final) {
                    this.accumulatedText = this.accumulatedText ? `${this.accumulatedText} ${final.trim()}` : final.trim();
                }
                const parts = [this.baseText, this.accumulatedText, interim.trim()].filter(Boolean);
                this.dom.input.value = parts.join(' ');
                this.dom.input.dispatchEvent(new this.platform.Event('input', { bubbles: true }));
            };

            recognition.onerror = event => {
                if (operationId !== this.operationId) return;
                this._clearTimers();
                this.recognition = null;
                if (event.error === 'not-allowed') {
                    this._setState('error', 'Không thể dùng microphone. Hãy cấp quyền rồi thử lại.');
                } else if (event.error !== 'no-speech') {
                    this._setState('error', `Lỗi nhận diện: ${event.error || 'không xác định'}`);
                }
            };

            recognition.onend = () => {
                this._clearTimers();
                this.recognition = null;
                if (this.state === 'recording') {
                    this._setState('success', 'Đã chuyển thành văn bản. Bạn có thể sửa trước khi gửi.');
                }
            };

            recognition.start();
        } catch (_err) {
            this._clearTimers();
            this.recognition = null;
            this._setState('error', 'Không thể khởi động Google Web Speech. Hãy thử lại.');
        }
    }

    async _startLocalWhisper() {
        const mimeType = this._mimeType();
        if (!mimeType) {
            this._setState('error', 'Không tìm thấy định dạng ghi âm được hỗ trợ.');
            return;
        }

        const operationId = ++this.operationId;
        this.cancelled = false;
        this._setState('requesting', 'Đang xin quyền dùng microphone…');
        try {
            const stream = await this.platform.mediaDevices.getUserMedia({
                audio: {
                    echoCancellation: true,
                    noiseSuppression: true,
                    autoGainControl: true
                }
            });
            if (operationId !== this.operationId) {
                stream.getTracks().forEach(track => track.stop());
                return;
            }
            this.stream = stream;
            this.chunks = [];
            this.pcmChunks = [];
            await this._startPcmCapture(stream);
            this.recorder = new this.platform.MediaRecorder(stream, { mimeType });
            this.completion = new Promise(resolve => { this._resolveCompletion = resolve; });
            this.recorder.ondataavailable = event => {
                if (event.data?.size) this.chunks.push(event.data);
            };
            this.recorder.onstop = () => this._finishRecording(mimeType);
            this.recorder.start(250);
            this.startedAt = Date.now();
            this.dom.elapsed.textContent = '0:00';
            this._setState('recording', 'Đang nghe Local Whisper… Bấm nút vuông để chuyển thành chữ.');
            if (this.platform.setInterval) {
                this.intervalId = this.platform.setInterval(() => {
                    const seconds = Math.min(60, Math.floor((Date.now() - this.startedAt) / 1000));
                    this.dom.elapsed.textContent = `0:${String(seconds).padStart(2, '0')}`;
                }, 1000);
            }
            this.timeoutId = this.platform.setTimeout(() => this.stop(), 60_000);
        } catch (_error) {
            this._cleanupMedia();
            this._setState('error', 'Không thể dùng microphone. Hãy cấp quyền rồi thử lại.');
        }
    }

    stop() {
        if (this.state !== 'recording') {
            return this.completion;
        }
        if (this.recognition) {
            this._clearTimers();
            try {
                this.recognition.stop();
            } catch (_err) {}
            this._setState('success', 'Đã chuyển thành văn bản. Bạn có thể sửa trước khi gửi.');
            return Promise.resolve();
        }
        if (this.recorder?.state !== 'recording') {
            return this.completion;
        }
        this._clearTimers();
        this._setState('transcribing', 'Đang chuyển giọng nói thành văn bản…');
        this.recorder.stop();
        return this.completion;
    }

    async cancel() {
        this.operationId += 1;
        this.cancelled = true;
        this._clearTimers();
        if (this.recognition) {
            try {
                this.recognition.abort();
            } catch (_err) {}
            this.recognition = null;
            this.dom.input.value = this.baseText;
            this.dom.input.dispatchEvent(new this.platform.Event('input', { bubbles: true }));
        }
        if (this.recorder?.state === 'recording') this.recorder.stop();
        this._cleanupMedia();
        this.chunks = [];
        this._setState('idle', 'Đã hủy bản ghi.');
        await this.completion;
    }

    async _finishRecording(mimeType) {
        try {
            if (this.cancelled) return;
            let blob = new this.platform.Blob(this.chunks, { type: mimeType });
            this.chunks = [];
            if (blob.size <= 110 && this.pcmChunks.length) blob = this._wavBlob();
            if (!blob.size) throw new Error('empty recording');
            const response = await this.repository.transcribe(blob);
            const text = response.data?.text?.trim();
            if (!text) {
                this._setState('error', 'Không nhận ra giọng nói. Hãy nói gần microphone và thử lại.');
                return;
            }
            const current = this.dom.input.value.trimEnd();
            this.dom.input.value = current ? `${current} ${text}` : text;
            this.dom.input.dispatchEvent(new this.platform.Event('input', { bubbles: true }));
            this.dom.input.focus?.();
            this._setState('success', 'Đã chuyển thành văn bản. Bạn có thể sửa trước khi gửi.');
        } catch (error) {
            let message = 'Không thể chuyển giọng nói. Nội dung cũ vẫn được giữ; hãy thử lại.';
            if (error?.message?.includes('is in progress') || error?.message?.includes('TRANSCRIBER_BUSY')) {
                message = 'Hệ thống đang xử lý bản ghi khác. Vui lòng thử lại sau giây lát.';
            } else if (error?.message?.includes('exceeds 60 seconds') || error?.message?.includes('AUDIO_TOO_LONG')) {
                message = 'Bản ghi vượt quá 60 giây. Hãy nói ngắn hơn và thử lại.';
            } else if (error?.message === 'empty recording') {
                message = 'Bản ghi rỗng. Hãy nói vào microphone rồi thử lại.';
            }
            this._setState('error', message);
        } finally {
            this._cleanupMedia();
            this.chunks = [];
            this._resolveCompletion?.();
            if (this.state === 'transcribing') {
                this._setState('idle', '');
            }
        }
    }

    _clearTimers() {
        if (this.timeoutId) this.platform.clearTimeout(this.timeoutId);
        if (this.intervalId && this.platform.clearInterval) this.platform.clearInterval(this.intervalId);
        this.timeoutId = null;
        this.intervalId = null;
    }

    async _startPcmCapture(stream) {
        if (!this.platform.AudioContext) return;
        try {
            this.audioContext = new this.platform.AudioContext();
            this.source = this.audioContext.createMediaStreamSource(stream);
            this.processor = this.audioContext.createScriptProcessor(4096, 1, 1);
            this.sink = this.audioContext.createGain();
            this.sink.gain.value = 0;
            this.processor.onaudioprocess = event => {
                this.pcmChunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
            };
            this.source.connect(this.processor);
            this.processor.connect(this.sink);
            this.sink.connect(this.audioContext.destination);
            await this.audioContext.resume();
        } catch (_error) {
            this._cleanupPcmCapture();
        }
    }

    _wavBlob() {
        const sampleCount = this.pcmChunks.reduce((total, chunk) => total + chunk.length, 0);
        const buffer = new ArrayBuffer(44 + sampleCount * 2);
        const view = new DataView(buffer);
        const write = (offset, value) => {
            for (let index = 0; index < value.length; index += 1) {
                view.setUint8(offset + index, value.charCodeAt(index));
            }
        };
        write(0, 'RIFF');
        view.setUint32(4, 36 + sampleCount * 2, true);
        write(8, 'WAVEfmt ');
        view.setUint32(16, 16, true);
        view.setUint16(20, 1, true);
        view.setUint16(22, 1, true);
        view.setUint32(24, this.audioContext.sampleRate, true);
        view.setUint32(28, this.audioContext.sampleRate * 2, true);
        view.setUint16(32, 2, true);
        view.setUint16(34, 16, true);
        write(36, 'data');
        view.setUint32(40, sampleCount * 2, true);
        let offset = 44;
        for (const chunk of this.pcmChunks) {
            for (const value of chunk) {
                const sample = Math.max(-1, Math.min(1, value));
                view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
                offset += 2;
            }
        }
        return new this.platform.Blob([buffer], { type: 'audio/wav' });
    }

    _cleanupPcmCapture() {
        if (this.processor) this.processor.onaudioprocess = null;
        this.processor?.disconnect();
        this.source?.disconnect();
        this.sink?.disconnect();
        this.audioContext?.close().catch(() => {});
        this.processor = null;
        this.source = null;
        this.sink = null;
        this.audioContext = null;
        this.pcmChunks = [];
    }

    _cleanupMedia() {
        this._cleanupPcmCapture();
        this.stream?.getTracks().forEach(track => track.stop());
        this.stream = null;
    }

    _setState(state, message) {
        this.state = state;
        this.dom.button.dataset.state = state;
        this.dom.button.disabled = state === 'requesting' || state === 'transcribing';
        this.dom.cancelButton.hidden = state !== 'recording';
        this.dom.listening.hidden = state !== 'recording';
        this.dom.input.hidden = state === 'recording';
        this.dom.status.textContent = message;
        this.dom.button.setAttribute(
            'aria-label',
            state === 'recording' ? 'Dừng nhập bằng giọng nói' : 'Bắt đầu nhập bằng giọng nói'
        );
        this.dom.button.setAttribute('aria-pressed', state === 'recording' ? 'true' : 'false');
    }
}
