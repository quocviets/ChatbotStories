import asyncio
import io
import logging
import math
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock

from app.config import STT_MAX_DURATION_SECONDS, STT_MIN_RMS, STT_MODEL_NAME

logger = logging.getLogger(__name__)


class TranscriberBusyError(Exception):
    pass


class TranscriptionUnavailableError(Exception):
    pass


class InvalidAudioError(Exception):
    pass


class AudioTooLongError(Exception):
    pass


@dataclass(frozen=True)
class DecodedAudio:
    samples: object
    duration_seconds: float
    rms: float


class LocalWhisperTranscriber:
    def __init__(
        self,
        *,
        decoder: Callable[[bytes, str], DecodedAudio] | None = None,
        inference: Callable[[object], str] | None = None,
        max_duration_seconds: float = STT_MAX_DURATION_SECONDS,
        min_rms: float = STT_MIN_RMS,
        model_name: str = STT_MODEL_NAME,
    ):
        self._decoder = decoder or self._decode_audio
        self._inference = inference or self._transcribe_sync
        self._uses_local_model = inference is None
        self._max_duration_seconds = max_duration_seconds
        self._min_rms = min_rms
        self._model_name = model_name
        self._busy = Lock()
        self._pipeline = None

    async def transcribe(self, audio: bytes, media_type: str) -> str:
        if not self._busy.acquire(blocking=False):
            raise TranscriberBusyError

        try:
            try:
                decoded = await asyncio.to_thread(self._decoder, audio, media_type)
            except InvalidAudioError:
                logger.warning(
                    "Audio decode rejected: media_type=%s bytes=%d",
                    media_type,
                    len(audio),
                    exc_info=True,
                )
                raise
            except Exception as exc:
                raise InvalidAudioError from exc

            logger.info(
                "Audio decoded: duration=%.2fs, rms=%.5f, bytes=%d",
                decoded.duration_seconds,
                decoded.rms,
                len(audio),
            )
            if decoded.duration_seconds > self._max_duration_seconds:
                raise AudioTooLongError
            if decoded.rms < self._min_rms:
                logger.info("Audio below silence threshold rms=%.5f", decoded.rms)
                return ""

            try:
                if self._pipeline is None and self._uses_local_model:
                    # PyTorch's Windows DLLs must initialize on the event-loop thread.
                    __import__("torch")
                text = (await asyncio.to_thread(self._inference, decoded.samples)).strip()
                logger.info("Transcribed text: %r", text)
                return text
            except Exception as exc:
                logger.exception("Local speech transcription failed")
                raise TranscriptionUnavailableError from exc
        finally:
            self._busy.release()

    @staticmethod
    def _decode_audio(audio: bytes, _media_type: str) -> DecodedAudio:
        try:
            import av
            import numpy as np

            chunks = []
            with av.open(io.BytesIO(audio), mode="r") as container:
                streams = [stream for stream in container.streams if stream.type == "audio"]
                if not streams:
                    raise InvalidAudioError
                resampler = av.AudioResampler(format="fltp", layout="mono", rate=16_000)
                for frame in container.decode(streams[0]):
                    for resampled in resampler.resample(frame):
                        chunks.append(resampled.to_ndarray().reshape(-1))
                for resampled in resampler.resample(None):
                    chunks.append(resampled.to_ndarray().reshape(-1))
        except InvalidAudioError:
            raise
        except Exception as exc:
            raise InvalidAudioError from exc

        if not chunks:
            raise InvalidAudioError
        samples = np.concatenate(chunks).astype(np.float32, copy=False)
        rms = math.sqrt(float(np.mean(np.square(samples, dtype=np.float64))))
        return DecodedAudio(
            samples=samples,
            duration_seconds=len(samples) / 16_000,
            rms=rms,
        )

    def _transcribe_sync(self, samples: object) -> str:
        if self._pipeline is None:
            import torch
            from transformers import pipeline

            has_cuda = getattr(torch, "cuda", None) is not None and torch.cuda.is_available()
            device = 0 if has_cuda else -1
            if "whisper" in self._model_name.lower():
                from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor

                model = AutoModelForSpeechSeq2Seq.from_pretrained(
                    self._model_name,
                    dtype=torch.float16,
                    low_cpu_mem_usage=True,
                    local_files_only=True,
                    use_safetensors=True,
                )
                processor = AutoProcessor.from_pretrained(self._model_name, local_files_only=True)
                if device == 0:
                    model.to("cuda")
                self._pipeline = pipeline(
                    "automatic-speech-recognition",
                    model=model,
                    tokenizer=processor.tokenizer,
                    feature_extractor=processor.feature_extractor,
                    dtype=torch.float16,
                    device=device,
                )
            else:
                self._pipeline = pipeline(
                    "automatic-speech-recognition",
                    model=self._model_name,
                    device=device,
                )

        if "whisper" in self._model_name.lower():
            result = self._pipeline(
                samples,
                return_timestamps=False,
                generate_kwargs={
                    "condition_on_prev_tokens": False,
                    "language": "vi",
                    "task": "transcribe",
                    "max_new_tokens": 128,
                    "no_repeat_ngram_size": 3,
                },
            )
        else:
            result = self._pipeline(samples)

        return result["text"]
