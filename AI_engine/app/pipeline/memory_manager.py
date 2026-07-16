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
        
    async def update_memory_after_approval(self, story_id: str, chapter_id: str, 
                                           chapter_content: str, version_number: int) -> dict:
        """Extracts new facts, plot updates, and summarizes the approved chapter. Then stores them in PostgreSQL."""
        system_prompt = (
            "Bạn là thư ký phụ trách biên chép cốt truyện (MEMORY_MANAGER).\n"
            "Hãy đọc chương truyện được phê duyệt và trích xuất thông tin tóm tắt cùng các sự kiện mới."
        )
        
        prompt = (
            f"[CHƯƠNG TRUYỆN ĐÃ ĐƯỢC DUYỆT - BẢN {version_number}]\n"
            f"{chapter_content}\n\n"
            "Hãy trả ra nội dung JSON có dạng:\n"
            "{\n"
            "  \"summary\": \"Tóm tắt ngắn gọn chương (tối đa 200 từ)\",\n"
            "  \"new_facts\": [\n"
            "    \"Chi tiết sự kiện mới xuất hiện (ví dụ: Minh phát hiện thầy phản bội)\"\n"
            "  ],\n"
            "  \"character_updates\": [\n"
            "    \"Thay đổi chỉ số/trạng thái nhân vật (ví dụ: Minh mất lòng tin vào thầy)\"\n"
            "  ]\n"
            "}"
        )
        
        request = LLMRequest(
            model=ROUTING_CONFIG["summarizer"],
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            response_format="json_object",
            temperature=0.3,
            max_tokens=1000
        )
        
        response = await self.gateway.generate(ROUTING_CONFIG["summarizer"], request)
        
        try:
            data = json.loads(response.content)
        except Exception:
            data = {
                "summary": f"Chương {version_number} hoàn tất.",
                "new_facts": ["Sự kiện chính được ghi nhận."],
                "character_updates": []
            }
            
        summary = data.get("summary", "")
        new_facts = data.get("new_facts", [])
        character_updates = data.get("character_updates", [])
        
        # 1. Save chapter summary memory
        summary_emb = await self.gateway.get_embeddings(summary)
        await save_memory_vector(
            story_id=story_id,
            chapter_id=chapter_id,
            memory_type="SUMMARY",
            content=summary,
            metadata={"version_number": version_number},
            embedding=summary_emb
        )
        
        # 2. Save facts
        for fact in new_facts:
            fact_emb = await self.gateway.get_embeddings(fact)
            await save_memory_vector(
                story_id=story_id,
                chapter_id=chapter_id,
                memory_type="NEW_FACT",
                content=fact,
                metadata={"version_number": version_number},
                embedding=fact_emb
            )
            
        # 3. Save character updates
        for cu in character_updates:
            cu_emb = await self.gateway.get_embeddings(cu)
            await save_memory_vector(
                story_id=story_id,
                chapter_id=chapter_id,
                memory_type="CHARACTER_STATE",
                content=cu,
                metadata={"version_number": version_number},
                embedding=cu_emb
            )
            
        return data
