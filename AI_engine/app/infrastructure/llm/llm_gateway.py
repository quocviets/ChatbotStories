import asyncio
import hashlib
import json
import logging
import os
import random
import time

import app.config as current_config
from app.application.dto.story_dtos import ChapterPlan, LLMRequest, LLMResponse, LLMUsage
from app.config import FALLBACKS, MODEL_REGISTRY
from app.domain.exceptions.story_exceptions import ProviderException
from app.infrastructure.llm.providers.anthropic_provider import AnthropicProvider
from app.infrastructure.llm.providers.gemini_provider import GeminiProvider
from app.infrastructure.llm.providers.ollama_provider import OllamaProvider
from app.infrastructure.llm.providers.openai_provider import OpenAIProvider

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


# --- Mock Data Helpers ---
VIETNAMESE_WORDS = [
    "Cánh cửa bí mật khẽ mở",
    "Bàn tay nắm chặt thanh kiếm",
    "Tiếng sấm vang xé bầu trời",
    "Dấu vết ma pháp còn sót lại",
]


def generate_mock_story(request_text: str, target_word_count: int) -> str:
    sentences = [f"Chương truyện sinh ngẫu nhiên (Mock mode) cho yêu cầu: '{request_text}'\n"]
    while len(" ".join(sentences).split()) < target_word_count:
        sentences.append(
            f"{random.choice(VIETNAMESE_WORDS)}, {random.choice(VIETNAMESE_WORDS).lower()}."
        )
    return "\n\n".join(sentences)


def get_mock_embedding(text: str) -> list[float]:
    hasher = hashlib.md5(text.encode("utf-8"))
    seed = int(hasher.hexdigest(), 16) % 10000
    rng = random.Random(seed)
    vector = [rng.uniform(-1.0, 1.0) for _ in range(1536)]
    norm = sum(x * x for x in vector) ** 0.5
    return [x / norm for x in vector]


