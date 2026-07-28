import json
import httpx
import time
import logging
from typing import AsyncIterator
from app.application.dto.story_dtos import LLMRequest, LLMResponse

logger = logging.getLogger(__name__)

class OllamaProvider:
    def __init__(self, model_name: str):
        self.model_name = model_name
        self.base_url = "http://localhost:11434/api/generate"

    async def generate(self, request: LLMRequest) -> LLMResponse:
        start_time = time.time()
        
        prompt = f"System: {request.system_prompt}\n\n"
        for m in request.messages:
            prompt += f"{m['role']}: {m['content']}\n"
        prompt += "assistant:"
        
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": request.temperature
            }
        }
        
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.base_url, json=payload, timeout=60.0)
                if response.status_code != 200:
                    raise ValueError(f"Ollama Error {response.status_code}: {response.text}")
                    
                res_data = response.json()
                content = res_data["response"]
                latency = int((time.time() - start_time) * 1000)
                
                return LLMResponse(
                    provider="ollama",
                    model=self.model_name,
                    content=content,
                    latency_ms=latency
                )
            except Exception as e:
                logger.error(f"Failed to communicate with local Ollama service: {e}")
                raise e

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        prompt = f"System: {request.system_prompt}\n\n"
        for m in request.messages:
            prompt += f"{m['role']}: {m['content']}\n"
        prompt += "assistant:"
        
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": request.temperature
            }
        }
        
        async with httpx.AsyncClient() as client:
            async with client.stream("POST", self.base_url, json=payload, timeout=60.0) as response:
                if response.status_code != 200:
                    raise ValueError("Ollama Streaming Error")
                async for line in response.iter_lines():
                    if line:
                        try:
                            chunk_json = json.loads(line)
                            yield chunk_json.get("response", "")
                        except Exception:
                            pass
