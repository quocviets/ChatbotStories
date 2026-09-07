from app.application.commands.story_commands import GenerateChapterCommand
from app.application.dto.story_dtos import AnalysisResult


def _as_list(value) -> list[str]:
    if not value:
        return []
    return [value] if isinstance(value, str) else list(value)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))


def _bullets(values: list[str], empty: str = "- Không có.") -> str:
    values = _unique(values)
    return "\n".join(f"- {value}" for value in values) if values else empty


def _memory_text(memory) -> str:
    return memory.get("content", "") if isinstance(memory, dict) else str(memory)


class PromptBuilder:
    async def build(
        self,
        command: GenerateChapterCommand,
        plan: dict,
        context: dict,
        previous_analysis: AnalysisResult | None = None,
        preserve_feedback: str | None = None,
    ) -> tuple[str, str]:
        chapter_override = command.chapter.chapter_tone_override
        master_tone = command.chapter.master_tone
        if chapter_override and chapter_override.strip():
            active_tone = f"GHI ĐÈ THEO CHƯƠNG: {chapter_override.strip()}"
        elif master_tone and master_tone.strip():
            active_tone = f"MẶC ĐỊNH BỘ TRUYỆN: {master_tone.strip()}"
        else:
            active_tone = plan.get("tone", "Thô mộc, tự nhiên, bộc trực")

        system_prompt = (
            "Bạn là tác giả tiểu thuyết dài tập. Viết tự nhiên, rõ và có nhịp; giữ đúng cốt truyện.\n"
            "- Không giải thích lại điều hành động đã thể hiện.\n"
            "- Không tổng kết ý nghĩa sau mỗi cảnh và không viết kết luận thay độc giả.\n"
            "- Không để nhân vật nói lại thông tin mà mọi người trong cảnh đều đã biết.\n"
            "- Không lặp cùng một ý qua lời kể, nội tâm và lời thoại.\n"
            "- Không biến scene plan thành từng đoạn văn tương ứng một-một.\n"
            "- Không áp dụng show-don't-tell máy móc; có thể kể trực tiếp để truyền thông tin nhanh.\n"
            "- Không biến mọi cảm xúc thành siết tay, tim đập hoặc ánh mắt lóe lên.\n"
            "- Giữ cách nói khác nhau giữa các nhân vật; tránh lời thoại báo cáo và suy luận quá đầy đủ.\n"
            "- Tránh các sáo ngữ AI như 'ánh mắt đong đầy xúc cảm', 'không gian như ngưng đọng', "
            "'cuộc hành trình đầy hiểm nguy' và 'chặng đường phía trước'."
        )

        must_preserve = list(context.get("must_preserve_facts", command.constraints))
        continuity_only = list(
            context.get("continuity_only", plan.get("continuity_constraints", []))
        )
        recent_chapters = context.get("recent_prose_reference", context.get("recent_chapters", []))
        character_state = [_memory_text(item) for item in context.get("character_state", [])]
        world_constraints = [_memory_text(item) for item in context.get("world_constraints", [])]
        relevant_memories = [_memory_text(item) for item in context.get("relevant_memories", [])]

        scene_lines = []
        forbidden_changes = []
        for index, scene in enumerate(plan.get("required_scenes", []), start=1):
            scene_id = scene.get("scene_id") or scene.get("order") or f"scene_{index}"
            objective = scene.get("objective") or scene.get("goal") or ""
            participants = _as_list(scene.get("participants", scene.get("characters", [])))
            mandatory_facts = _as_list(scene.get("mandatory_facts"))
            state_before = _as_list(scene.get("state_before"))
            state_after = _as_list(scene.get("state_after"))
            scene_forbidden = _as_list(scene.get("forbidden_changes"))
            must_preserve.extend(mandatory_facts)
            forbidden_changes.extend(scene_forbidden)
            scene_lines.append(
                f"- {scene_id}: objective={objective}; conflict={scene.get('conflict', '')}; "
                f"participants={', '.join(participants) or 'không xác định'}; "
                f"location={scene.get('location', '')}; "
                f"state_before={'; '.join(state_before) or 'không có'}; "
                f"state_after={'; '.join(state_after) or 'không có'}."
            )

        character_lines = []
        character_wiki = command.chapter.character_wiki or {}
        for name, raw_info in character_wiki.items():
            info = raw_info.model_dump() if hasattr(raw_info, "model_dump") else raw_info
            info = info if isinstance(info, dict) else {}
            status = info.get("status", "Đang sống")
            voice = [
                f"nhịp nói={info.get('speech_rhythm')}" if info.get("speech_rhythm") else "",
                f"từ ngữ={info.get('word_choice')}" if info.get("word_choice") else "",
                f"khi xung đột={info.get('conflict_style')}" if info.get("conflict_style") else "",
                f"cách lộ cảm xúc={info.get('emotional_leak')}"
                if info.get("emotional_leak")
                else "",
                f"tránh={', '.join(info.get('avoids', []))}" if info.get("avoids") else "",
            ]
            character_lines.append(
                f"{name} ({info.get('role', '')}; {status}): "
                f"{'; '.join(part for part in voice if part) or 'chưa có hồ sơ giọng riêng'}."
            )
            if "Đã chết" in status or "Hy sinh" in status:
                forbidden_changes.append(
                    f"{name} chỉ xuất hiện qua hồi tưởng hoặc lời kể, không trực tiếp hành động hay nói chuyện."
                )

        recent_text = (
            "\n".join(
                f"--- Chương trước, bản {chapter.get('version_number', '?')} ---\n"
                f"{chapter.get('content', '')}"
                for chapter in recent_chapters
            )
            or "- Không có."
        )

        outline = command.chapter.condensed_outline or command.chapter.master_outline
        outline_text = (
            f"\nĐề cương tổng quát chỉ là ranh giới cốt truyện, không mở rộng từng dòng:\n{outline.strip()}"
            if outline and outline.strip()
            else ""
        )
        feedback_text = ""
        if previous_analysis and not previous_analysis.passed:
            feedback_text += "\nLỗi của bản trước cần tránh:\n" + _bullets(
                [
                    f"{issue.description} — {issue.suggested_action or 'sửa đúng vấn đề'}"
                    for issue in previous_analysis.issues
                ]
            )
        if preserve_feedback:
            feedback_text += f"\nPhản hồi của người dùng:\n{preserve_feedback}"

        user_prompt = (
            f"[1. WRITING TASK]\n"
            f"Yêu cầu: {command.request}\n"
            f"Tiêu đề dự kiến: {command.chapter.title or 'Không có'}"
            f"{outline_text}{feedback_text}\n\n"
            f"[2. POINT OF VIEW AND TONE]\n"
            f"- POV: {plan.get('pov_character') or command.chapter.pov_character_id or 'Nhân vật chính'}\n"
            f"- Tone: {active_tone}\n\n"
            f"[3. CHARACTER VOICE]\n"
            f"{_bullets(character_lines, '- Chưa có hồ sơ giọng nhân vật.')}\n"
            f"Trạng thái nhân vật chỉ để giữ nhất quán, không đọc lại như hồ sơ:\n"
            f"{_bullets(character_state)}\n\n"
            f"[4. SCENE PLAN]\n"
            f"Đây là các beat cần đạt, không phải dàn đoạn để mở rộng một-một:\n"
            f"{chr(10).join(scene_lines) or '- Không có scene bắt buộc.'}\n\n"
            f"[5. MUST PRESERVE]\n"
            f"Các sự thật sau phải giữ đúng nhưng không bắt buộc phải nhắc lại nếu cảnh không cần:\n"
            f"{_bullets(must_preserve)}\n"
            f"Quy tắc thế giới không được vi phạm:\n"
            f"{_bullets(world_constraints)}\n\n"
            f"[6. CONTINUITY ONLY]\n"
            f"Chỉ dùng để kiểm tra tính liên tục; đây không phải nội dung bắt buộc phải nhắc lại:\n"
            f"{_bullets(continuity_only)}\n"
            f"Ký ức chỉ dùng khi liên quan trực tiếp đến chương hiện tại:\n"
            f"{_bullets(relevant_memories)}\n\n"
            f"[7. RECENT PROSE REFERENCE]\n"
            f"Chỉ tham khảo điểm nối, nhịp và giọng; không tóm tắt hoặc chép lại:\n"
            f"{recent_text}\n\n"
            f"[8. FORBIDDEN CHANGES]\n"
            f"{_bullets(forbidden_changes)}\n\n"
            f"[9. OUTPUT REQUIREMENTS]\n"
            f"- Chỉ trả nội dung văn xuôi của chương mới, không chào hỏi, giải thích hoặc thêm tiêu đề.\n"
            f"- Dùng văn bản thuần; không dùng Markdown hoặc ký hiệu định dạng như *, ** hay #.\n"
            f"- Không tự thêm tình tiết để lấp đủ dàn ý.\n"
            f"- Độ dài mục tiêu: {plan.get('target_word_count', command.chapter.target_word_count)} từ."
        )
        return system_prompt, user_prompt
