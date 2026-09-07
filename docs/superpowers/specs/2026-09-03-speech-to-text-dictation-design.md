# Speech-to-Text Dictation Design

- **Status:** Implemented locally; waiting for owner acceptance
- **Date:** 2026-09-03

**Implementation rule:** Finish one stage, report evidence, and wait for explicit
owner approval before starting the next stage.

## 1. Goal

Add ChatGPT-style voice dictation to the existing chat composer:

1. The user presses a microphone button.
2. The browser records one utterance, up to 60 seconds.
3. The user stops or cancels recording.
4. The backend transcribes the audio with a local Hugging Face Whisper model.
5. The transcript is placed in the existing textarea for editing.
6. The text is sent only when the user explicitly submits the form.

## 2. Non-goals

- No continuous voice conversation or spoken response.
- No automatic message submission.
- No external speech API.
- No recording history, speaker identification, or audio library.
- No automatic CPU fallback after a CUDA failure.
- No speculative abstraction for multiple transcription providers.

## 3. Confirmed Decisions

| Area | Decision |
|---|---|
| Interaction | Press to start, press to stop, then edit the transcript |
| Recording limit | 60 seconds per utterance |
| Primary model | `openai/whisper-large-v3-turbo` |
| Execution | Local NVIDIA GPU with CUDA and FP16 |
| Fallback | `openai/whisper-small` only through an explicit configuration change if measurements show the primary model cannot run reliably |
| Submission | Never automatic |
| Parallel work | One transcription at a time |
| Audio retention | No persistent audio storage |
| Transcript retention | Saved only through the existing chat submission flow |

## 4. Architecture and Data Flow

```text
Microphone
  -> browser MediaRecorder
  -> temporary browser-managed Blob
  -> POST /api/v1/ai/transcriptions
  -> request validation
  -> local Whisper inference on the GPU
  -> temporary decoder file deleted in finally, if one was required
  -> transcript response
  -> existing editable textarea
```

The frontend uses `MediaRecorder`, a native browser API. The backend adds one route
and one concrete local transcriber. There is no provider interface or factory until
a second real implementation exists.

### Proposed API contract

`POST /api/v1/ai/transcriptions`

- Request body: raw recorded audio with its supported audio `Content-Type`.
- Response: the project's existing success envelope containing one `text` string.
- Authentication and origin handling: preserve and verify the application's current
  deployment policy; do not invent a separate auth system inside this feature. If no
  policy exists, report that security gap at Gate 1 before implementing the route.
- Validation: allowed media type, non-empty body, duration policy, and a bounded
  request size.
- Errors: stable client-safe errors for unsupported media, oversized input,
  unavailable model, busy transcriber, and failed transcription.
- Audio bytes, filenames, and transcript content must not be logged.

The exact media types and byte limit are not guessed in this document. Stage 1 must
measure the browser's actual recording output and propose a safe bound; the owner
must approve that contract before Stage 2.

## 5. Frontend Experience

The microphone control sits beside the existing submit control and has these states:

| State | UI behavior |
|---|---|
| Idle | Microphone button is available |
| Requesting permission | Control is disabled and permission progress is announced |
| Recording | Visible recording indicator, elapsed time, Stop, and Cancel |
| Transcribing | Recording is stopped; progress is announced; duplicate work is blocked |
| Success | Transcript is inserted into the textarea and remains editable |
| Error | Existing draft text is preserved and a recoverable error is shown |

Cancel discards the current temporary recording and does not call the backend.
Stopping or leaving the recording state must stop every microphone track promptly.
The flow must work from the keyboard, expose accessible names and state, and not use
color as its only signal.

## 6. Backend and Model Lifecycle

- Load one model instance per backend process and reuse it.
- Use CUDA FP16 for the primary path.
- Serialize inference with the smallest in-process guard needed for the agreed
  one-at-a-time behavior.
- Return a busy response instead of accumulating an unbounded queue.
- Keep model weights in the Hugging Face disk cache; this cache is separate from
  user audio and its exact location and disk budget must be approved in Stage 1.
- Do not silently switch models or execution devices after an error.
- Delete any decoder-required temporary file in a `finally` block on success,
  validation failure, cancellation, and inference failure.

Model load, cache creation, a concurrency guard, and all new packages are explicit
implementation changes. None may be introduced before their corresponding approval
gate.

## 7. Privacy and Security

### Data retained

- Browser: only the short-lived `MediaRecorder` Blob needed to upload the current
  utterance; no `localStorage`, IndexedDB, service-worker cache, DOM history, or
  long-lived global reference.
- Backend: in-memory request data and, only when required by the decoder, one
  short-lived temporary file.
- Disk: Hugging Face model weights only, not user audio.
- Transcript: no new storage path; it is persisted only if the user later submits it
  through the existing chat flow.

### Required controls

- Microphone access only after an explicit user action and browser permission.
- HTTPS in deployed environments; localhost is acceptable for development.
- `Permissions-Policy: microphone=(self)`.
- Strict media-type, duration, and size validation at the API boundary.
- Safe DOM text insertion; no transcript interpolation into HTML.
- Content Security Policy as defense in depth where compatible with the current app.
- Generic client errors and content-free operational logs.

### Security boundary

This design minimizes retention; it cannot make in-flight audio invisible to a
compromised page, malicious browser extension, or compromised operating system.
Streaming would not remove that risk and is outside this feature.

## 8. Ordered Implementation Stages and Approval Gates

### Stage 0 — Approve this design

Deliverables:

- Product context in `PRODUCT.md`.
- This architecture, privacy model, ordered plan, and acceptance criteria.

