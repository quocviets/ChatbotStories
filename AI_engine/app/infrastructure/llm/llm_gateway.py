import sys
import os
import time
import logging
import asyncio
import random
import hashlib
import json
from app.application.dto.story_dtos import LLMRequest, LLMResponse, LLMUsage
from app.config import MODEL_REGISTRY, FALLBACKS
from app.domain.exceptions.story_exceptions import ProviderException
from app.infrastructure.llm.providers.openai_provider import OpenAIProvider
from app.infrastructure.llm.providers.anthropic_provider import AnthropicProvider
from app.infrastructure.llm.providers.gemini_provider import GeminiProvider
from app.infrastructure.llm.providers.ollama_provider import OllamaProvider

logger = logging.getLogger(__name__)

_PROVIDERS = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "google": GeminiProvider,
    "ollama": OllamaProvider,
}


def _get_provider(model_alias: str):
    config = MODEL_REGISTRY.get(model_alias)
    if not config:
        raise ValueError(f"Model alias '{model_alias}' is not registered.")
    if not config.get("enabled", True):
        raise ValueError(f"Model alias '{model_alias}' is disabled.")
    provider_cls = _PROVIDERS.get(config["provider"])
    if not provider_cls:
        raise ValueError(f"Unsupported LLM provider: {config['provider']}")
    return provider_cls(config["model_name"])


def _mock_mode_enabled() -> bool:
    return "pytest" in sys.modules or os.getenv("TESTING") == "true"

# --- Mock Data Helpers ---
VIETNAMESE_WORDS = ["Cánh cửa bí mật khẽ mở", "Bàn tay nắm chặt thanh kiếm", "Tiếng sấm vang xé bầu trời", "Dấu vết ma pháp còn sót lại"]

def generate_mock_story(request_text: str, target_word_count: int) -> str:
    sentences = [f"Chương truyện sinh ngẫu nhiên (Mock mode) cho yêu cầu: '{request_text}'\n"]
    while len(" ".join(sentences).split()) < target_word_count:
        sentences.append(f"{random.choice(VIETNAMESE_WORDS)}, {random.choice(VIETNAMESE_WORDS).lower()}.")
    return "\n\n".join(sentences)


def get_mock_embedding(text: str) -> list[float]:
    hasher = hashlib.md5(text.encode('utf-8'))
    seed = int(hasher.hexdigest(), 16) % 10000
    random.seed(seed)
    vector = [random.uniform(-1.0, 1.0) for _ in range(1536)]
    norm = sum(x*x for x in vector) ** 0.5
    return [x/norm for x in vector]