class LLMGateway:
    """Gateway managing routing, API key verification, provider delegation, and error fallbacks."""

    async def get_embeddings(self, text: str) -> list[float]:
        """Fetch embeddings; deterministic vectors require explicit mock mode."""
        if current_config.LLM_MOCK_MODE:
            return get_mock_embedding(text)
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

    async def generate(
        self,
        model_alias: str,
        request: LLMRequest,
        stream_handler=None,
        _tried: set[str] | None = None,
    ) -> LLMResponse:
        """Generate completion text, using mocks only when explicitly configured."""
        tried = _tried if _tried is not None else set()
        if model_alias in tried:
            raise RuntimeError(f"LLM fallback cycle detected at '{model_alias}'.")
        tried.add(model_alias)

        config = MODEL_REGISTRY.get(model_alias)
        if not config:
            raise ValueError(f"Model alias {model_alias} not found.")
        if current_config.LLM_MOCK_MODE:
            return await self._generate_mock(model_alias, request, stream_handler)

        provider_name = config["provider"]
        has_key = (
            (provider_name == "openai" and current_config.OPENAI_API_KEY)
            or (provider_name == "anthropic" and current_config.ANTHROPIC_API_KEY)
            or (
                provider_name == "google"
                and (current_config.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY"))
            )
            or (provider_name == "ollama")
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
                    usage=LLMUsage(),
                    latency_ms=0,
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
                        fallback_response = await self.generate(
                            fb_alias, request, stream_handler, tried
                        )
                        fallback_response.fallback_from = model_alias
                        fallback_response.fallback_reason = str(primary_error)
                        return fallback_response
                    except Exception as fallback_error:
                        logger.error(f"Fallback '{fb_alias}' failed: {fallback_error}")

            raise ProviderException(
                f"LLM provider '{model_alias}' failed: {primary_error}"
            ) from primary_error

    async def _generate_mock(
        self, model_alias: str, request: LLMRequest, stream_handler=None
    ) -> LLMResponse:
        """Return schema-compatible responses for explicitly selected scenarios."""
        start_time = time.time()
        scenario = request.metadata.get("mock_scenario", "valid")
        if scenario == "timeout":
            raise TimeoutError("Mock provider timed out")
        if scenario == "provider_error":
            raise ProviderException("Mock provider failed")

        purpose = request.metadata.get("purpose", "chapter_writer")
        content = ""
        prompt_content = (
            " ".join([m["content"] for m in request.messages]) + " " + request.system_prompt
        )

        if scenario == "malformed":
            content = "not-json"
        elif scenario == "schema_error":
            content = "{}"
        elif purpose in {"story_planning", "plan_revision"}:
            plan = {
                "chapter_goal": "Nhân vật chính đối mặt với sự phản bội ẩn giấu",
                "chapter_type": "suspense",
                "target_word_count": int(request.metadata.get("target_word_count", 1500)),
                "pov_character": "character_001",
                "tone": "dark suspense",
                "required_scenes": [
                    {
                        "scene_id": "scene_1",
                        "objective": "Find evidence in the library",
                        "location": "old_castle_library",
                    },
                    {
                        "scene_id": "scene_2",
                        "objective": "Confront the unexpected visitor",
                        "location": "old_castle_library",
                    },
                ],
                "continuity_constraints": [
                    "Nhân vật chính đang bị thương ở tay trái",
                    "Không được tiết lộ toàn bộ âm mưu",
                ],
                "ending_hook": "Cánh cửa phòng bị sập khóa từ bên ngoài",
            }
            content = ChapterPlan.model_validate(plan).model_dump_json(indent=2)
        elif purpose == "narrative_critique":
            critique = {"needs_revision": False, "issues": []}
            if scenario == "narrative_issue":
                critique = {
                    "needs_revision": True,
                    "issues": [
                        {
                            "type": "redundant_explanation",
                            "severity": "medium",
                            "paragraph_ids": ["p0001"],
                            "evidence": "Repeated explanation.",
                            "reason": "The narration repeats what the action showed.",
                            "revision_instruction": "Remove only the repeated explanation.",
                            "must_preserve": [],
                        }
                    ],
                }
            content = json.dumps(critique)
        elif purpose == "targeted_revision":
            target_ids = request.metadata.get("target_paragraph_ids") or ["p0001"]
            content = json.dumps(
                {
                    "revisions": [
                        {
                            "paragraph_id": paragraph_id,
                            "revised_text": request.metadata.get(
                                "mock_replacement_text",
                                "Targeted replacement paragraph.",
                            ),
                        }
                        for paragraph_id in target_ids
                    ],
                }
            )
        elif purpose == "story_analysis":
            if scenario == "analysis_failed":
                analysis = {
                    "passed": False,
                    "score": 75,
                    "issues": [
                        {
                            "type": "MANDATORY_EVENT_LOSS",
                            "severity": "HIGH",
                            "description": "[PONYTAIL_ISSUE] Nhân vật chính bỗng nhiên cầm kiếm bằng tay trái dù tay trái đang bị thương nặng.",
                            "suggested_action": "Sửa lại chi tiết hành động tay trái thành cố gắng mở cửa hoặc tránh dùng lực mạnh.",
                        }
                    ],
                    "primary_issue_type": "MANDATORY_EVENT_LOSS",
                }
            else:
                analysis = {"passed": True, "score": 92, "issues": [], "primary_issue_type": None}
            content = json.dumps(analysis, ensure_ascii=False, indent=2)
        elif purpose == "memory_extraction":
            content = json.dumps(
                {
                    "summary": "Approved chapter summary.",
                    "new_facts": ["The protagonist found the letter."],
                    "character_updates": ["The protagonist injured their left hand."],
                }
            )
        else:
            target_words = int(request.metadata.get("target_word_count", 1500))
            content = generate_mock_story(prompt_content[:150] + "...", target_words)

        if stream_handler and callable(stream_handler):
            chunk_size = max(5, len(content) // 10)
            for i in range(0, len(content), chunk_size):
                await asyncio.sleep(0.05)
                chunk = content[i : i + chunk_size]
                await stream_handler(chunk)

        latency = int((time.time() - start_time) * 1000)
        return LLMResponse(
            provider="mock",
            model=model_alias,
            content=content,
            finish_reason="stop",
            usage=LLMUsage(),
            latency_ms=latency,
        )
