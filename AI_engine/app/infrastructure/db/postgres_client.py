import json
import logging
from datetime import datetime
from uuid import UUID, uuid4
import asyncpg
from urllib.parse import urlsplit
from app.config import DATABASE_URL

logger = logging.getLogger(__name__)

db_pool = None

async def init_postgres():
    """Initializes PostgreSQL connection pool and runs tables schema migration."""
    global db_pool
    try:
        target = urlsplit(DATABASE_URL)
        logger.info("Connecting to PostgreSQL host=%s port=%s db=%s", target.hostname, target.port, target.path.lstrip("/"))
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

            logger.info("Creating story chat tables...")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS story_chat_threads (
                    id UUID NOT NULL,
                    story_id UUID NOT NULL,
                    title VARCHAR(200) NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (story_id, id)
                );

                CREATE TABLE IF NOT EXISTS story_chat_messages (
                    id BIGSERIAL PRIMARY KEY,
                    story_id UUID NOT NULL,
                    thread_id UUID NOT NULL,
                    position INTEGER NOT NULL,
                    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant')),
                    content TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (story_id, thread_id, position),
                    FOREIGN KEY (story_id, thread_id)
                        REFERENCES story_chat_threads (story_id, id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_story_chat_threads_story
                    ON story_chat_threads (story_id, updated_at DESC);
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
        row = await conn.fetchrow("""
            INSERT INTO generation_jobs (
                id, tenant_id, user_id, story_id, operation, status,
                model_alias, idempotency_key, request_payload, max_attempts, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
            ON CONFLICT (tenant_id, idempotency_key) DO UPDATE
            SET idempotency_key = generation_jobs.idempotency_key
            RETURNING *
        """, UUID(job_id), tenant_id, user_id, UUID(story_id), operation, status,
             model_alias, idempotency_key, json.dumps(request_payload), max_attempts)
        return pg_row_to_dict(row)


async def update_job(job_id: str, status: str, current_step: str | None = None, 
                     progress: int | None = None, attempt: int | None = None, result_payload: dict | None = None,
                     error_payload: dict | None = None, chapter_id: str | None = None,
                     started_at: datetime | None = None, completed_at: datetime | None = None) -> dict | None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            UPDATE generation_jobs SET
                status = $1,
                progress = COALESCE($2, progress),
                attempt = COALESCE($3, attempt),
                current_step = CASE
                    WHEN $1 IN ('COMPLETED', 'FAILED', 'CANCELLED', 'NEEDS_MANUAL_REVIEW') THEN NULL
                    ELSE COALESCE($4, current_step)
                END,
                result_payload = COALESCE($5, result_payload),
                error_payload = COALESCE($6, error_payload),
                chapter_id = COALESCE($7, chapter_id),
                started_at = COALESCE($8, started_at),
                completed_at = COALESCE($9, completed_at)
            WHERE id = $10
              AND status <> 'CANCELLED'
              AND (
                  $1 <> 'CANCELLED'
                  OR status IN ('QUEUED', 'PLANNING', 'RETRIEVING', 'BUILDING_PROMPT', 'GENERATING', 'ANALYZING')
              )
            RETURNING *
        """, status, progress, attempt, current_step,
             json.dumps(result_payload) if result_payload is not None else None,
             json.dumps(error_payload) if error_payload is not None else None,
             UUID(chapter_id) if chapter_id is not None else None,
             started_at, completed_at, UUID(job_id))
        return pg_row_to_dict(row) if row else None


async def get_job(job_id: str) -> dict | None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM generation_jobs WHERE id = $1", UUID(job_id))
        return pg_row_to_dict(row) if row else None


# --- Story Chat Helpers ---

async def save_chat_thread(story_id: str, thread_id: str, title: str, messages: list[dict]) -> dict:
    story_uuid, thread_uuid = UUID(story_id), UUID(thread_id)
    pool = get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            thread = await conn.fetchrow("""
                INSERT INTO story_chat_threads (id, story_id, title)
                VALUES ($1, $2, $3)
                ON CONFLICT (story_id, id) DO UPDATE
                SET title = EXCLUDED.title, updated_at = NOW()
                RETURNING *
            """, thread_uuid, story_uuid, title)
            await conn.execute(
                "DELETE FROM story_chat_messages WHERE story_id = $1 AND thread_id = $2",
                story_uuid, thread_uuid
            )
            if messages:
                await conn.executemany("""
                    INSERT INTO story_chat_messages (story_id, thread_id, position, role, content)
                    VALUES ($1, $2, $3, $4, $5)
                """, [
                    (story_uuid, thread_uuid, position, message["role"], message["content"])
                    for position, message in enumerate(messages)
                ])
            return pg_row_to_dict(thread)


async def append_chat_message(story_id: str, thread_id: str, title: str, role: str, content: str) -> dict:
    story_uuid, thread_uuid = UUID(story_id), UUID(thread_id)
    pool = get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("""
                INSERT INTO story_chat_threads (id, story_id, title)
                VALUES ($1, $2, $3)
                ON CONFLICT (story_id, id) DO UPDATE
                SET title = EXCLUDED.title, updated_at = NOW()
            """, thread_uuid, story_uuid, title)
            row = await conn.fetchrow("""
                INSERT INTO story_chat_messages (story_id, thread_id, position, role, content)
                SELECT $1, $2, COALESCE(MAX(position) + 1, 0), $3, $4
                FROM story_chat_messages
                WHERE story_id = $1 AND thread_id = $2
                RETURNING *
            """, story_uuid, thread_uuid, role, content)
            return pg_row_to_dict(row)


async def get_story_chat_threads(story_id: str) -> list[dict]:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT
                thread.id, thread.title, thread.created_at, thread.updated_at,
                message.role, message.content, message.position
            FROM story_chat_threads AS thread
            LEFT JOIN story_chat_messages AS message
              ON message.story_id = thread.story_id AND message.thread_id = thread.id
            WHERE thread.story_id = $1
            ORDER BY thread.updated_at DESC, thread.created_at DESC, message.position ASC
        """, UUID(story_id))

    threads = {}
    for row in rows:
        thread_id = str(row["id"])
        thread = threads.setdefault(thread_id, {
            "id": thread_id,
            "title": row["title"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "messages": []
        })
        if row["role"] is not None:
            thread["messages"].append({"role": row["role"], "content": row["content"]})
    return list(threads.values())


async def delete_chat_thread(story_id: str, thread_id: str) -> bool:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM story_chat_threads WHERE story_id = $1 AND id = $2",
            UUID(story_id), UUID(thread_id)
        )
        return result != "DELETE 0"


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


async def update_chapter_version(chapter_id: str, version: dict, **changes) -> dict:
    fields = (
        "version_number", "content", "status", "model_alias", "prompt_template_version",
        "generation_metadata", "analysis_result", "user_feedback", "created_by"
    )
    values = version | changes
    return await save_chapter_version(
        chapter_id=chapter_id,
        **{field: values[field] for field in fields}
    )


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


async def get_story_chapter(story_id: str, chapter_id: str) -> dict | None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT cv.* FROM chapter_versions cv
            WHERE cv.chapter_id = $2
              AND EXISTS (
                  SELECT 1 FROM generation_jobs
                  WHERE story_id = $1 AND chapter_id = $2
              )
            ORDER BY cv.version_number DESC
            LIMIT 1
        """, UUID(story_id), UUID(chapter_id))
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


async def resolve_chapter_version(chapter_id: str, version_id_or_num: str) -> dict | None:
    try:
        version = await get_chapter_version_by_id(str(UUID(version_id_or_num)))
        if version and str(version["chapter_id"]) == str(UUID(chapter_id)):
            return version
        return None
    except ValueError:
        pass

    return await get_chapter_version(chapter_id, int(version_id_or_num)) if version_id_or_num.isdigit() else None


async def get_chapter_versions(chapter_id: str) -> list[dict]:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM chapter_versions 
            WHERE chapter_id = $1 
            ORDER BY version_number ASC
        """, UUID(chapter_id))
        return [pg_row_to_dict(r) for r in rows]


