from app.application.commands.story_commands import GenerateChapterCommand
from app.infrastructure.db.postgres_client import get_recent_chapters_content
from app.infrastructure.vector_store.pgvector_store import search_memories_vector
from app.infrastructure.llm.llm_gateway import LLMGateway

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
        
        return {
            "story_summary": "Tóm tắt truyện dài tập (Trích xuất từ Vector Store)",
            "recent_chapters": recent_chapters,
            "relevant_memories": relevant_memories,
            "token_usage_estimate": 4000
        }

    async def retrieve_more(self, story_id: str, issues: list) -> dict:
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
        
        return {
            "story_summary": "Tóm tắt mở rộng",
            "recent_chapters": await get_recent_chapters_content(story_id, limit=3),
            "relevant_memories": new_memories,
            "token_usage_estimate": 6000
        }
