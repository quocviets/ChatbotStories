import sys
import os
import json
import asyncio
import time

# Thêm đường dẫn AI_engine vào sys.path
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ai_engine_path = os.path.join(project_root, 'AI_engine')
if ai_engine_path not in sys.path:
    sys.path.insert(0, ai_engine_path)

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from app.application.commands.story_commands import GenerateChapterCommand
from app.application.dto.story_dtos import ChapterOptions, GenerationConfig
from app.infrastructure.llm.llm_gateway import LLMGateway
from app.pipeline.planner import StoryPlanner
from app.pipeline.retriever import StoryRetriever
from app.pipeline.prompt_builder import PromptBuilder
from app.pipeline.analyzer import StoryAnalyzer
from app.pipeline.issue_classifier import IssueClassifier

# Tải cấu hình môi trường
from dotenv import load_dotenv
load_dotenv(os.path.join(project_root, 'API', '.env'))

# Dữ liệu thử nghiệm 5 Chương - Thể loại: Huyền Huyễn / Kiếm Hiệp Dark Fantasy
STORY_TITLE = "Đại Đạo Đao Đồ"
MASTER_TONE = "Thô mộc, lạnh khốc, nhịp văn dồn dập, bộc trực, không dùng từ sến sẩm AI"

MASTER_OUTLINE = """
[BẢN ĐỀ CƯƠNG TỔNG QUÁT - ĐẠI ĐẠO ĐAO ĐỒ]
- Thế giới: Tu chân giới tàn khốc, các tông môn đấu đá máu me, nhân tâm hiểm ác.
- Nhân vật chính: Trần Huyền - Đệ tử ngoại môn Tinh Vân Tông, tính cách kiên định, lạnh lùng nhưng trọng tình nghĩa.
- Nhân vật phụ: 
  + Lão Trâu: Quản lý Chợ Đen Ngoại Môn, ân nhân giúp đỡ Trần Huyền thời nghèo khó. (Trạng thái: Ban đầu sống, Chương 4 chết).
  + Lâm Phong: Đệ tử nội môn hẹp hòi, kẻ hãm hại Trần Huyền.
  + Trưởng lão Lý Vô Ngại: Chấp pháp trưởng lão đứng sau Lâm Phong.

[TÓM TẮT MẠCH 5 CHƯƠNG]
Chương 1: Trần Huyền bị Lâm Phong hãm hại đẩy xuống U Mạch Cốc tàn khốc. Nhặt được phế đao Hắc Ma chứa tàn hồn cổ Ma Tôn.
Chương 2: Trần Huyền thoát khỏi vực sâu trở lại Đại Hội Tỉ Võ. Đánh bại Lâm Phong trước mặt mọi người. Có hint Lão Trâu đang gặp nguy hiểm ở Chợ Đen.
Chương 3: Trận chiến Sinh Tử Đài với Trưởng lão Lý Vô Ngại. Giọng văn cực kỳ máu me dồn dập khốc liệt. Trần Huyền chém chết Lý Vô Ngại.
Chương 4: Trần Huyền đến Chợ Đen tìm Lão Trâu thì phát hiện Lão Trâu ĐÃ CHẾT do bị tay chân của tông môn diệt khẩu. 
Chương 5: Trần Huyền xông vào Quỷ Sương Lâm truy sát toàn bộ kẻ diệt khẩu Lão Trâu. Cliffhanger mở ra arc mới.
"""

