# Speech-to-Text Dictation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add local, editable voice dictation to the existing chat composer without automatically submitting text or retaining audio.

**Architecture:** The browser records one bounded utterance with native `MediaRecorder` and posts the raw bytes to a FastAPI route. A single lazy-loaded Whisper Large V3 Turbo instance decodes audio in memory with PyAV and performs serialized CUDA FP16 inference; the frontend inserts the returned text into the existing textarea.

**Tech Stack:** FastAPI, PyTorch 2.14 CUDA 13.0, Transformers 5.16.1, PyAV 18.1.0, plain JavaScript `MediaRecorder`, Node assert tests, pytest.

**Spec:** `docs/superpowers/specs/2026-09-03-speech-to-text-dictation-design.md`

**Status:** Implemented and verified locally on 2026-09-03. The checklists below preserve the original execution plan; verification evidence is recorded in the design document.

## Global Constraints

- Support CPython 3.11 and newer.
- Record at most 60 seconds and accept at most 10,000,000 request bytes.
- Use `openai/whisper-large-v3-turbo` locally with CUDA FP16; never call an external speech API.
- Allow only one in-flight transcription per backend process; return a busy error instead of queueing.
- Never persist or log audio, filenames, or transcript content.
- Preserve existing textarea content on every error and never submit a transcript automatically.
- Do not commit or reformat unrelated dirty files.

---

### Task 1: Backend HTTP contract

**Files:**
- Create: `AI_engine/app/api/v1/transcription_router.py`
- Create: `AI_engine/tests/test_transcription.py`
- Modify: `AI_engine/app/main.py`

**Interfaces:**
- Consumes: raw request bytes and `Content-Type`.
- Produces: `POST /api/v1/ai/transcriptions` and dependency `get_transcriber()` whose object exposes `async transcribe(audio: bytes, media_type: str) -> str`.

- [ ] Write contract tests using a fake transcriber for success, unsupported media, empty input, oversized streaming input, busy, and inference failure.
- [ ] Run `AI_engine/.venv/Scripts/python.exe -m pytest AI_engine/tests/test_transcription.py -q` and verify failure because the route does not exist.
- [ ] Implement streamed size validation, stable client-safe errors, and the success envelope `{code, message, data: {text}}`.
- [ ] Register the router in `AI_engine/app/main.py` and rerun the contract tests.

### Task 2: Concrete local Whisper transcriber

**Files:**
- Create: `AI_engine/app/infrastructure/speech_to_text.py`
- Create: `AI_engine/tests/test_speech_to_text.py`
- Modify: `AI_engine/app/config.py`
- Create: `AI_engine/requirements-stt.txt`

**Interfaces:**
- Produces: `LocalWhisperTranscriber.transcribe(audio: bytes, media_type: str) -> str`.
- Raises: `InvalidAudioError`, `AudioTooLongError`, `TranscriberBusyError`, and `TranscriptionUnavailableError`.

- [ ] Write tests for non-blocking busy behavior, lock release after failure, silence rejection, duration rejection, and dependency-unavailable behavior using injected decoder/model loaders.
- [ ] Run the focused test and verify it fails because the concrete transcriber does not exist.
- [ ] Implement in-memory PyAV decoding to mono 16 kHz float32, configurable RMS silence threshold, lazy singleton model loading, CUDA FP16 inference via `asyncio.to_thread`, and `threading.Lock.acquire(blocking=False)` cleanup in `finally`.
- [ ] Pin the approved optional dependencies: `torch==2.14.0+cu130`, `transformers==5.16.1`, and `av==18.1.0`.
- [ ] Run both backend test files and the Ruff gate.

### Task 3: Browser dictation controller

**Files:**
- Create: `API/static/dictationController.js`
- Create: `API/tests/dictation_contract.test.js`
- Modify: `API/static/storyRepository.js`
- Modify: `API/static/index.html`

**Interfaces:**
- Consumes: `StoryRepository.transcribe(blob)` and DOM nodes `btn-dictate`, `btn-cancel-dictation`, `dictation-status`, and `user-prompt`.
- Produces: explicit Idle, Requesting, Recording, Transcribing, Success, and Error UI states.

- [ ] Write Node tests with fake `MediaRecorder`, media tracks, timers, and repository for stop, cancel, timeout, error draft preservation, cleanup, and no form submission.
- [ ] Run `node API/tests/dictation_contract.test.js` and verify failure because the controller does not exist.
- [ ] Add `StoryRepository.transcribe(blob)` using the blob MIME type as `Content-Type`.
- [ ] Implement the smallest standalone controller: runtime MIME selection, 60-second stop, immediate track cleanup, transcript insertion through `.value`, and an `input` event without form submission.
- [ ] Add accessible microphone/cancel controls and live status text beside the existing send button; include the classic script before app initialization.
- [ ] Run the new and existing frontend contract tests.

### Task 4: Visual states, security header, and integrated verification

**Files:**
- Modify: `API/static/style.css`
- Modify: `AI_engine/app/main.py`
- Modify: `docs/superpowers/specs/2026-09-03-speech-to-text-dictation-design.md`

**Interfaces:**
- Produces: keyboard-visible dictation states and `Permissions-Policy: microphone=(self)`.

- [ ] Add focused styles for idle, recording, and transcribing states, including reduced-motion behavior and mobile fit.
- [ ] Add and test the microphone Permissions Policy response header.
- [ ] Install optional dependencies into `AI_engine/.venv`, using the already-approved model cache.
- [ ] Run backend transcription tests, full backend tests, both frontend contract tests, Ruff, and the Impeccable detector.
- [ ] Start the local app and verify the root page plus transcription endpoint without using real user story data.
- [ ] Record actual commands, model/device/dtype, latency, retention result, and remaining browser limitation in the design document.
