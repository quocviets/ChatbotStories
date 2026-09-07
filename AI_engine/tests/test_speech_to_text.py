import asyncio
import sys
from threading import Event
from types import SimpleNamespace

import pytest
from app.infrastructure.speech_to_text import (
    AudioTooLongError,
    DecodedAudio,
    LocalWhisperTranscriber,
    TranscriberBusyError,
    TranscriptionUnavailableError,
)


def decoded(*, seconds: float = 1.0, rms: float = 0.2) -> DecodedAudio:
    return DecodedAudio(samples=[0.1], duration_seconds=seconds, rms=rms)


def test_silence_returns_empty_text_without_running_whisper():
    inference_calls = 0

    def inference(_samples):
        nonlocal inference_calls
        inference_calls += 1
        return "hallucinated text"

    transcriber = LocalWhisperTranscriber(
        decoder=lambda _audio, _media_type: decoded(rms=0.0001),
        inference=inference,
        min_rms=0.003,
    )

    assert asyncio.run(transcriber.transcribe(b"audio", "audio/webm")) == ""
    assert inference_calls == 0


def test_audio_longer_than_sixty_seconds_is_rejected():
    transcriber = LocalWhisperTranscriber(
        decoder=lambda _audio, _media_type: decoded(seconds=60.01),
        inference=lambda _samples: "should not run",
    )

    with pytest.raises(AudioTooLongError):
        asyncio.run(transcriber.transcribe(b"audio", "audio/webm"))


def test_second_transcription_is_rejected_instead_of_queued():
    started = Event()
    release = Event()

    def blocking_inference(_samples):
        started.set()
        release.wait(timeout=2)
        return "done"

    transcriber = LocalWhisperTranscriber(
        decoder=lambda _audio, _media_type: decoded(),
        inference=blocking_inference,
    )

    async def exercise():
        first = asyncio.create_task(transcriber.transcribe(b"first", "audio/webm"))
        await asyncio.to_thread(started.wait, 1)
        with pytest.raises(TranscriberBusyError):
            await transcriber.transcribe(b"second", "audio/webm")
        release.set()
        assert await first == "done"

    asyncio.run(exercise())


def test_inference_failure_releases_the_transcriber_lock():
    def failed_inference(_samples):
        raise RuntimeError("provider internals")

    transcriber = LocalWhisperTranscriber(
        decoder=lambda _audio, _media_type: decoded(),
        inference=failed_inference,
    )

    async def exercise():
        with pytest.raises(TranscriptionUnavailableError):
            await transcriber.transcribe(b"first", "audio/webm")
        with pytest.raises(TranscriptionUnavailableError):
            await transcriber.transcribe(b"second", "audio/webm")

    asyncio.run(exercise())


def test_model_and_processor_load_from_the_local_cache_only(monkeypatch):
    class OfflineLoader:
        @classmethod
        def from_pretrained(cls, _model_name, **kwargs):
            if kwargs.get("local_files_only") is not True:
                raise AssertionError("network lookup attempted")
            return cls()

        def to(self, _device):
            return self

    def fake_pipeline(*args, **kwargs):
        return lambda *call_args, **call_kwargs: {"text": " cached "}

    fake_transformers = SimpleNamespace(
        AutoModelForSpeechSeq2Seq=OfflineLoader,
        AutoProcessor=OfflineLoader,
        pipeline=fake_pipeline,
    )
    OfflineLoader.tokenizer = object()
    OfflineLoader.feature_extractor = object()
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(float16="float16"))
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)

    transcriber = LocalWhisperTranscriber()

    assert transcriber._transcribe_sync([0.1]) == " cached "
