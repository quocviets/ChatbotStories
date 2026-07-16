from typing import Protocol, Any, AsyncIterator
from app.application.dto.story_dtos import LLMRequest, LLMResponse

class LLMProvider(Protocol):
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generates a text completion synchronously."""
        ...

    async def stream(self, request: LLMRequest) -> AsyncIterator[str]:
        """Streams text completion tokens as they are generated."""
        ...
