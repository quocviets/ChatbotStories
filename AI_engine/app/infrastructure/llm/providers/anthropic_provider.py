import json
import httpx
import time
import logging
from typing import AsyncIterator
from app.application.dto.story_dtos import LLMRequest, LLMResponse, LLMUsage
from app.config import ANTHROPIC_API_KEY

logger = logging.getLogger(__name__)

class AnthropicProvider:
    def __init__(self, model_name: str):
        self.model_name = model_name

    async def generate(self, request: LLMRequest) -> LLMResponse:
        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not configured.")

        start_time = time.time()
        headers = {
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        
        payload = {
            "model": self.model_name,
            "system": request.system_prompt,
            "messages": request.messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.api.anthropic.com/v1/messages",
                headers=headers,
                json=payload,
                timeout=60.0
            )
            if response.status_code != 200:
                raise ValueError(f"Anthropic Error {response.status_code}: {response.text}")
            
            res_data = response.json()
            content = res_data["content"][0]["text"]
            usage = res_data.get("usage", {})
            latency = int((time.time() - start_time) * 1000)
            
            return LLMResponse(
                provider="anthropic",
                model=self.model_name,
                content=content,
                finish_reason=res_data.get("stop_reason"),
                usage=LLMUsage(
                    input_tokens=usage.get("input_tokens", 0),
                    output_tokens=usage.get("output_tokens", 0),
                    total_tokens=usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
                ),
                latency_ms=latency,
                raw_response_id=res_data.get("id")
            )

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not configured.")

        headers = {
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        
        payload = {
            "model": self.model_name,
            "system": request.system_prompt,
            "messages": request.messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": True
        }
        
        async with httpx.AsyncClient() as client:
            async with client.stream("POST", "https://api.api.anthropic.com/v1/messages", headers=headers, json=payload, timeout=60.0) as response:
                if response.status_code != 200:
                    raise ValueError(f"Anthropic Streaming Error {response.status_code}")
                
                async for line in response.iter_lines():
                    if line.startswith("data: "):
                        data_str = line[6:]
                        try:
                            chunk_json = json.loads(data_str)
                            if chunk_json["type"] == "content_block_delta":
                                chunk_text = chunk_json["delta"].get("text", "")
                                if chunk_text:
                                    yield chunk_text
                        except Exception:
                            pass
