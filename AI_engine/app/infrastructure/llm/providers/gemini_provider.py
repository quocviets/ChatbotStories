import httpx
import time
import logging
from typing import AsyncIterator
from app.application.dto.story_dtos import LLMRequest, LLMResponse, LLMUsage
from app.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

class GeminiProvider:
    def __init__(self, model_name: str):
        self.model_name = model_name

    async def generate(self, request: LLMRequest) -> LLMResponse:
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is not configured.")

        start_time = time.time()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={GEMINI_API_KEY}"
        
        contents = []
        for m in request.messages:
            role = "user" if m["role"] == "user" else "model"
            contents.append({
                "role": role,
                "parts": [{"text": m["content"]}]
            })
            
        payload = {
            "contents": contents,
            "systemInstruction": {
                "parts": [{"text": request.system_prompt}]
            },
            "generationConfig": {
                "temperature": request.temperature,
                "maxOutputTokens": request.max_tokens
            }
        }
        
        if request.response_format == "json_object":
            payload["generationConfig"]["responseMimeType"] = "application/json"

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=60.0)
            if response.status_code != 200:
                raise ValueError(f"Gemini Error {response.status_code}: {response.text}")
                
            res_data = response.json()
            content = res_data["candidates"][0]["content"]["parts"][0]["text"]
            latency = int((time.time() - start_time) * 1000)
            usage = res_data.get("usageMetadata", {})
            
            return LLMResponse(
                provider="google",
                model=self.model_name,
                content=content,
                usage=LLMUsage(
                    input_tokens=usage.get("promptTokenCount", 0),
                    output_tokens=usage.get("candidatesTokenCount", 0),
                    total_tokens=usage.get("totalTokenCount", 0)
                ),
                latency_ms=latency
            )

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        # Simple non-stream fallback to yield in one go for Gemini in this basic wrapper
        response = await self.generate(request)
        yield response.content
