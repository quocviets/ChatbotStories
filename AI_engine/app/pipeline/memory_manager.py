import json
from app.application.dto.story_dtos import LLMRequest
from app.config import ROUTING_CONFIG
from app.infrastructure.llm.llm_gateway import LLMGateway
from app.infrastructure.vector_store.pgvector_store import save_memory_vector

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
        
        for memory_type, contents in (
            ("SUMMARY", (summary,)),
            ("NEW_FACT", new_facts),
            ("CHARACTER_STATE", character_updates)
        ):
            for content in contents:
                embedding = await self.gateway.get_embeddings(content)
                await save_memory_vector(
                    story_id=story_id,
                    chapter_id=chapter_id,
                    memory_type=memory_type,
                    content=content,
                    metadata={"version_number": version_number},
                    embedding=embedding
                )
            
        return data
