import json
import httpx
import time
import logging
from typing import AsyncIterator
from app.application.dto.story_dtos import LLMRequest, LLMResponse, LLMUsage
from app.config import OPENAI_API_KEY

logger = logging.getLogger(__name__)

class OpenAIProvider:
    def __init__(self, model_name: str):
        self.model_name = model_name

    async def generate(self, request: LLMRequest) -> LLMResponse:
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not configured.")

        start_time = time.time()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}"
        }
        
        messages = [{"role": "system", "content": request.system_prompt}]
        for m in request.messages:
            messages.append({"role": m["role"], "content": m["content"]})
            
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        
        if request.response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=60.0
            )
            if response.status_code != 200:
                raise ValueError(f"OpenAI Error {response.status_code}: {response.text}")
                
            res_data = response.json()
            content = res_data["choices"][0]["message"]["content"]
            usage = res_data.get("usage", {})
            latency = int((time.time() - start_time) * 1000)
            
            return LLMResponse(
                provider="openai",
                model=self.model_name,
                content=content,
                finish_reason=res_data["choices"][0].get("finish_reason"),
                usage=LLMUsage(
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0)
                ),
                latency_ms=latency,
                raw_response_id=res_data.get("id")
            )

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not configured.")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}"
        }
        
        messages = [{"role": "system", "content": request.system_prompt}]
        for m in request.messages:
            messages.append({"role": m["role"], "content": m["content"]})
            
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": True
        }
        
        async with httpx.AsyncClient() as client:
            async with client.stream("POST", "https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=60.0) as response:
                if response.status_code != 200:
                    raise ValueError(f"OpenAI Streaming Error {response.status_code}")
                
                async for line in response.iter_lines():
                    if not line.strip():
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            chunk_json = json.loads(data_str)
                            chunk_text = chunk_json["choices"][0]["delta"].get("content", "")
                            if chunk_text:
                                yield chunk_text
                        except Exception:
                            pass

    async def get_embeddings(self, text: str) -> list[float]:
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not configured.")
            
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/embeddings",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                json={"input": text, "model": "text-embedding-3-small"},
                timeout=15.0
            )
            if response.status_code == 200:
                data = response.json()
                return data["data"][0]["embedding"]
            else:
                raise ValueError(f"OpenAI Embedding Error {response.status_code}: {response.text}")
