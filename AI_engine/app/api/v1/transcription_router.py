from functools import lru_cache

from app.api.v1.responses import api_response
from app.infrastructure.speech_to_text import (
    AudioTooLongError,
    InvalidAudioError,
    LocalWhisperTranscriber,
    TranscriberBusyError,
    TranscriptionUnavailableError,
)
from fastapi import APIRouter, Depends, HTTPException, Request, status

router = APIRouter(prefix="/transcriptions", tags=["Transcription"])

ALLOWED_MEDIA_TYPES = {"audio/mp4", "audio/ogg", "audio/wav", "audio/webm"}
MAX_AUDIO_BYTES = 10_000_000


@lru_cache(maxsize=1)
def get_transcriber() -> LocalWhisperTranscriber:
    return LocalWhisperTranscriber()


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


@router.post("", status_code=status.HTTP_200_OK)
async def transcribe_audio(request: Request, transcriber=Depends(get_transcriber)):
    media_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media_type not in ALLOWED_MEDIA_TYPES:
        raise _error(415, "UNSUPPORTED_MEDIA_TYPE", "Unsupported audio format")

    audio = bytearray()
    async for chunk in request.stream():
        audio.extend(chunk)
        if len(audio) > MAX_AUDIO_BYTES:
            raise _error(413, "AUDIO_TOO_LARGE", "Audio exceeds the request-size limit")
    if not audio:
        raise _error(422, "EMPTY_AUDIO", "Audio is empty")

    try:
        text = await transcriber.transcribe(bytes(audio), media_type)
    except TranscriberBusyError as exc:
        raise _error(409, "TRANSCRIBER_BUSY", "Another transcription is in progress") from exc
    except InvalidAudioError as exc:
        raise _error(422, "INVALID_AUDIO", "Audio could not be decoded") from exc
    except AudioTooLongError as exc:
        raise _error(422, "AUDIO_TOO_LONG", "Audio exceeds 60 seconds") from exc
    except TranscriptionUnavailableError as exc:
        raise _error(
            503,
            "TRANSCRIPTION_UNAVAILABLE",
            "Speech transcription is unavailable",
        ) from exc

    return api_response(200, "Audio transcribed successfully", data={"text": text})
