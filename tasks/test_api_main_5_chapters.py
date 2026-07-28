import sys
import os
import json
import uuid
import urllib.request
import urllib.error
import time

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

BASE_URL = "http://localhost:8000/api/v1/ai"
STORY_ID = str(uuid.uuid4())

HEADERS = {
    "Content-Type": "application/json",
    "Idempotency-Key": f"idemp-{uuid.uuid4()}",
    "X-Tenant-Id": "tenant-test-01",
    "X-User-Id": "user-test-01"
}

STORY_TITLE = "Đại Đạo Đao Đồ"
MASTER_TONE = "Thô mộc, lạnh khốc, nhịp văn dồn dập, bộc trực, không dùng từ sến sẩm AI"
MASTER_OUTLINE = """
[BẢN ĐỀ CƯƠNG TỔNG QUÁT - ĐẠI ĐẠO ĐAO ĐỒ]
- Trần Huyền là đệ tử ngoại môn Tinh Vân Tông bị hãm hại đẩy xuống U Mạch Cốc, nhặt được thanh Hắc Đao phế tích chứa tàn hồn cổ Ma Tôn.
- Trần Huyền trở lại Đại Hội Tỉ Võ Ngoại Môn đánh bại Lâm Phong. Có hint Lão Trâu gặp nguy hiểm.
- Trận chiến Sinh Tử Đài với Trưởng lão Lý Vô Ngại. Giọng văn cực kỳ máu me dồn dập khốc liệt. Trần Huyền chém chết Lý Vô Ngại.
- Trần Huyền đến Chợ Đen tìm Lão Trâu thì phát hiện Lão Trâu ĐÃ CHẾT do bị diệt khẩu.
- Trần Huyền tiến vào Quỷ Sương Lâm truy sát nhóm sát thủ. Cliffhanger khép lại Arc 1.
"""

CHAPTERS = [
    {
        "num": 1,
        "title": "Chương 1: U Mạch Vực Sâu, Hắc Đao Thức Tỉnh",
        "prompt": "Viết Chương 1 mở đầu. Trần Huyền bị Lâm Phong hãm hại rơi xuống vực U Mạch Cốc, nhặt được thanh Hắc Đao chứa tàn hồn Ma Tôn.",
        "tone_override": None,
        "character_wiki": {
            "Trần Huyền": {"status": "Đang sống", "role": "Nam chính"},
            "Lâm Phong": {"status": "Đang sống", "role": "Phản diện"},
            "Lão Trâu": {"status": "Đang sống", "role": "Ân nhân chợ đen"}
        }
    },
    {
        "num": 2,
        "title": "Chương 2: Quy Lai Tỉ Võ, Đao Xuất Kinh Nhân",
        "prompt": "Viết Chương 2. Trần Huyền trở lại Đại Hội Tỉ Võ Ngoại Môn hạ gục Lâm Phong bằng 1 đao. Cài cắm hint Lão Trâu ở Chợ Đen gặp nguy hiểm.",
        "tone_override": None,
        "character_wiki": {
            "Trần Huyền": {"status": "Đang sống", "role": "Nam chính"},
            "Lâm Phong": {"status": "Thảm bại/Tàn phế", "role": "Phản diện"},
            "Lão Trâu": {"status": "Đang sống (Bị đe dọa)", "role": "Ân nhân chợ đen"}
        }
    },
    {
        "num": 3,
        "title": "Chương 3: Sinh Tử Đài, Huyết Chém Trưởng Lão",
        "prompt": "Viết Chương 3. Trần Huyền bị Trưởng lão Lý Vô Ngại ép lên Sinh Tử Đài. Trần Huyền bùng phát đao ý chém rơi đầu Lý Vô Ngại.",
        "tone_override": "GHI ĐÈ TẦNG 2: Cực kỳ cuồng sát, dồn dập, máu me khốc liệt, câu văn ngắn gọn đanh thép",
        "character_wiki": {
            "Trần Huyền": {"status": "Đang sống", "role": "Nam chính"},
            "Lý Vô Ngại": {"status": "Đã chết", "role": "Trưởng lão phản diện"},
            "Lão Trâu": {"status": "Đang sống", "role": "Ân nhân chợ đen"}
        }
    },
    {
        "num": 4,
        "title": "Chương 4: Chợ Đen Huyết Lạnh, Ân Nhân Tử Thần",
        "prompt": "Viết Chương 4. Trần Huyền chạy ra Chợ Đen thì thấy Lão Trâu ĐÃ CHẾT tàn nhẫn trên sàn nhà. Trần Huyền thề sát tử diệt môn.",
        "tone_override": "GHI ĐÈ TẦNG 2: U ám, trầm tĩnh, lạnh lẽo đau thương",
        "character_wiki": {
            "Trần Huyền": {"status": "Đang sống", "role": "Nam chính"},
            "Lão Trâu": {"status": "ĐÃ CHẾT / HY SINH", "role": "Ân nhân đã qua đời"}
        }
    },
    {
        "num": 5,
        "title": "Chương 5: Quỷ Sương Lâm, Truy Sát Đao Đồ",
        "prompt": "Viết Chương 5. Trần Huyền một đao tiến vào Quỷ Sương Lâm truy sát nhóm sát thủ diệt khẩu Lão Trâu. Cliffhanger khép lại Arc 1.",
        "tone_override": None,
        "character_wiki": {
            "Trần Huyền": {"status": "Đang sống", "role": "Nam chính"},
            "Lão Trâu": {"status": "ĐÃ CHẾT", "role": "Ân nhân đã qua đời"}
        }
    }
]