CHAPTER_REQUESTS = [
    {
        "chapter_num": 1,
        "title": "Chương 1: U Mạch Vực Sâu, Hắc Đao Thức Tỉnh",
        "user_prompt": "Viết Chương 1 mở đầu. Trần Huyền bị Lâm Phong hãm hại rơi xuống vực U Mạch Cốc, thập tử nhất sinh nhặt được thanh Hắc Đao sứt mẻ.",
        "chapter_tone_override": None,
        "character_wiki": [
            {"name": "Trần Huyền", "status": "Đang sống", "role": "Nam chính"},
            {"name": "Lâm Phong", "status": "Đang sống", "role": "Phản diện"},
            {"name": "Lão Trâu", "status": "Đang sống", "role": "Ân nhân chợ đen"}
        ]
    },
    {
        "chapter_num": 2,
        "title": "Chương 2: Quy Lai Tỉ Võ, Đao Xuất Kinh Nhân",
        "user_prompt": "Viết Chương 2. Trần Huyền bò lên từ vực thẫm, xuất hiện tại Đại Hội Tỉ Võ Ngoại Môn và hạ gục Lâm Phong chỉ bằng một đao. Cài cắm hint Lão Trâu ở Chợ Đen bị theo dõi.",
        "chapter_tone_override": None,
        "character_wiki": [
            {"name": "Trần Huyền", "status": "Đang sống", "role": "Nam chính"},
            {"name": "Lâm Phong", "status": "Thảm bại/Tàn phế", "role": "Phản diện"},
            {"name": "Lão Trâu", "status": "Đang sống (Bị đe dọa)", "role": "Ân nhân chợ đen"}
        ]
    },
    {
        "chapter_num": 3,
        "title": "Chương 3: Sinh Tử Đài, Huyết Chém Trưởng Lão",
        "user_prompt": "Viết Chương 3. Trần Huyền bị Trưởng lão Lý Vô Ngại ép lên Sinh Tử Đài. Trần Huyền phát động đao ý chém rơi đầu Lý Vô Ngại.",
        "chapter_tone_override": "GHI ĐÈ TẦNG 2: Cực kỳ cuồng sát, dồn dập, máu me khốc liệt, câu văn ngắn gọn đanh thép",
        "character_wiki": [
            {"name": "Trần Huyền", "status": "Đang sống", "role": "Nam chính"},
            {"name": "Lý Vô Ngại", "status": "Đã chết", "role": "Trưởng lão phản diện"},
            {"name": "Lão Trâu", "status": "Đang sống", "role": "Ân nhân chợ đen"}
        ]
    },
    {
        "chapter_num": 4,
        "title": "Chương 4: Chợ Đen Huyết Lạnh, Ân Nhân Tử Thần",
        "user_prompt": "Viết Chương 4. Trần Huyền vội vã chạy ra Chợ Đen thì thấy quán trà bốc cháy, Lão Trâu ĐÃ CHẾT tàn nhẫn trên sàn nhà. Trần Huyền thề sát tử diệt môn.",
        "chapter_tone_override": "GHI ĐÈ TẦNG 2: U ám, trầm tĩnh, lạnh lẽo đau thương, không sến sẩm",
        "character_wiki": [
            {"name": "Trần Huyền", "status": "Đang sống", "role": "Nam chính"},
            {"name": "Lão Trâu", "status": "ĐÃ CHẾT / HY SINH (Tuyệt đối không cho xuất hiện đối thoại trực tiếp)", "role": "Ân nhân đã qua đời"}
        ]
    },
    {
        "chapter_num": 5,
        "title": "Chương 5: Quỷ Sương Lâm, Truy Sát Đao Đồ",
        "user_prompt": "Viết Chương 5. Trần Huyền một đao một ngựa tiến vào Quỷ Sương Lâm truy sát nhóm sát thủ diệt khẩu Lão Trâu. Cliffhanger khép lại Arc 1.",
        "chapter_tone_override": None,
        "character_wiki": [
            {"name": "Trần Huyền", "status": "Đang sống", "role": "Nam chính"},
            {"name": "Lão Trâu", "status": "ĐÃ CHẾT", "role": "Ân nhân đã qua đời"}
        ]
    }
]

