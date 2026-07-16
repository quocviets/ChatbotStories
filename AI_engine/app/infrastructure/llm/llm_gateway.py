import time
import logging
import asyncio
import random
import hashlib
import json
from typing import AsyncIterator, Any
from app.application.dto.story_dtos import LLMRequest, LLMResponse, LLMUsage
from app.config import (
    MODEL_REGISTRY, FALLBACKS, 
    OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY
)
from app.infrastructure.llm.provider_factory import LLMProviderFactory

logger = logging.getLogger(__name__)

# --- Mock Data Helpers ---
VIETNAMESE_WORDS = [
    "Một buổi sáng đầy sương mù", "cánh cửa bí mật khẽ mở", "hành lang tối tăm và tĩnh lặng",
    "bước chân dồn dập vang lên", "nụ cười nham hiểm của người cố vấn", "bức thư mật màu vàng úa",
    "ngọn nến lập lòe trong đêm", "Minh nắm chặt thanh kiếm trong tay", "sự phản bội đau đớn",
    "tiếng sấm vang lên xé toạc bầu trời", "ánh mắt nghi ngờ lẫn nhau", "Hội Đồng Bóng Tối đang hành động",
    "những lời hứa hẹn trong quá khứ", "bí mật của lâu đài cổ", "cánh rừng rậm rì rào trong gió",
    "dấu vết ma pháp còn sót lại", "chất độc không màu không mùi", "chiếc nhẫn gia tộc bị vỡ vụn"
]

def generate_mock_story(request_text: str, target_word_count: int) -> str:
    paragraphs = []
    paragraphs.append(f"Chương truyện sinh ngẫu nhiên (Mock mode) cho yêu cầu: '{request_text}'\n")
    
    current_words = 0
    while current_words < target_word_count:
        sentence_count = random.randint(4, 7)
        sentences = []
        for _ in range(sentence_count):
            clause1 = random.choice(VIETNAMESE_WORDS)
            clause2 = random.choice(VIETNAMESE_WORDS).lower()
            clause3 = random.choice(VIETNAMESE_WORDS).lower()
            sentences.append(f"{clause1}, {clause2} và {clause3}.")
        
        para = " ".join(sentences)
        paragraphs.append(para)
        current_words += len(para.split())
        
    return "\n\n".join(paragraphs)


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
        """Fetches embeddings from OpenAI or generates mock embeddings."""
        if not OPENAI_API_KEY:
            logger.info("Using mock embeddings (OPENAI_API_KEY missing)")
            return get_mock_embedding(text)
        try:
            from app.infrastructure.llm.providers.openai_provider import OpenAIProvider
            provider = OpenAIProvider("text-embedding-3-small")
            return await provider.get_embeddings(text)
        except Exception as e:
            logger.error(f"Failed to get embeddings: {e}. Falling back to mock embeddings.")
            return get_mock_embedding(text)

    async def generate(self, model_alias: str, request: LLMRequest, stream_handler=None) -> LLMResponse:
        """Generates completion text. Automatically falls back to mock logic if keys are missing."""
        config = MODEL_REGISTRY.get(model_alias)
        if not config:
            raise ValueError(f"Model alias {model_alias} not found.")

        provider_name = config["provider"]
        has_key = (
            (provider_name == "openai" and OPENAI_API_KEY) or
            (provider_name == "anthropic" and ANTHROPIC_API_KEY) or
            (provider_name == "google" and GEMINI_API_KEY) or
            (provider_name == "ollama") # Ollama doesn't require cloud API keys
        )
        
        if not has_key:
            logger.info(f"API key missing for provider {provider_name}. Running in Mock Mode.")
            return await self._generate_mock(model_alias, request, stream_handler)

        try:
            provider = LLMProviderFactory.get_provider(model_alias)
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
            for fb_alias in fallbacks:
                fb_config = MODEL_REGISTRY.get(fb_alias)
                if fb_config and fb_config.get("enabled"):
                    logger.info(f"Falling back to model alias '{fb_alias}'...")
                    return await self.generate(fb_alias, request, stream_handler)
            
            # If all else fails, use mock fallback to prevent crash in test environment
            logger.warning("All fallbacks exhausted. Yielding mock completion.")
            return await self._generate_mock(model_alias, request, stream_handler)

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
