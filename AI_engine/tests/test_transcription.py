from app.api.v1.transcription_router import get_transcriber, router
from app.infrastructure.speech_to_text import (
    TranscriberBusyError,
    TranscriptionUnavailableError,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient


class FakeTranscriber:
    def __init__(self, result: str = "Xin chào", error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls: list[tuple[bytes, str]] = []

    async def transcribe(self, audio: bytes, media_type: str) -> str:
        self.calls.append((audio, media_type))
        if self.error:
            raise self.error
        return self.result


def make_client(transcriber: FakeTranscriber) -> TestClient:
    test_app = FastAPI()
    test_app.include_router(router, prefix="/api/v1/ai")
    test_app.dependency_overrides[get_transcriber] = lambda: transcriber
    return TestClient(test_app)


def test_transcription_returns_editable_text():
    transcriber = FakeTranscriber()

    response = make_client(transcriber).post(
        "/api/v1/ai/transcriptions",
        content=b"recorded-audio",
        headers={"Content-Type": "audio/webm;codecs=opus"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "code": 200,
        "message": "Audio transcribed successfully",
        "data": {"text": "Xin chào"},
    }
    assert transcriber.calls == [(b"recorded-audio", "audio/webm")]


def test_transcription_accepts_pcm_wav_fallback():
    transcriber = FakeTranscriber()

    response = make_client(transcriber).post(
        "/api/v1/ai/transcriptions",
        content=b"wav recording",
        headers={"Content-Type": "audio/wav"},
    )

    assert response.status_code == 200
    assert transcriber.calls == [(b"wav recording", "audio/wav")]


def test_transcription_rejects_unsupported_media_without_inference():
    transcriber = FakeTranscriber()

    response = make_client(transcriber).post(
        "/api/v1/ai/transcriptions",
        content=b"not-audio",
        headers={"Content-Type": "text/plain"},
    )

    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "UNSUPPORTED_MEDIA_TYPE"
    assert transcriber.calls == []


def test_transcription_rejects_empty_audio_without_inference():
    transcriber = FakeTranscriber()

    response = make_client(transcriber).post(
        "/api/v1/ai/transcriptions",
        content=b"",
        headers={"Content-Type": "audio/webm"},
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "EMPTY_AUDIO"
    assert transcriber.calls == []


def test_transcription_stops_reading_oversized_audio(monkeypatch):
    from app.api.v1 import transcription_router

    monkeypatch.setattr(transcription_router, "MAX_AUDIO_BYTES", 4)
    transcriber = FakeTranscriber()

    response = make_client(transcriber).post(
        "/api/v1/ai/transcriptions",
        content=b"12345",
        headers={"Content-Type": "audio/webm"},
    )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "AUDIO_TOO_LARGE"
    assert transcriber.calls == []


def test_transcription_returns_busy_without_queueing():
    transcriber = FakeTranscriber(error=TranscriberBusyError())

    response = make_client(transcriber).post(
        "/api/v1/ai/transcriptions",
        content=b"audio",
        headers={"Content-Type": "audio/webm"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "TRANSCRIBER_BUSY"


def test_transcription_hides_inference_failure_details():
    transcriber = FakeTranscriber(error=TranscriptionUnavailableError("secret decoder detail"))

    response = make_client(transcriber).post(
        "/api/v1/ai/transcriptions",
        content=b"audio",
        headers={"Content-Type": "audio/webm"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "TRANSCRIPTION_UNAVAILABLE",
        "message": "Speech transcription is unavailable",
    }