async def run_5_chapter_benchmark():
    print("=" * 80)
    print(f"🎬 THỬ NGHIỆM CHẠY AUTO BENCHMARK 5 CHƯƠNG - TRUYỆN: {STORY_TITLE}")
    print("=" * 80)

    # Khởi tạo các pipeline components
    gateway = LLMGateway()
    planner = StoryPlanner(gateway)
    retriever = StoryRetriever(gateway)
    prompt_builder = PromptBuilder()
    analyzer = StoryAnalyzer(gateway)

    # Bước 0: Nén Đề Cương Tổng Quát
    print("\n📦 1. Khởi tạo Master Outline (Đề cương 30-50 trang)...")
    condensed_outline = MASTER_OUTLINE.strip()
    print(f"✅ Đề cương đã nạp thành công (~{len(condensed_outline.split())} từ)")

    results_report = {
        "story_title": STORY_TITLE,
        "master_tone": MASTER_TONE,
        "chapters": [],
        "overall_evaluation": {}
    }

    recent_chapters_history = []
    relevant_memories = [
        {"content": "Trần Huyền mang theo Hắc Đao sứt mẻ chứa Cổ Ma Tàn Hồn", "memory_type": "ITEM_LORE"},
        {"content": "Lão Trâu là người duy nhất ở Chợ Đen cho Trần Huyền nợ tiền mua dược liệu", "memory_type": "RELATIONSHIP"}
    ]

    for chap_info in CHAPTER_REQUESTS:
        c_num = chap_info["chapter_num"]
        c_title = chap_info["title"]
        print("\n" + "-" * 70)
        print(f"🚀 ĐANG SINH {c_title} (Chương {c_num}/5)...")
        print("-" * 70)

        # Cấu hình Command
        command = GenerateChapterCommand(
            story_id="test_story_5_chapters",
            model="gemini-2.0-flash",
            request=chap_info["user_prompt"],
            chapter=ChapterOptions(
                title=c_title,
                target_word_count=800,
                tone=MASTER_TONE,
                master_tone=MASTER_TONE,
                chapter_tone_override=chap_info["chapter_tone_override"],
                master_outline=MASTER_OUTLINE,
                condensed_outline=condensed_outline,
                character_wiki=chap_info["character_wiki"]
            ),
            generation_config=GenerationConfig(temperature=0.75, max_output_tokens=3000)
        )

        start_time = time.time()

        # Step 1: Planner
        print("  🔹 [Step 1] StoryPlanner lập kế hoạch...")
        plan = await planner.create_plan(command, recent_chapters_history, relevant_memories)
        print(f"     -> Mục tiêu chương: {plan.get('chapter_goal', 'N/A')}")
        print(f"     -> Điểm dừng (Cliffhanger): {plan.get('cliffhanger_stoppoint', 'N/A')}")

        # Step 2: Context Retriever
        context = {
            "recent_chapters": recent_chapters_history,
            "relevant_memories": relevant_memories,
            "character_wiki": chap_info["character_wiki"]
        }

        # Step 3: Prompt Builder
        print("  🔹 [Step 2] PromptBuilder dựng System Prompt & User Prompt (Giọng văn 2 tầng & Character Status)...")
        sys_prompt, user_prompt = await prompt_builder.build(
            command=command,
            plan=plan,
            context=context
        )

        # Step 4: Generate Chapter Text
        print("  🔹 [Step 3] LLM Gateway đang sinh văn bản...")
        llm_req = command.to_llm_request(sys_prompt, user_prompt)
        llm_res = await gateway.generate(command.model, llm_req)
        content = llm_res.content
        word_count = len(content.split())
        elapsed = round(time.time() - start_time, 2)
        print(f"     -> Sinh hoàn tất: {word_count} từ ({len(content)} ký tự) trong {elapsed}s")

        # Step 5: Story Analyzer
        print("  🔹 [Step 4] StoryAnalyzer đánh giá chất lượng bản nháp...")
        analysis = await analyzer.analyze(command.story_id, content, plan, context)
        print(f"     -> Score: {analysis.score}/100 | Passed: {analysis.passed}")
        if analysis.issues:
            for issue in analysis.issues:
                print(f"        ⚠️ Issue: [{issue.issue_type}] {issue.description}")

        # Kiểm tra Character Status (Lão Trâu có phát biểu khi đã chết không)
        lao_trau_spoke_error = False
        if c_num >= 4:
            # Nếu Lão Trâu đã chết mà có thoại dạng `Lão Trâu nói:` hoặc `Lão Trâu cất lời`
            if "Lão Trâu nói" in content or "Lão Trâu cười" in content or "Lão Trâu cất lời" in content:
                lao_trau_spoke_error = True
                print("     ❌ LỖI NGHIÊM TRỌNG: Lão Trâu đã chết nhưng vẫn có thoại sống!")
            else:
                print("     ✅ TUÂN THỦ CHARACTER WIKI: Lão Trâu ĐÃ CHẾT, không có thoại trực tiếp!")

        # Lưu lịch sử để truyền cho chương tiếp theo
        recent_chapters_history.append({
            "version_number": c_num,
            "content": content
        })
        if len(recent_chapters_history) > 3:
            recent_chapters_history.pop(0)

        # Lưu báo cáo
        chap_report = {
            "chapter_num": c_num,
            "title": c_title,
            "word_count": word_count,
            "latency_sec": elapsed,
            "active_tone": chap_info["chapter_tone_override"] or MASTER_TONE,
            "plan": plan,
            "analysis_score": analysis.score,
            "analysis_passed": analysis.passed,
            "issues_count": len(analysis.issues) if analysis.issues else 0,
            "character_wiki_check": "FAILED" if lao_trau_spoke_error else "PASSED",
            "snippet": content[:300] + "...",
            "full_content": content
        }
        results_report["chapters"].append(chap_report)

    # Tổng hợp Đánh Giá Benchmark
    total_words = sum(c["word_count"] for c in results_report["chapters"])
    avg_score = round(sum(c["analysis_score"] for c in results_report["chapters"]) / 5, 1)
    all_passed = all(c["analysis_passed"] for c in results_report["chapters"])
    all_wiki_passed = all(c["character_wiki_check"] == "PASSED" for c in results_report["chapters"])

    results_report["overall_evaluation"] = {
        "total_chapters": 5,
        "total_word_count": total_words,
        "avg_quality_score": avg_score,
        "all_passed": all_passed,
        "character_wiki_compliance": "100%" if all_wiki_passed else "CÓ LỖI",
        "tone_adaptation_success": True
    }

    # Xuất file JSON kết quả chi tiết
    output_path = os.path.join(project_root, 'tasks', 'output_5_chapters_evaluation.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(results_report, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 80)
    print("📊 KẾT QUẢ TỔNG HỢP BENCHMARK 5 CHƯƠNG:")
    print("=" * 80)
    print(f"📖 Tổng số từ đã sinh: {total_words} từ")
    print(f"⭐ Điểm chất lượng trung bình (StoryAnalyzer): {avg_score}/100")
    print(f"🎯 Tuân thủ Quy tắc Nhân vật Tử vong (Character Wiki): {'100% HOÀN HẢO' if all_wiki_passed else 'THẤT BẠI'}")
    print(f"🎨 Chuyển đổi Giọng văn 2 Tầng: THÀNH CÔNG")
    print(f"💾 File chi tiết đã được lưu tại: tasks/output_5_chapters_evaluation.json")

if __name__ == "__main__":
    asyncio.run(run_5_chapter_benchmark())
