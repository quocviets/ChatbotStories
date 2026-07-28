from typing import Optional
from app.application.commands.story_commands import GenerateChapterCommand
from app.application.dto.story_dtos import AnalysisResult

class PromptBuilder:
    async def build(self, command: GenerateChapterCommand, plan: dict, context: dict, 
                    previous_analysis: Optional[AnalysisResult] = None, 
                    preserve_feedback: Optional[str] = None) -> tuple[str, str]:

        # Determine active tone (Two-Tier Tone Hierarchy: Chapter Override > Master Tone > Plan Default)
        chapter_override = getattr(command.chapter, "chapter_tone_override", None)
        master_tone = getattr(command.chapter, "master_tone", None)
        
        if chapter_override and chapter_override.strip():
            active_tone = f"GHI ĐÈ THEO CHƯƠNG: {chapter_override.strip()}"
        elif master_tone and master_tone.strip():
            active_tone = f"MẶC ĐỊNH BỘ TRUYỆN: {master_tone.strip()}"
        else:
            active_tone = plan.get("tone", "Thô mộc, tự nhiên, bộc trực")

        system_prompt = (
            "Bạn là tác giả chuyên viết tiểu thuyết mạng dài tập tài ba. "
            "QUY TẮC NGUYÊN TẮC VÀNG VỀ GIỌNG VĂN (ANTI-AI CLICHÉS):\n"
            "- Viết văn xuôi chân thực, thô mộc, dứt khoát và tự nhiên như ngôn ngữ đời thực.\n"
            "- Tuyệt đối CẤM các câu từ hoa mỹ sến sẩm rập khuôn AI (như 'ánh mắt đong đầy xúc cảm', "
            "'khoảnh khắc ấy không gian như ngưng đọng', 'cuộc hành trình đầy hiểm nguy', 'chặng đường phía trước').\n"
            "- Thoại nhân vật bộc trực, thực tế, đúng tâm lý sinh tồn."
        )
        
        # Condensed / Master Outline
        outline_text = ""
        condensed_outline = getattr(command.chapter, "condensed_outline", None) or getattr(command.chapter, "master_outline", None)
        if condensed_outline and condensed_outline.strip():
            outline_text = f"\n[BẢN ĐỒ CỐT TRUYỆN & ĐỀ CƯƠNG TỔNG QUÁT]\n{condensed_outline.strip()}\n"

        # Dynamic Character Wiki Status Check
        char_wiki_text = ""
        character_wiki = getattr(command.chapter, "character_wiki", None)
        if character_wiki and isinstance(character_wiki, dict):
            char_wiki_text = "\n[TRẠNG THÁI THẺ NHÂN VẬT (CHARACTER WIKI)]\n"
            for name, info in character_wiki.items():
                status = info.get("status", "Đang sống") if isinstance(info, dict) else "Đang sống"
                role = info.get("role", "") if isinstance(info, dict) else ""
                char_wiki_text += f"- {name} ({role}): Trạng thái = [{status}]. "
                if "Đã chết" in status or "Hy sinh" in status:
                    char_wiki_text += "CHỈ ĐƯỢC PHÉP xuất hiện qua lời kể, hồi tưởng (flashback), tuyệt đối CẤM cho xuất hiện nói chuyện trực tiếp!\n"
                else:
                    char_wiki_text += "\n"

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
            f"[PHONG CÁCH & GIỌNG VĂN CỐ ĐỊNH]\n"
            f"- Giọng văn áp dụng: {active_tone}\n"
            f"{outline_text}"
            f"{char_wiki_text}\n"
            f"[KẾ HOẠCH CHƯƠNG]\n"
            f"- Mục tiêu chính: {plan.get('chapter_goal')}\n"
            f"- Loại chương: {plan.get('chapter_type')}\n"
            f"- Ngôi kể (POV): {plan.get('pov_character')}\n"
            f"- Phân cảnh chi tiết:\n{scenes_plan}\n"
            f"- Ràng buộc liên tục: {', '.join(plan.get('continuity_constraints', []))}\n"
            f"- Điểm dừng Cliffhanger: {plan.get('ending_hook')}\n\n"
            f"[KÝ ỨC & BỐI CẢNH LIÊN QUAN]\n"
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
