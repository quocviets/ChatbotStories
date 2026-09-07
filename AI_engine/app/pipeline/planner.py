import json
import logging

from app.application.commands.story_commands import GenerateChapterCommand
from app.application.dto.story_dtos import ChapterPlan, LLMRequest
from app.config import ROUTING_CONFIG
from app.infrastructure.llm.llm_gateway import LLMGateway

logger = logging.getLogger(__name__)


def _as_list(value) -> list[str]:
    if not value:
        return []
    return [value] if isinstance(value, str) else list(value)


def _normalize_plan(data: dict) -> dict:
    scenes = []
    for index, scene in enumerate(data.get("required_scenes", []), start=1):
        scenes.append(
            {
                "scene_id": str(scene.get("scene_id") or scene.get("order") or f"scene_{index}"),
                "objective": scene.get("objective") or scene.get("goal") or "",
                "conflict": scene.get("conflict", ""),
                "participants": _as_list(scene.get("participants", scene.get("characters", []))),
                "location": scene.get("location", ""),
                "mandatory_facts": _as_list(scene.get("mandatory_facts")),
                "state_before": _as_list(scene.get("state_before")),
                "state_after": _as_list(scene.get("state_after")),
                "forbidden_changes": _as_list(scene.get("forbidden_changes")),
            }
        )
    return ChapterPlan.model_validate({**data, "required_scenes": scenes}).model_dump()


class StoryPlanner:
    def __init__(self, gateway: LLMGateway):
        self.gateway = gateway

    async def create_plan(
        self,
        command: GenerateChapterCommand,
        recent_chapters: list[dict],
        relevant_memories: list[dict],
    ) -> dict:
        system_prompt = (
            "Bạn là trợ lý lập kế hoạch viết truyện (PLANNER) chuyên nghiệp.\n"
            "Chuyển yêu cầu thành các scene beat ngắn gọn ở dạng JSON, không viết văn xuôi chờ được mở rộng.\n"
            "Không tạo câu văn mẫu, lời thoại mẫu, kết luận đạo lý, phân tích tâm lý dài, "
            "thông điệp người kể phải giải thích hoặc diễn giải đầy đủ suy luận."
        )

        recent_context = ""
        for rc in recent_chapters:
            recent_context += (
                f"--- Chương trước (Bản {rc['version_number']}) ---\n{rc['content'][:600]}...\n\n"
            )

        memory_context = "\n".join(
            [f"- Ký ức: {m['content']} (Loại: {m['memory_type']})" for m in relevant_memories]
        )

        outline_info = ""
        master_outline = getattr(command.chapter, "condensed_outline", None) or getattr(
            command.chapter, "master_outline", None
        )
        if master_outline and master_outline.strip():
            outline_info = f"Đề cương Cốt truyện Tổng quát:\n{master_outline.strip()[:2500]}\n\n"

        prompt = (
            f"Yêu cầu của người dùng: {command.request}\n\n"
            f"Thông tin bổ sung về chương cần sinh:\n"
            f"- Tiêu đề dự kiến: {command.chapter.title or 'Không có'}\n"
            f"- Độ dài kỳ vọng: {command.chapter.target_word_count} từ\n"
            f"- Giọng văn: {command.chapter.tone or 'Mặc định'}\n\n"
            f"{outline_info}"
            f"Bối cảnh truyện gần đây:\n{recent_context}\n"
            f"Ký ức liên quan từ Story Bible:\n{memory_context}\n\n"
            f"Các ràng buộc bổ sung: {command.constraints}\n\n"
            "Mỗi scene chỉ ghi dữ kiện vận hành ngắn. Không thêm field ngoài schema sau:\n"
            "{\n"
            '  "chapter_goal": "Mục tiêu tổng quát của chương",\n'
            '  "chapter_type": "Loại chương (ví dụ: revelation, action, suspense)",\n'
            '  "target_word_count": 2000,\n'
            '  "pov_character": "Tên nhân vật kể chuyện",\n'
            '  "tone": "Giọng văn chung",\n'
            '  "required_scenes": [\n'
            "    {\n"
            '      "scene_id": "scene_1",\n'
            '      "objective": "Mục tiêu ngắn của cảnh",\n'
            '      "conflict": "Trở lực trực tiếp",\n'
            '      "participants": ["Nhân vật"],\n'
            '      "location": "Địa điểm",\n'
            '      "mandatory_facts": ["Dữ kiện bắt buộc"],\n'
            '      "state_before": ["Trạng thái trước cảnh"],\n'
            '      "state_after": ["Trạng thái sau cảnh"],\n'
            '      "forbidden_changes": ["Điều không được thay đổi"]\n'
            "    }\n"
            "  ],\n"
            '  "continuity_constraints": [\n'
            '    "Các ràng buộc liên tục cần tuân thủ (ví dụ: nhân vật đang bị thương ở tay)"\n'
            "  ],\n"
            '  "ending_hook": "Đoạn kết lôi cuốn (cliffhanger)"\n'
            "}"
        )

        request = LLMRequest(
            model=ROUTING_CONFIG["planner"],
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            response_format="json_object",
            temperature=0.3,
            max_tokens=2000,
            metadata={
                "purpose": "story_planning",
                "target_word_count": command.chapter.target_word_count,
            },
        )

        response = await self.gateway.generate(ROUTING_CONFIG["planner"], request)
        try:
            return _normalize_plan(json.loads(response.content))
        except Exception as e:
            logger.error(
                f"Failed to parse Planner JSON response: {e}. Raw content: {response.content}"
            )
            return _normalize_plan(
                {
                    "chapter_goal": command.request,
                    "chapter_type": "standard",
                    "target_word_count": command.chapter.target_word_count,
                    "pov_character": command.chapter.pov_character_id or "Nhân vật chính",
                    "tone": command.chapter.tone or "dramatic",
                    "required_scenes": [
                        {
                            "scene_id": "scene_1",
                            "objective": command.request,
                            "location": "unspecified",
                        }
                    ],
                    "continuity_constraints": command.constraints,
                    "ending_hook": "",
                }
            )

    async def revise_plan(self, original_plan: dict, issues: list) -> dict:
        """Modifies the plan based on critical errors identified by the Analyzer."""
        system_prompt = (
            "Bạn là tác giả kỳ cựu sửa chữa kế hoạch viết truyện.\n"
            "Hãy sửa kế hoạch JSON cũ dựa trên lỗi logic/nhất quán. "
            "Giữ scene ở dạng beat ngắn và không thêm field ngoài schema đang có."
        )

        prompt = (
            f"Kế hoạch cũ:\n{json.dumps(original_plan, ensure_ascii=False, indent=2)}\n\n"
            f"Các vấn đề phát hiện:\n{json.dumps([i.model_dump() if hasattr(i, 'model_dump') else i for i in issues], ensure_ascii=False, indent=2)}\n\n"
            "Hãy điều chỉnh kế hoạch để tránh các lỗi trên và trả về JSON có cấu trúc y hệt."
        )

        request = LLMRequest(
            model=ROUTING_CONFIG["planner"],
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            response_format="json_object",
            temperature=0.3,
            max_tokens=2000,
            metadata={
                "purpose": "plan_revision",
                "target_word_count": original_plan.get("target_word_count", 2000),
            },
        )

        response = await self.gateway.generate(ROUTING_CONFIG["planner"], request)
        try:
            return _normalize_plan(json.loads(response.content))
        except Exception:
            return _normalize_plan(original_plan)
