import json
import logging

from app.application.dto.story_dtos import LLMRequest
from app.config import ROUTING_CONFIG
from app.infrastructure.llm.llm_gateway import LLMGateway
from app.infrastructure.vector_store.pgvector_store import save_memory_vector

logger = logging.getLogger(__name__)


class MemoryManager:
    def __init__(self, gateway: LLMGateway):
        self.gateway = gateway

    async def update_memory_after_approval(
        self,
        story_id: str,
        chapter_id: str,
        chapter_content: str,
        version_number: int,
    ) -> dict:
        """Extract and store facts from an approved chapter."""
        system_prompt = (
            "Bạn là thư ký phụ trách biên chép cốt truyện (MEMORY_MANAGER).\n"
            "Đọc chương đã duyệt và trích xuất tóm tắt cùng các sự kiện mới."
        )
        prompt = (
            f"[CHƯƠNG ĐÃ DUYỆT - BẢN {version_number}]\n"
            f"{chapter_content}\n\n"
            "Trả JSON có dạng:\n"
            '{"summary": "Tóm tắt tối đa 200 từ", '
            '"new_facts": ["Sự kiện mới"], '
            '"character_updates": ["Thay đổi trạng thái nhân vật"]}'
        )
        request = LLMRequest(
            model=ROUTING_CONFIG["summarizer"],
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            response_format="json_object",
            temperature=0.3,
            max_tokens=1000,
            metadata={"purpose": "memory_extraction"},
        )
        response = await self.gateway.generate(ROUTING_CONFIG["summarizer"], request)

        try:
            data = json.loads(response.content)
            if not isinstance(data, dict):
                raise ValueError("Memory response must be a JSON object")
            summary = data.get("summary", "")
            new_facts = data.get("new_facts", [])
            character_updates = data.get("character_updates", [])
            if not isinstance(summary, str):
                raise ValueError("Memory summary must be a string")
            if not isinstance(new_facts, list) or not isinstance(character_updates, list):
                raise ValueError("Memory facts and character updates must be lists")
            if any(not isinstance(item, str) for item in new_facts + character_updates):
                raise ValueError("Memory items must be strings")
        except Exception as exc:
            logger.warning(
                "Memory extraction response was unusable; skipping update: %s",
                exc,
            )
            return {
                "status": "SKIPPED",
                "reason": "INVALID_RESPONSE",
                "summary": "",
                "new_facts": [],
                "character_updates": [],
            }

        summary = summary.strip()
        new_facts = [item.strip() for item in new_facts if item.strip()]
        character_updates = [item.strip() for item in character_updates if item.strip()]
        for memory_type, contents in (
            ("SUMMARY", [summary] if summary else []),
            ("NEW_FACT", new_facts),
            ("CHARACTER_STATE", character_updates),
        ):
            for content in contents:
                embedding = await self.gateway.get_embeddings(content)
                await save_memory_vector(
                    story_id=story_id,
                    chapter_id=chapter_id,
                    memory_type=memory_type,
                    content=content,
                    metadata={"version_number": version_number},
                    embedding=embedding,
                )

        return {
            "status": "COMPLETED",
            "summary": summary,
            "new_facts": new_facts,
            "character_updates": character_updates,
        }