class LLMGateway:
    """Gateway managing routing, API key verification, provider delegation, and error fallbacks."""
    
    async def get_embeddings(self, text: str) -> list[float]:
        """Fetch embeddings; deterministic vectors are only available in test mode."""
        if _mock_mode_enabled():
            return get_mock_embedding(text)
        import app.config as current_config
        try:
            if current_config.OPENAI_API_KEY:
                provider = OpenAIProvider("text-embedding-3-small")
            elif current_config.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY"):
                provider = GeminiProvider("gemini-embedding-2")
            else:
                raise ProviderException(
                    "OPENAI_API_KEY or GEMINI_API_KEY is required for embeddings."
                )
            return await provider.get_embeddings(text)
        except ProviderException:
            raise
        except Exception as e:
            raise ProviderException(f"Embeddings provider failed: {e}") from e

    async def generate(self, model_alias: str, request: LLMRequest, stream_handler=None, _tried: set[str] | None = None) -> LLMResponse:
        """Generates completion text. Automatically falls back to mock logic if keys are missing."""
        tried = _tried if _tried is not None else set()
        if model_alias in tried:
            raise RuntimeError(f"LLM fallback cycle detected at '{model_alias}'.")
        tried.add(model_alias)

        config = MODEL_REGISTRY.get(model_alias)
        if not config:
            raise ValueError(f"Model alias {model_alias} not found.")
        if _mock_mode_enabled():
            return await self._generate_mock(model_alias, request, stream_handler)

        provider_name = config["provider"]
        import app.config as current_config
        has_key = (
            (provider_name == "openai" and current_config.OPENAI_API_KEY) or
            (provider_name == "anthropic" and current_config.ANTHROPIC_API_KEY) or
            (provider_name == "google" and (current_config.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY"))) or
            (provider_name == "ollama")
        )
        
        if not has_key:
            raise ProviderException(f"API key is not configured for provider '{provider_name}'.")

        try:
            provider = _get_provider(model_alias)
            if stream_handler and callable(stream_handler):
                # Execute with streaming
                content_accum = []
                async for chunk in provider.stream(request):
                    content_accum.append(chunk)
                    await stream_handler(chunk)
                content = "".join(content_accum)
                return LLMResponse(
                    provider=provider_name,
                    model=config["model_name"],
                    content=content,
                    usage=LLMUsage(input_tokens=0, output_tokens=0, total_tokens=0),
                    latency_ms=0
                )
            else:
                return await provider.generate(request)
        except Exception as e:
            logger.error(f"LLM call failed for alias '{model_alias}' ({e}). Attempting fallback...")
            # Try fallbacks
            fallbacks = FALLBACKS.get(model_alias, [])
            primary_error = e
            for fb_alias in fallbacks:
                fb_config = MODEL_REGISTRY.get(fb_alias)
                if fb_config and fb_config.get("enabled") and fb_alias not in tried:
                    logger.info(f"Falling back to model alias '{fb_alias}'...")
                    try:
                        return await self.generate(fb_alias, request, stream_handler, tried)
                    except Exception as fallback_error:
                        logger.error(f"Fallback '{fb_alias}' failed: {fallback_error}")

            raise ProviderException(f"LLM provider '{model_alias}' failed: {primary_error}") from primary_error


    async def _generate_mock(self, model_alias: str, request: LLMRequest, stream_handler=None) -> LLMResponse:
        """Simulates latency and generates mocked, structural outputs."""
        start_time = time.time()
        await asyncio.sleep(0.5)
        
        content = ""
        prompt_content = " ".join([m["content"] for m in request.messages]) + " " + request.system_prompt
        
        if "PLANNER" in request.system_prompt.upper() or "PLAN" in request.system_prompt.upper():
            plan = {
                "chapter_goal": "Nhân vật chính đối mặt với sự phản bội ẩn giấu",
                "chapter_type": "suspense",
                "target_word_count": request.max_tokens,
                "pov_character": "character_001",
                "tone": "dark suspense",
                "required_scenes": [
                    {
                        "order": 1,
                        "goal": "Nhân vật chính đột nhập thư phòng để tìm bằng chứng",
                        "location": "old_castle_library",
                        "characters": ["character_001"]
                    },
                    {
                        "order": 2,
                        "goal": "Người cố vấn bất ngờ xuất hiện từ phía sau",
                        "location": "old_castle_library",
                        "characters": ["character_001", "mentor_002"]
                    }
                ],
                "continuity_constraints": [
                    "Nhân vật chính đang bị thương ở tay trái",
                    "Không được tiết lộ toàn bộ âm mưu"
                ],
                "ending_hook": "Cánh cửa phòng bị sập khóa từ bên ngoài"
            }
            content = json.dumps(plan, ensure_ascii=False, indent=2)
        elif "ANALYZER" in request.system_prompt.upper() or "CHECK" in request.system_prompt.upper():
            attempt = request.metadata.get("attempt", 0)
            if attempt == 0:
                analysis = {
                    "passed": False,
                    "score": 75,
                    "issues": [
                        {
                            "type": "CONTEXT_ISSUE",
                            "severity": "HIGH",
                            "description": "[PONYTAIL_ISSUE] Nhân vật chính bỗng nhiên cầm kiếm bằng tay trái dù tay trái đang bị thương nặng.",
                            "suggested_action": "Sửa lại chi tiết hành động tay trái thành cố gắng mở cửa hoặc tránh dùng lực mạnh."
                        }
                    ],
                    "primary_issue_type": "CONTEXT_ISSUE"
                }
            else:
                analysis = {
                    "passed": True,
                    "score": 92,
                    "issues": [],
                    "primary_issue_type": None
                }
            content = json.dumps(analysis, ensure_ascii=False, indent=2)
        else:
            target_words = int(request.metadata.get("target_word_count", 1500))
            content = generate_mock_story(prompt_content[:150] + "...", target_words)

        if stream_handler and callable(stream_handler):
            chunk_size = max(5, len(content) // 10)
            for i in range(0, len(content), chunk_size):
                await asyncio.sleep(0.05)
                chunk = content[i:i+chunk_size]
                await stream_handler(chunk)

        latency = int((time.time() - start_time) * 1000)
        tokens = len(content.split()) * 2
        return LLMResponse(
            provider="mock",
            model=model_alias,
            content=content,
            finish_reason="stop",
            usage=LLMUsage(input_tokens=100, output_tokens=tokens, total_tokens=100+tokens),
            latency_ms=latency
        )
