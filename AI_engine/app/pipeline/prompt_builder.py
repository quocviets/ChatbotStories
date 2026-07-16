import logging
from typing import Optional
from app.application.commands.story_commands import GenerateChapterCommand
from app.application.dto.story_dtos import AnalysisResult

logger = logging.getLogger(__name__)

class PromptBuilder:
    async def build(self, command: GenerateChapterCommand, plan: dict, context: dict, 
                    previous_analysis: Optional[AnalysisResult] = None, 
                    preserve_feedback: Optional[str] = None) -> tuple[str, str]:
        
        system_prompt = (
            "Bạn là tác giả chuyên viết tiểu thuyết mạng dài tập, có khả năng viết lôi cuốn, "
            "giọng văn mượt mà và duy trì tính nhất quán tuyệt đối về nhân vật, bối cảnh."
        )
        
        recent_chapters_text = ""
        for idx, rc in enumerate(context.get("recent_chapters", [])):
            recent_chapters_text += f"\n--- Chương trước (Bản {rc['version_number']}) ---\n{rc['content']}\n"
            
        memories_text = ""
        for m in context.get("relevant_memories", []):
            memories_text += f"- Ký ức ({m['memory_type']}): {m['content']}\n"
            
        scenes_plan = ""
        for scene in plan.get("required_scenes", []):
            scenes_plan += f"Cảnh {scene['order']}: {scene['goal']} (Tại: {scene['location']}, Nhân vật tham gia: {', '.join(scene['characters'])})\n"
            
        user_instruct = (
            f"Hãy viết chương truyện tiếp theo dựa trên kế hoạch và thông tin sau:\n\n"
            f"[KẾ HOẠCH CHƯƠNG]\n"
            f"- Mục tiêu chính: {plan.get('chapter_goal')}\n"
            f"- Loại chương: {plan.get('chapter_type')}\n"
            f"- Ngôi kể (POV): {plan.get('pov_character')}\n"
            f"- Giọng văn/Tone: {plan.get('tone')}\n"
            f"- Phân cảnh chi tiết:\n{scenes_plan}\n"
            f"- Ràng buộc liên tục: {', '.join(plan.get('continuity_constraints', []))}\n"
            f"- Cliffhanger: {plan.get('ending_hook')}\n\n"
            f"[KÝ ỨC & BỒI CẢNH LIÊN QUAN]\n"
            f"{memories_text}\n"
            f"[CHƯƠNG GẦN ĐÂY]\n"
            f"{recent_chapters_text}\n"
        )
        
        if command.constraints:
            user_instruct += f"\n[RÀNG BUỘC CỦA NGƯỜI DÙNG]\n" + "\n".join([f"- {c}" for c in command.constraints]) + "\n"
            
        if previous_analysis and not previous_analysis.passed:
            user_instruct += f"\n[CÁC LỖI CẦN SỬA Ở LẦN VIẾT TRƯỚC (HÃY SỬA LẠI CHO ĐÚNG)]\n"
            for issue in previous_analysis.issues:
                user_instruct += f"- Vấn đề: {issue.description}\n  Gợi ý sửa đổi: {issue.suggested_action}\n"
                
        if preserve_feedback:
            user_instruct += f"\n[Ý KIẾN PHẢN HỒI REGENERATE CỦA USER]\n{preserve_feedback}\n"
            
        user_instruct += (
            f"\n[YÊU CẦU ĐẦU RA]\n"
            f"- Chỉ trả ra nội dung văn xuôi của chương truyện mới.\n"
            f"- Không thêm các câu chào hỏi, giải thích tư duy, hay tiêu đề đầu ra.\n"
            f"- Độ dài văn bản mong muốn: {plan.get('target_word_count', command.chapter.target_word_count)} từ."
        )
        
        return system_prompt, user_instruct