**Gate 0:** The owner approves or requests changes. No implementation starts before
approval.

### Stage 1 — Compatibility and dependency probe

Actions, only after Gate 0:

1. Inventory the current Python environment and installed packages.
2. Propose exact package versions and download/disk impact; request approval before
   installing or downloading anything.
3. Verify CPython 3.11 compatibility and separately record whether the local Python
   version is supported.
4. Probe CUDA, FP16 model loading, VRAM, latency, and teardown on the target RTX 3050.
5. Probe the browser's produced media type and bitrate using synthetic or explicitly
   consented short audio, never real user story data.
6. Propose supported media types, request-size bound, cache path, and disk budget
   from the evidence.

Exit evidence: exact environment, exact proposed dependencies, model load result,
peak VRAM, sample latency, media format, estimated cache size, and proposed limits.

**Gate 1:** The owner approves the dependency install/download, primary or fallback
model, cache policy, and API limits.

### Stage 2 — Backend contract with a fake transcriber

Actions, only after Gate 1:

1. Add failing contract tests for success, validation, busy, failure, and cleanup.
2. Add the minimum route and concrete service boundary needed by those tests.
3. Use a fake transcriber in tests; do not load a model or use user audio.
4. Verify the full backend test suite and Ruff gates.

Exit evidence: API examples, changed files, test output, and confirmed temporary-file
cleanup.

**Gate 2:** The owner approves the backend contract before real model integration.

### Stage 3 — Local Whisper integration

Actions, only after Gate 2:

1. Implement the single concrete Hugging Face Whisper transcriber.
2. Load and reuse the approved model on the approved device.
3. Enforce one in-flight transcription and deterministic cleanup.
4. Test failure paths without live providers or user story data.
5. Re-measure VRAM and latency on the target machine.

Exit evidence: model identity, device/dtype, cache location, cleanup result, measured
VRAM/latency, and automated test output.

**Gate 3:** The owner approves the measured local backend behavior before frontend
work.

### Stage 4 — Browser recording and dictation UX

Actions, only after Gate 3:

1. Add failing frontend contract tests for the dictation states and no-auto-send rule.
2. Add the microphone control with native `MediaRecorder`.
3. Implement Stop, Cancel, permission denial, timeout, busy, and retry behavior.
4. Stop media tracks and release temporary Blob references on every exit path.
5. Add the approved permission/security headers and accessible status announcements.
6. Verify existing text is preserved on errors and returned text is editable.

Exit evidence: contract-test output, supported-browser result, keyboard flow, screen
states, and confirmation that dictation never submits the form.

**Gate 4:** The owner reviews and approves the visible behavior.

### Stage 5 — Integrated local acceptance

Actions, only after Gate 4:

1. Run one approved 5–10 second synthetic or explicitly consented recording through
   the complete local flow.
2. Inspect browser and backend state for forbidden persistence and content logging.
3. Run relevant backend tests, frontend contract tests, Ruff checks, and the existing
   regression suite.
4. Update user and engineering documentation with the verified configuration and
   limitations.

Exit evidence: actual commands and results, final data-retention check, observed
latency, and remaining limitations.

**Gate 5:** The owner gives final acceptance. No commit, deployment, or external
publication is implied by this gate.

## 9. Acceptance Criteria

- The user can start, stop, and cancel dictation from the existing composer.
- A recording cannot exceed 60 seconds.
- The approved local model performs transcription without an external speech API.
- The returned transcript is editable and never auto-submitted.
- Existing textarea content is not lost on permission, network, model, or validation
  errors.
- Only one transcription runs at a time, with no unbounded queue.
- Microphone tracks and temporary audio references/files are released on every exit
  path.
- No audio is stored in browser persistent storage, PostgreSQL, Redis, or logs.
- Automated tests do not use live providers or user story data.
- Relevant regressions and quality gates pass with recorded evidence.

## 10. Rollback

Each stage must remain separable. Before final acceptance, rollback means removing
only that stage's new route/service, model integration, or frontend control while
leaving the existing text composer unchanged. Model-cache deletion is a separate,
explicit owner action because it is destructive and does not affect application
correctness.

## 11. Decisions Reserved for Gate 1

These decisions require measured evidence and explicit approval:

- Exact dependency versions and whether local CPython is compatible.
- Primary-model viability on 6 GB VRAM; otherwise explicit use of `whisper-small`.
- Hugging Face cache location and disk budget.
- Supported browser-produced media types and maximum request bytes.
- Measured latency accepted for the 60-second maximum recording.

## 12. Verified Local Implementation

- Model: `openai/whisper-large-v3-turbo`, Hugging Face commit `41f01f3fe87f28c78e2fbf8b568835947dd65ed9`.
- Runtime: RTX 3050 Laptop GPU, CUDA FP16, one in-flight transcription.
- Dependencies: `torch==2.14.0+cu130`, `transformers==5.16.1`, `av==18.1.0`.
- Limits: 60 seconds, 10,000,000 request bytes, WebM/Ogg/MP4 audio.
- Measured probe: 60 seconds of synthetic silence in 2.994 seconds; peak allocated GPU memory 1755.5 MiB.
- Live app acceptance: root page and static controller returned 200; synthetic WebM request returned 200 through `/api/v1/ai/transcriptions` in 11.94 seconds including first model load.
- Verification: 61 backend tests passed; both frontend contract scripts passed; Ruff baseline gate passed.
- Retention: decoding is in memory, no temporary audio file or persistent audio store is created, and audio/transcript content is not logged.
- Browser limitation: automated browser control was unavailable; owner microphone permission and real-speech acceptance remain manual at Gate 5.