async def delete_chapter(story_id: str, chapter_id: str) -> bool:
    pool = get_db_pool()
    story_uuid, chapter_uuid = UUID(story_id), UUID(chapter_id)
    async with pool.acquire() as conn:
        async with conn.transaction():
            exists = await conn.fetchval("""
                SELECT EXISTS(
                    SELECT 1 FROM generation_jobs
                    WHERE story_id = $1 AND chapter_id = $2
                )
            """, story_uuid, chapter_uuid)
            if not exists:
                return False
            await conn.execute(
                "DELETE FROM story_memories WHERE story_id = $1 AND chapter_id = $2",
                story_uuid, chapter_uuid
            )
            await conn.execute("DELETE FROM chapter_versions WHERE chapter_id = $1", chapter_uuid)
            await conn.execute(
                "DELETE FROM generation_jobs WHERE story_id = $1 AND chapter_id = $2",
                story_uuid, chapter_uuid
            )
            return True


async def rename_chapter(story_id: str, chapter_id: str, title: str) -> bool:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("""
            UPDATE generation_jobs
            SET request_payload = jsonb_set(request_payload, '{chapter,title}', to_jsonb($3::text), true)
            WHERE story_id = $1 AND chapter_id = $2
        """, UUID(story_id), UUID(chapter_id), title)
        return result != "UPDATE 0"


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
