import json
import logging
from datetime import datetime
from uuid import UUID, uuid4
import asyncpg
from app.config import DATABASE_URL

logger = logging.getLogger(__name__)

db_pool = None

async def init_postgres():
    """Initializes PostgreSQL connection pool and runs tables schema migration."""
    global db_pool
    try:
        logger.info(f"Connecting to PostgreSQL: {DATABASE_URL[:40]}...")
        db_pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=2,
            max_size=10,
            command_timeout=60.0,
            timeout=10.0
        )
        
        async with db_pool.acquire() as conn:
            # Enable pgvector extension
            logger.info("Enabling pgvector extension in PostgreSQL...")
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            
            # Create generation_jobs table
            logger.info("Creating generation_jobs table...")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS generation_jobs (
                    id UUID PRIMARY KEY,
                    tenant_id VARCHAR(100) NOT NULL,
                    user_id VARCHAR(100) NOT NULL,
                    story_id UUID NOT NULL,
                    chapter_id UUID,
                    operation VARCHAR(50) NOT NULL,
                    status VARCHAR(50) NOT NULL,
                    current_step VARCHAR(50),
                    model_alias VARCHAR(100) NOT NULL,
                    provider VARCHAR(50),
                    progress INTEGER NOT NULL DEFAULT 0,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    idempotency_key VARCHAR(150) NOT NULL,
                    request_payload JSONB NOT NULL,
                    result_payload JSONB,
                    error_payload JSONB,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    started_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ,
                    UNIQUE (tenant_id, idempotency_key)
                );
            """)
            
            # Create chapter_versions table
            logger.info("Creating chapter_versions table...")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS chapter_versions (
                    id UUID PRIMARY KEY,
                    chapter_id UUID NOT NULL,
                    version_number INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    status VARCHAR(50) NOT NULL,
                    model_alias VARCHAR(100),
                    prompt_template_version VARCHAR(100),
                    generation_metadata JSONB,
                    analysis_result JSONB,
                    user_feedback TEXT,
                    created_by VARCHAR(100) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (chapter_id, version_number)
                );
            """)
            
            # Create story_memories table
            logger.info("Creating story_memories table...")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS story_memories (
                    id UUID PRIMARY KEY,
                    story_id UUID NOT NULL,
                    chapter_id UUID,
                    memory_type VARCHAR(50) NOT NULL,
                    content TEXT NOT NULL,
                    metadata JSONB,
                    embedding vector(1536),
                    importance_score NUMERIC(5, 4) DEFAULT 0.5,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """)
            
            logger.info("PostgreSQL database initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize PostgreSQL: {e}")
        raise e


async def close_postgres():
    global db_pool
    if db_pool:
        await db_pool.close()
        logger.info("Database connection pool closed.")


def get_db_pool() -> asyncpg.Pool:
    if not db_pool:
        raise ValueError("PostgreSQL pool is not initialized.")
    return db_pool


def pg_row_to_dict(row) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for key in ("request_payload", "result_payload", "error_payload", "generation_metadata", "analysis_result", "metadata"):
        if key in d and d[key] is not None:
            if isinstance(d[key], str):
                try:
                    d[key] = json.loads(d[key])
                except Exception:
                    pass
    return d


# --- Generation Jobs Helpers ---

async def save_job(job_id: str, tenant_id: str, user_id: str, story_id: str, 
                   operation: str, status: str, model_alias: str, idempotency_key: str, 
                   request_payload: dict, max_attempts: int = 3) -> dict:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        try:
            existing = await conn.fetchrow(
                "SELECT * FROM generation_jobs WHERE tenant_id = $1 AND idempotency_key = $2",
                tenant_id, idempotency_key
            )
            if existing:
                return pg_row_to_dict(existing)
                
            row = await conn.fetchrow("""
                INSERT INTO generation_jobs (
                    id, tenant_id, user_id, story_id, operation, status, 
                    model_alias, idempotency_key, request_payload, max_attempts, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
                RETURNING *
            """, UUID(job_id), tenant_id, user_id, UUID(story_id), operation, status, 
                 model_alias, idempotency_key, json.dumps(request_payload), max_attempts)
            return pg_row_to_dict(row)
        except asyncpg.UniqueViolationError:
            existing = await conn.fetchrow(
                "SELECT * FROM generation_jobs WHERE tenant_id = $1 AND idempotency_key = $2",
                tenant_id, idempotency_key
            )
            return pg_row_to_dict(existing)


async def update_job(job_id: str, status: str, current_step: str | None = None, 
                     progress: int = 0, attempt: int = 0, result_payload: dict | None = None, 
                     error_payload: dict | None = None, chapter_id: str | None = None,
                     started_at: datetime | None = None, completed_at: datetime | None = None) -> dict | None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        updates = []
        params = []
        param_idx = 1
        
        updates.append(f"status = ${param_idx}")
        params.append(status)
        param_idx += 1
        
        updates.append(f"progress = ${param_idx}")
        params.append(progress)
        param_idx += 1
        
        updates.append(f"attempt = ${param_idx}")
        params.append(attempt)
        param_idx += 1
        
        if current_step is not None:
            updates.append(f"current_step = ${param_idx}")
            params.append(current_step)
            param_idx += 1
            
        if result_payload is not None:
            updates.append(f"result_payload = ${param_idx}")
            params.append(json.dumps(result_payload))
            param_idx += 1
            
        if error_payload is not None:
            updates.append(f"error_payload = ${param_idx}")
            params.append(json.dumps(error_payload))
            param_idx += 1
            
        if chapter_id is not None:
            updates.append(f"chapter_id = ${param_idx}")
            params.append(UUID(chapter_id))
            param_idx += 1
            
        if started_at is not None:
            updates.append(f"started_at = ${param_idx}")
            params.append(started_at)
            param_idx += 1
            
        if completed_at is not None:
            updates.append(f"completed_at = ${param_idx}")
            params.append(completed_at)
            param_idx += 1
            
        params.append(UUID(job_id))
        query = f"UPDATE generation_jobs SET {', '.join(updates)} WHERE id = ${param_idx} RETURNING *"
        row = await conn.fetchrow(query, *params)
        return pg_row_to_dict(row) if row else None


async def get_job(job_id: str) -> dict | None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM generation_jobs WHERE id = $1", UUID(job_id))
        return pg_row_to_dict(row) if row else None


# --- Chapter Versions Helpers ---

async def save_chapter_version(chapter_id: str, version_number: int, content: str, 
                               status: str, model_alias: str | None = None, 
                               prompt_template_version: str | None = None, 
                               generation_metadata: dict | None = None, 
                               analysis_result: dict | None = None, 
                               user_feedback: str | None = None, 
                               created_by: str = "system") -> dict:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO chapter_versions (
                id, chapter_id, version_number, content, status, model_alias, 
                prompt_template_version, generation_metadata, analysis_result, 
                user_feedback, created_by, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, NOW())
            ON CONFLICT (chapter_id, version_number) 
            DO UPDATE SET 
                content = EXCLUDED.content,
                status = EXCLUDED.status,
                analysis_result = EXCLUDED.analysis_result,
                user_feedback = EXCLUDED.user_feedback
            RETURNING *
        """, uuid4(), UUID(chapter_id), version_number, content, status, model_alias,
             prompt_template_version, 
             json.dumps(generation_metadata) if generation_metadata else None,
             json.dumps(analysis_result) if analysis_result else None,
             user_feedback, created_by)
        return pg_row_to_dict(row)


async def get_latest_chapter_version(chapter_id: str) -> dict | None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT * FROM chapter_versions 
            WHERE chapter_id = $1 
            ORDER BY version_number DESC 
            LIMIT 1
        """, UUID(chapter_id))
        return pg_row_to_dict(row) if row else None


async def get_chapter_version(chapter_id: str, version_number: int) -> dict | None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT * FROM chapter_versions 
            WHERE chapter_id = $1 AND version_number = $2
        """, UUID(chapter_id), version_number)
        return pg_row_to_dict(row) if row else None


async def get_chapter_version_by_id(version_id: str) -> dict | None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT * FROM chapter_versions 
            WHERE id = $1
        """, UUID(version_id))
        return pg_row_to_dict(row) if row else None


async def get_chapter_versions(chapter_id: str) -> list[dict]:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM chapter_versions 
            WHERE chapter_id = $1 
            ORDER BY version_number ASC
        """, UUID(chapter_id))
        return [pg_row_to_dict(r) for r in rows]


async def get_recent_chapters_content(story_id: str, limit: int = 3) -> list[dict]:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            WITH story_chapters AS (
                SELECT DISTINCT chapter_id FROM generation_jobs 
                WHERE story_id = $1 AND chapter_id IS NOT NULL
            )
            SELECT cv.* FROM chapter_versions cv
            JOIN story_chapters sc ON cv.chapter_id = sc.chapter_id
            WHERE cv.status = 'APPROVED' OR cv.status = 'PUBLISHED'
            ORDER BY cv.created_at DESC
            LIMIT $2
        """, UUID(story_id), limit)
        return [pg_row_to_dict(r) for r in rows]
