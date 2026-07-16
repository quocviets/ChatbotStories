import json
import logging
from uuid import uuid4, UUID
from app.infrastructure.db.postgres_client import get_db_pool

logger = logging.getLogger(__name__)

async def save_memory_vector(story_id: str, chapter_id: str | None, memory_type: str, 
                               content: str, metadata: dict | None = None, 
                               embedding: list[float] | None = None, 
                               importance_score: float = 0.5) -> dict:
    """Saves a story memory with its 1536-dimensional vector embedding to PostgreSQL."""
    pool = get_db_pool()
    embedding_str = f"[{','.join(map(str, embedding))}]" if embedding else None
    
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO story_memories (
                id, story_id, chapter_id, memory_type, content, metadata, 
                embedding, importance_score, created_at, updated_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7::vector, $8, NOW(), NOW())
            RETURNING id, story_id, chapter_id, memory_type, content, metadata, importance_score, created_at, updated_at
        """, uuid4(), UUID(story_id), UUID(chapter_id) if chapter_id else None,
             memory_type, content, json.dumps(metadata) if metadata else None,
             embedding_str, importance_score)
        return dict(row)

async def search_memories_vector(story_id: str, query_embedding: list[float], limit: int = 5) -> list[dict]:
    """Queries similar memories using pgvector's cosine distance operator (<=>)."""
    pool = get_db_pool()
    
    if not query_embedding:
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, story_id, chapter_id, memory_type, content, metadata, importance_score, created_at 
                FROM story_memories 
                WHERE story_id = $1 
                ORDER BY created_at DESC 
                LIMIT $2
            """, UUID(story_id), limit)
            return [dict(r) for r in rows]
            
    async with pool.acquire() as conn:
        embedding_str = f"[{','.join(map(str, query_embedding))}]"
        rows = await conn.fetch("""
            SELECT id, story_id, chapter_id, memory_type, content, metadata, importance_score, created_at,
                   (1 - (embedding <=> $2::vector)) AS similarity 
            FROM story_memories 
            WHERE story_id = $1 AND embedding IS NOT NULL
            ORDER BY embedding <=> $2::vector ASC 
            LIMIT $3
        """, UUID(story_id), embedding_str, limit)
        return [dict(r) for r in rows]
