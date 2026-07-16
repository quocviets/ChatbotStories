import json
import logging
from app.application.commands.story_commands import GenerateChapterCommand
from app.application.dto.story_dtos import LLMRequest
from app.config import ROUTING_CONFIG
from app.infrastructure.llm.llm_gateway import LLMGateway

logger = logging.getLogger(__name__)

class StoryPlanner:
    def __init__(self, gateway: LLMGateway):
        self.gateway = gateway
        
    async def create_plan(self, command: GenerateChapterCommand, recent_chapters: list[dict], relevant_memories: list[dict]) -> dict:
        system_prompt = (
            "Bạn là trợ lý lập kế hoạch viết truyện (PLANNER) chuyên nghiệp.\n"
            "Nhiệm vụ của bạn là chuyển yêu cầu của người dùng thành kế hoạch viết chương có cấu trúc chi tiết (dạng JSON).\n"
            "Hãy đảm bảo kế hoạch chia phân cảnh hợp lý, thiết lập mục tiêu và ràng buộc đầy đủ."
        )
        
        recent_context = ""
        for rc in recent_chapters:
            recent_context += f"--- Chương trước (Bản {rc['version_number']}) ---\n{rc['content'][:1000]}...\n\n"
            
        memory_context = "\n".join([f"- Ký ức: {m['content']} (Loại: {m['memory_type']})" for m in relevant_memories])
            
        prompt = (
            f"Yêu cầu của người dùng: {command.request}\n\n"
            f"Thông tin bổ sung về chương cần sinh:\n"
            f"- Tiêu đề dự kiến: {command.chapter.title or 'Không có'}\n"
            f"- Độ dài kỳ vọng: {command.chapter.target_word_count} từ\n"
            f"- Giọng văn: {command.chapter.tone or 'Mặc định'}\n\n"
            f"Bối cảnh truyện gần đây:\n{recent_context}\n"
            f"Ký ức liên quan từ Story Bible:\n{memory_context}\n\n"
            f"Các ràng buộc bổ sung: {command.constraints}\n\n"
            "Hãy trả ra dữ liệu dạng JSON khớp với cấu trúc sau, không giải thích gì thêm:\n"
            "{\n"
            "  \"chapter_goal\": \"Mục tiêu tổng quát của chương\",\n"
            "  \"chapter_type\": \"Loại chương (ví dụ: revelation, action, suspense)\",\n"
            "  \"target_word_count\": 2000,\n"
            "  \"pov_character\": \"Tên nhân vật kể chuyện\",\n"
            "  \"tone\": \"Giọng văn chung\",\n"
            "  \"required_scenes\": [\n"
            "    {\"order\": 1, \"goal\": \"Mục tiêu cảnh 1\", \"location\": \"Địa điểm\", \"characters\": [\"Nhân vật\"]}\n"
            "  ],\n"
            "  \"continuity_constraints\": [\n"
            "    \"Các ràng buộc liên tục cần tuân thủ (ví dụ: nhân vật đang bị thương ở tay)\"\n"
            "  ],\n"
            "  \"ending_hook\": \"Đoạn kết lôi cuốn (cliffhanger)\"\n"
            "}"
        )
        
        request = LLMRequest(
            model=ROUTING_CONFIG["planner"],
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            response_format="json_object",
            temperature=0.3,
            max_tokens=2000
        )
        
        response = await self.gateway.generate(ROUTING_CONFIG["planner"], request)
        try:
            return json.loads(response.content)
        except Exception as e:
            logger.error(f"Failed to parse Planner JSON response: {e}. Raw content: {response.content}")
            return {
                "chapter_goal": command.request,
                "chapter_type": "standard",
                "target_word_count": command.chapter.target_word_count,
                "pov_character": command.chapter.pov_character_id or "Nhân vật chính",
                "tone": command.chapter.tone or "dramatic",
                "required_scenes": [{"order": 1, "goal": command.request, "location": "unspecified", "characters": []}],
                "continuity_constraints": command.constraints,
                "ending_hook": "Cliffhanger ngẫu nhiên."
            }

    async def revise_plan(self, original_plan: dict, issues: list) -> dict:
        """Modifies the plan based on critical errors identified by the Analyzer."""
        system_prompt = (
            "Bạn là tác giả kỳ cựu sửa chữa kế hoạch viết truyện.\n"
            "Hãy sửa lại bản kế hoạch (JSON) cũ dựa trên danh sách các lỗi logic/nhất quán được báo cáo."
        )
        
        prompt = (
            f"Kế hoạch cũ:\n{json.dumps(original_plan, ensure_ascii=False, indent=2)}\n\n"
            f"Các vấn đề phát hiện:\n{json.dumps([getattr(i, 'model_dump', lambda: i)() for i in issues], ensure_ascii=False, indent=2)}\n\n"
            "Hãy điều chỉnh kế hoạch để tránh các lỗi trên và trả về JSON có cấu trúc y hệt."
        )
        
        request = LLMRequest(
            model=ROUTING_CONFIG["planner"],
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            response_format="json_object",
            temperature=0.3,
            max_tokens=2000
        )
        
        response = await self.gateway.generate(ROUTING_CONFIG["planner"], request)
        try:
            return json.loads(response.content)
        except Exception:
            return original_plan
