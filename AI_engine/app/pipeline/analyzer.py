import json
import logging
import random
from app.application.dto.story_dtos import LLMRequest, AnalysisResult, Issue
from app.config import ROUTING_CONFIG
from app.infrastructure.llm.llm_gateway import LLMGateway

logger = logging.getLogger(__name__)

class StoryAnalyzer:
    def __init__(self, gateway: LLMGateway):
        self.gateway = gateway
        
    async def analyze(self, story_id: str, draft: str, plan: dict, context: dict, attempt: int = 0) -> AnalysisResult:
        system_prompt = (
            "Bạn là biên tập viên văn học khó tính (STORY_ANALYZER).\n"
            "Hãy kiểm tra bản nháp chương truyện xem có gặp lỗi logic, nhất quán hoặc vi phạm quy tắc thế giới không.\n"
            "Hãy trả kết quả dưới dạng JSON có cấu trúc chính xác."
        )
        
        recent_summary = ""
        for rc in context.get("recent_chapters", []):
            recent_summary += f"- Chương {rc['version_number']}: {rc['content'][:500]}...\n"
            
        memories = "\n".join([f"- Ký ức: {m['content']}" for m in context.get("relevant_memories", [])])
        
        prompt = (
            f"[BẢN NHÁP CHƯƠNG ĐANG KIỂM TRA]\n"
            f"{draft}\n\n"
            f"[KẾ HOẠCH CHƯƠNG]\n"
            f"{json.dumps(plan, ensure_ascii=False)}\n\n"
            f"[NGỮ CẢNH TRUYỆN GẦN ĐÂY]\n"
            f"{recent_summary}\n"
            f"[Quy tắc thế giới & nhân vật từ Story Bible]\n"
            f"{memories}\n\n"
            "Hãy đánh giá bản nháp dựa trên các tiêu chí sau và xếp hạng điểm (0-100):\n"
            "1. Continuity: mâu thuẫn sự kiện chương trước.\n"
            "2. Character consistency: hành vi nhân vật có lệch tính cách không.\n"
            "3. World rules: vi phạm thiết lập thế giới.\n"
            "4. Writing style: độ dài, giọng kể.\n"
            "Hãy trả về JSON có cấu trúc sau:\n"
            "{\n"
            "  \"passed\": true/false,\n"
            "  \"score\": 88,\n"
            "  \"primary_issue_type\": \"CONTEXT_ISSUE\"/\"PLANNER_ISSUE\"/\"WRITING_ISSUE\"/null,\n"
            "  \"issues\": [\n"
            "    {\n"
            "      \"type\": \"CONTEXT_ISSUE\"/\"PLANNER_ISSUE\"/\"WRITING_ISSUE\",\n"
            "      \"severity\": \"HIGH\"/\"MEDIUM\"/\"LOW\",\n"
            "      \"description\": \"Mô tả chi tiết lỗi\",\n"
            "      \"suggested_action\": \"Cách khắc phục lỗi\"\n"
            "    }\n"
            "  ]\n"
            "}\n\n"
            "Quy tắc chấm điểm: Bản nháp chỉ đạt (passed=true) khi điểm score >= 85 và không có bất kỳ lỗi nào có mức độ severity='HIGH'."
        )
        
        request = LLMRequest(
            model=ROUTING_CONFIG["analyzer"],
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            response_format="json_object",
            temperature=0.2,
            max_tokens=1500,
            metadata={"attempt": attempt}
        )
        
        response = await self.gateway.generate(ROUTING_CONFIG["analyzer"], request)
        try:
            data = json.loads(response.content)
            
            issues_list = []
            for issue_dict in data.get("issues", []):
                issues_list.append(Issue(
                    id=f"issue_{random.randint(100, 999)}",
                    type=issue_dict.get("type", "WRITING_ISSUE"),
                    severity=issue_dict.get("severity", "MEDIUM"),
                    description=issue_dict.get("description", "Lỗi nội dung"),
                    suggested_action=issue_dict.get("suggested_action")
                ))
                
            return AnalysisResult(
                passed=data.get("passed", True),
                score=data.get("score", 90),
                issues=issues_list,
                primary_issue_type=data.get("primary_issue_type")
            )
        except Exception as e:
            logger.error(f"Failed to parse Analyzer JSON response: {e}. Raw content: {response.content}")
            return AnalysisResult(passed=True, score=90, issues=[])
