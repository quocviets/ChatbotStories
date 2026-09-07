import asyncio
import logging
import os
import time
from collections.abc import AsyncIterator

import app.config as config
import httpx
from app.application.dto.story_dtos import LLMRequest, LLMResponse, LLMUsage

logger = logging.getLogger(__name__)


class GeminiProvider:
    def __init__(self, model_name: str):
        self.model_name = model_name

    async def get_embeddings(self, text: str) -> list[float]:
        api_key = config.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not configured.")

        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-2:embedContent"
        payload = {"content": {"parts": [{"text": text}]}, "outputDimensionality": 1536}
        async with httpx.AsyncClient(verify=config.LLM_VERIFY_TLS) as client:
            response = await client.post(
                url, headers={"x-goog-api-key": api_key}, json=payload, timeout=60.0
            )
        if response.status_code != 200:
            raise ValueError(f"Gemini embeddings error {response.status_code}: {response.text}")
        return response.json()["embedding"]["values"]

    async def generate(self, request: LLMRequest) -> LLMResponse:
        api_key = config.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not configured.")

        start_time = time.time()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent"
        headers = {"x-goog-api-key": api_key}

        contents = []
        for m in request.messages:
            role = "user" if m["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})

        payload = {
            "contents": contents,
            "systemInstruction": {"parts": [{"text": request.system_prompt}]},
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens,
            },
        }

        if request.response_format == "json_object":
            payload["generationConfig"]["responseMimeType"] = "application/json"

        max_retries = 5
        last_error = None

        for attempt in range(max_retries):
            try:
                async with httpx.AsyncClient(verify=config.LLM_VERIFY_TLS) as client:
                    response = await client.post(url, headers=headers, json=payload, timeout=60.0)

                    if response.status_code == 200:
                        res_data = response.json()
                        content = res_data["candidates"][0]["content"]["parts"][0]["text"]
                        latency = int((time.time() - start_time) * 1000)
                        usage = res_data.get("usageMetadata", {})

                        return LLMResponse(
                            provider="google",
                            model=self.model_name,
                            content=content,
                            usage=LLMUsage(
                                input_tokens=usage.get("promptTokenCount"),
                                output_tokens=usage.get("candidatesTokenCount"),
                                total_tokens=usage.get("totalTokenCount"),
                                usage_available=all(
                                    key in usage
                                    for key in (
                                        "promptTokenCount",
                                        "candidatesTokenCount",
                                        "totalTokenCount",
                                    )
                                ),
                            ),
                            latency_ms=latency,
                        )
                    elif response.status_code == 429:
                        logger.warning(
                            f"Gemini {self.model_name} rate limited (429). Trying instant fallback to gemini-flash-latest / gemini-flash-lite-latest..."
                        )
                        for fb_model in ["gemini-flash-latest", "gemini-flash-lite-latest"]:
                            fb_url = f"https://generativelanguage.googleapis.com/v1beta/models/{fb_model}:generateContent?key={api_key}"
                            try:
                                async with httpx.AsyncClient(
                                    verify=config.LLM_VERIFY_TLS
                                ) as fb_client:
                                    fb_resp = await fb_client.post(
                                        fb_url, headers=headers, json=payload, timeout=60.0
                                    )
                                    if fb_resp.status_code == 200:
                                        res_data = fb_resp.json()
                                        content = res_data["candidates"][0]["content"]["parts"][0][
                                            "text"
                                        ]
                                        usage = res_data.get("usageMetadata", {})
                                        logger.info(f"Fallback to {fb_model} succeeded!")
                                        return LLMResponse(
                                            provider="google",
                                            model=f"{fb_model} (fallback)",
                                            content=content,
                                            usage=LLMUsage(
                                                input_tokens=usage.get("promptTokenCount"),
                                                output_tokens=usage.get("candidatesTokenCount"),
                                                total_tokens=usage.get("totalTokenCount"),
                                                usage_available=all(
                                                    key in usage
                                                    for key in (
                                                        "promptTokenCount",
                                                        "candidatesTokenCount",
                                                        "totalTokenCount",
                                                    )
                                                ),
                                            ),
                                            latency_ms=int((time.time() - start_time) * 1000),
                                        )
                            except Exception as fb_err:
                                logger.warning(f"Fallback {fb_model} failed: {fb_err}")

                        retry_delay = 15
                        try:
                            details = response.json().get("error", {}).get("details", [])
                            for d in details:
                                if "retryDelay" in d:
                                    retry_delay = int(float(d["retryDelay"].replace("s", ""))) + 2
                        except Exception:
                            pass

                        if attempt < max_retries - 1:
                            logger.warning(
                                f"Gemini 429 Rate Limit. Auto-waiting {retry_delay}s for quota window reset (Attempt {attempt + 1}/{max_retries})..."
                            )
                            await asyncio.sleep(retry_delay)
                        else:
                            raise ValueError(f"Gemini Error 429: {response.text}")
                    else:
                        raise ValueError(f"Gemini Error {response.status_code}: {response.text}")
            except Exception as e:
                last_error = e
                rate_limited = "429" in str(e) or "rate" in str(e).lower()
                if attempt < max_retries - 1 and (
                    rate_limited or isinstance(e, httpx.RequestError)
                ):
                    delay = 20 if rate_limited else 3
                    logger.warning(
                        f"Gemini request failed temporarily. Retrying in {delay} seconds... (Attempt {attempt + 1}/{max_retries})"
                    )
                    await asyncio.sleep(delay)
                else:
                    raise

        raise last_error or ValueError("Gemini API call failed after retries.")

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        response = await self.generate(request)
        yield response.content