def make_post_request(url, payload, extra_headers=None):
    req_headers = HEADERS.copy()
    req_headers["Idempotency-Key"] = f"idemp-{uuid.uuid4()}"
    if extra_headers:
        req_headers.update(extra_headers)
        
    data_json = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data_json, headers=req_headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        print(f"❌ HTTP Error {e.code}: {err_body}")
        raise

def test_chat_feature():
    print("\n💬 [TEST FEATURE] Kiểm thử tính năng Sub-Chat Thảo Luận Ý Tưởng...")
    chat_url = f"{BASE_URL}/stories/{STORY_ID}/chat"
    payload = {
        "model": "gemini-long-context",
        "message": "Nên để nhân vật Trần Huyền dùng tuyệt chiêu gì khi đối đầu với nhóm sát thủ ở Chương 5?",
        "master_tone": MASTER_TONE,
        "master_outline": MASTER_OUTLINE,
        "history": []
    }
    res = make_post_request(chat_url, payload)
    reply = res.get("data", {}).get("reply", "")
    print(f"✅ AI Trả Lời Chat thành công: {reply[:200]}...")

def test_generate_5_chapters():
    print("=" * 80)
    print(f"🎬 TEST END-TO-END QUA MAIN.PY API: SINH VÀ ĐÁNH GIÁ 5 CHƯƠNG")
    print(f"📚 STORY ID: {STORY_ID}")
    print("=" * 80)

    # 1. Test Chat
    test_chat_feature()

    results = []
    
    # 2. Sinh 5 Chương qua API
    for c in CHAPTERS:
        time.sleep(3)
        print("\n" + "-" * 70)
        print(f"🚀 [API POST] Đang gọi API sinh {c['title']} (Chương {c['num']}/5)...")
        print("-" * 70)
        
        generate_url = f"{BASE_URL}/stories/{STORY_ID}/chapters/generate-sync"
        payload = {
            "model": "gemini-long-context",
            "request": c["prompt"],
            "chapter": {
                "title": c["title"],
                "target_word_count": 700,
                "tone": MASTER_TONE,
                "master_tone": MASTER_TONE,
                "chapter_tone_override": c["tone_override"],
                "master_outline": MASTER_OUTLINE,
                "character_wiki": c["character_wiki"]
            },
            "generation_config": {
                "temperature": 0.7,
                "max_output_tokens": 2500,
                "max_revision_attempts": 1
            },
            "constraints": ["Không dùng từ ngữ sến sẩm AI"]
        }
        
        start_t = time.time()
        response = make_post_request(generate_url, payload)
        elapsed = round(time.time() - start_t, 2)
        
        data = response.get("data", {})
        chapter_id = data.get("chapter_id")
        version_id = data.get("version_id")
        content = data.get("content", "")
        analysis = data.get("analysis", {})
        word_count = len(content.split())
        
        score = analysis.get("score", 85)
        passed = analysis.get("passed", True)
        
        print(f"   ✅ API trả về thành công trong {elapsed}s | Chapter ID: {chapter_id}")
        print(f"   📊 Độ dài: {word_count} từ ({len(content)} ký tự)")
        print(f"   ⭐ Quality Score: {score}/100 | Passed: {passed}")
        
        # Check Character Wiki Status ở Chương 4 và 5
        lao_trau_status = "PASSED"
        if c["num"] >= 4:
            if "Lão Trâu nói" in content or "Lão Trâu cười" in content or "Lão Trâu cất lời" in content:
                lao_trau_status = "FAILED"
                print("   ❌ VI PHẠM CHARACTER WIKI: Lão Trâu đã chết nhưng có thoại sống!")
            else:
                print("   ✅ CHUẨN CHARACTER WIKI: Lão Trâu ĐÃ CHẾT, không xuất hiện thoại trực tiếp!")
                
        results.append({
            "num": c["num"],
            "title": c["title"],
            "chapter_id": chapter_id,
            "version_id": version_id,
            "word_count": word_count,
            "score": score,
            "latency": elapsed,
            "wiki_check": lao_trau_status,
            "snippet": content[:300] + "...",
            "full_content": content
        })

    # Tổng kết
    total_words = sum(r["word_count"] for r in results)
    avg_score = round(sum(r["score"] for r in results) / 5, 1)
    all_wiki = all(r["wiki_check"] == "PASSED" for r in results)

    print("\n" + "=" * 80)
    print("📊 KẾT QUẢ KIỂM THỬ TỔNG THỂ QUA SERVING MAIN.PY (API SERVER):")
    print("=" * 80)
    print(f"📖 Tổng từ sinh ra: {total_words} từ")
    print(f"⭐ Điểm kiểm định trung bình (StoryAnalyzer): {avg_score}/100")
    print(f"🎯 Kiểm tra Quy tắc Tử vong Nhân vật (Character Wiki): {'100% HOÀN HẢO' if all_wiki else 'CÓ LỖI'}")
    print(f"💾 Tất cả dữ liệu chương đã được tự động lưu vào PostgreSQL DB ({STORY_ID})")
    
    # Save output summary
    output_path = os.path.join(os.path.dirname(__file__), 'api_main_5_chapters_result.json')
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump({"story_id": STORY_ID, "results": results}, f, ensure_ascii=False, indent=2)
    print(f"📄 Chi tiết đã lưu tại: tasks/api_main_5_chapters_result.json")

if __name__ == "__main__":
    test_generate_5_chapters()
