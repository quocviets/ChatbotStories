from app.application.commands.story_commands import GenerateChapterCommand
from app.infrastructure.db.postgres_client import get_recent_chapters_content
from app.infrastructure.llm.llm_gateway import LLMGateway
from app.infrastructure.vector_store.pgvector_store import search_memories_vector

CONTEXT_PURPOSES = {
    "must_preserve_facts": "Các sự thật phải giữ đúng; không bắt buộc phải nhắc lại trong văn bản.",
    "continuity_only": "Chỉ dùng để kiểm tra tính liên tục; không tự động kể lại.",
    "recent_prose_reference": "Chỉ tham khảo giọng và điểm nối từ chương gần đây.",
    "character_state": "Trạng thái hiện tại của nhân vật; giữ nhất quán, không đọc lại như hồ sơ.",
    "world_constraints": "Quy tắc thế giới không được vi phạm.",
    "relevant_memories": "Chỉ dùng khi liên quan trực tiếp đến chương đang viết.",
}


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))


def _build_context(
    command, plan: dict, recent_chapters: list[dict], memories: list[dict], token_estimate: int
) -> dict:
    must_preserve = list(command.constraints) if command else []
    continuity_only = list(plan.get("continuity_constraints", []))
    character_state = []
    world_constraints = []
    relevant_memories = []

    for scene in plan.get("required_scenes", []):
        must_preserve.extend(scene.get("mandatory_facts", []))

    for memory in memories:
        content = memory.get("content", "").strip()
        memory_type = memory.get("memory_type", "").upper()
        if not content:
            continue
        if memory_type == "NEW_FACT":
            must_preserve.append(content)
        elif memory_type == "SUMMARY":
            continuity_only.append(content)
        elif memory_type == "CHARACTER_STATE":
            character_state.append(content)
        elif memory_type in {"WORLD_RULE", "WORLD_CONSTRAINT"}:
            world_constraints.append(content)
        else:
            relevant_memories.append(content)

    must_preserve = _unique(must_preserve)
    continuity_only = [item for item in _unique(continuity_only) if item not in must_preserve]

    return {
        "purposes": CONTEXT_PURPOSES,
        "must_preserve_facts": must_preserve,
        "continuity_only": continuity_only,
        "recent_prose_reference": recent_chapters,
        "character_state": _unique(character_state),
        "world_constraints": _unique(world_constraints),
        "relevant_memories": _unique(relevant_memories),
        "token_usage_estimate": token_estimate,
    }


class StoryRetriever:
    def __init__(self, gateway: LLMGateway):
        self.gateway = gateway

    async def retrieve(self, story_id: str, command: GenerateChapterCommand, plan: dict) -> dict:
        # 1. Get N recent chapters (default N=3)
        recent_chapters = await get_recent_chapters_content(story_id, limit=3)

        # 2. Get embeddings of the user request & plan goal
        search_query = f"{command.request} {plan.get('chapter_goal', '')}"
        query_vector = await self.gateway.get_embeddings(search_query)

        # 3. Retrieve matching memories from pgvector
        relevant_memories = await search_memories_vector(story_id, query_vector, limit=5)

        return _build_context(command, plan, recent_chapters, relevant_memories, 4000)

    async def retrieve_more(
        self,
        story_id: str,
        issues: list,
        command: GenerateChapterCommand | None = None,
        plan: dict | None = None,
    ) -> dict:
        """Called when CONTEXT_ISSUE is classified to fetch broader information from pgvector."""
        issue_descriptions = []
        for issue in issues:
            if hasattr(issue, "description") and issue.description:
                issue_descriptions.append(issue.description)
            elif isinstance(issue, dict) and "description" in issue:
                issue_descriptions.append(issue["description"])
        issue_text = " ".join(issue_descriptions)

        query_vector = await self.gateway.get_embeddings(issue_text)
        new_memories = await search_memories_vector(story_id, query_vector, limit=7)

        recent_chapters = await get_recent_chapters_content(story_id, limit=3)
        return _build_context(command, plan or {}, recent_chapters, new_memories, 6000)
