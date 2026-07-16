import logging
from app.application.dto.story_dtos import LLMRequest, LLMResponse
from app.infrastructure.llm.llm_gateway import LLMGateway

logger = logging.getLogger(__name__)

class StoryWriter:
    def __init__(self, gateway: LLMGateway):
        self.gateway = gateway

    async def write_draft(self, model_alias: str, request: LLMRequest, stream_handler=None) -> LLMResponse:
        logger.info(f"Generating draft with model alias: {model_alias}...")
        return await self.gateway.generate(model_alias, request, stream_handler)
