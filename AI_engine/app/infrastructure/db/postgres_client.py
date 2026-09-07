import json
import logging
import re
from contextlib import suppress
from datetime import datetime
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import asyncpg
from app.config import DATABASE_URL

logger = logging.getLogger(__name__)

db_pool = None


async def init_postgres():
    """Initializes PostgreSQL connection pool and runs tables schema migration."""
    global db_pool
    try:
        target = urlsplit(DATABASE_URL)
        logger.info(
            "Connecting to PostgreSQL host=%s port=%s db=%s",
            target.hostname,
            target.port,
            target.path.lstrip("/"),
        )
        db_pool = await asyncpg.create_pool(
            DATABASE_URL, min_size=2, max_size=10, command_timeout=60.0, timeout=10.0
        )

        async with db_pool.acquire() as conn:
            # Enable pgvector extension
            logger.info("Enabling pgvector extension in PostgreSQL...")
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")

            # Authentication Tables (users, auth_identities, sessions, password_reset_tokens)
            logger.info("Initializing authentication tables...")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    email VARCHAR(255) NOT NULL,
                    display_name VARCHAR(100) NOT NULL,
                    avatar_url TEXT,
                    tier VARCHAR(50) NOT NULL DEFAULT 'author',
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_users_email UNIQUE (email)
                );

                CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);

                CREATE TABLE IF NOT EXISTS auth_identities (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
                    provider VARCHAR(20) NOT NULL,
                    provider_user_id VARCHAR(255) NOT NULL,
                    password_hash TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    CONSTRAINT uq_auth_identities_provider UNIQUE (provider, provider_user_id),
                    CONSTRAINT uq_auth_identities_user_provider UNIQUE (user_id, provider)
                );

                CREATE INDEX IF NOT EXISTS idx_auth_identities_lookup
                    ON auth_identities (provider, provider_user_id);

                CREATE TABLE IF NOT EXISTS sessions (
                    id VARCHAR(64) PRIMARY KEY,
                    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
                    ip_address VARCHAR(45),
                    user_agent TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at TIMESTAMPTZ NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_sessions_lookup
                    ON sessions (id, expires_at);

                CREATE TABLE IF NOT EXISTS password_reset_tokens (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
                    token_hash VARCHAR(64) NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL,
                    used_at TIMESTAMPTZ,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_reset_token_lookup
                    ON password_reset_tokens (token_hash, expires_at)
                    WHERE used_at IS NULL;
            """)

            # Canonical story metadata. Content tables keep their existing schema;
            # this registry replaces browser storage as the source of truth.
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS stories (
                    id UUID PRIMARY KEY,
                    tenant_id VARCHAR(100) NOT NULL,
                    user_id VARCHAR(100) NOT NULL,
                    title VARCHAR(200) NOT NULL,
                    master_tone TEXT NOT NULL DEFAULT '',
                    master_outline TEXT NOT NULL DEFAULT '',
                    metadata_initialized BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    archived_at TIMESTAMPTZ
                );

                CREATE INDEX IF NOT EXISTS idx_stories_owner
                    ON stories (tenant_id, user_id, archived_at, created_at DESC);
            """)

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

            # Canonical chapter registry. Browser storage is only a disposable UI cache;
            # chapter ownership, order and deletion state live here.
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS story_chapters (
                    id UUID PRIMARY KEY,
                    story_id UUID NOT NULL,
                    chapter_number INTEGER NOT NULL,
                    title VARCHAR(200) NOT NULL,
                    status VARCHAR(50) NOT NULL DEFAULT 'ACTIVE',
                    source_thread_id UUID,
                    source_message_index INTEGER,
                    model_alias VARCHAR(100),
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    deleted_at TIMESTAMPTZ,
                    UNIQUE (story_id, chapter_number)
                );

                CREATE INDEX IF NOT EXISTS idx_story_chapters_story_active
                    ON story_chapters (story_id, chapter_number DESC)
                    WHERE deleted_at IS NULL;
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

            # Preserve existing installations. Legacy chapters were identified only by
            # generation_jobs; register them once without reusing allocated numbers.
            await conn.execute("""
                WITH missing AS (
                    SELECT
                        jobs.chapter_id,
                        jobs.story_id,
                        MIN(jobs.created_at) AS created_at,
                        (ARRAY_AGG(
                            NULLIF(jobs.request_payload->'chapter'->>'title', '')
                            ORDER BY jobs.created_at DESC
                        ))[1] AS requested_title,
                        (ARRAY_AGG(jobs.model_alias ORDER BY jobs.created_at DESC))[1] AS model_alias
                    FROM generation_jobs AS jobs
                    LEFT JOIN story_chapters AS chapter ON chapter.id = jobs.chapter_id
                    WHERE jobs.chapter_id IS NOT NULL
                      AND chapter.id IS NULL
                      AND EXISTS (
                          SELECT 1 FROM chapter_versions AS version
                          WHERE version.chapter_id = jobs.chapter_id
                      )
                    GROUP BY jobs.chapter_id, jobs.story_id
                ),
                numbered AS (
                    SELECT
                        missing.*,
                        ROW_NUMBER() OVER (
                            PARTITION BY missing.story_id
                            ORDER BY missing.created_at, missing.chapter_id
                        ) AS offset_number
                    FROM missing
                )
                INSERT INTO story_chapters (
                    id, story_id, chapter_number, title, status, model_alias, created_at
                )
                SELECT
                    numbered.chapter_id,
                    numbered.story_id,
                    COALESCE((
                        SELECT MAX(existing.chapter_number)
                        FROM story_chapters AS existing
                        WHERE existing.story_id = numbered.story_id
                    ), 0) + numbered.offset_number,
                    COALESCE(
                        numbered.requested_title,
                        'Chương ' || (
                            COALESCE((
                                SELECT MAX(existing.chapter_number)
                                FROM story_chapters AS existing
                                WHERE existing.story_id = numbered.story_id
                            ), 0) + numbered.offset_number
                        )
                    ),
                    'ACTIVE',
                    numbered.model_alias,
                    numbered.created_at
                FROM numbered
                ON CONFLICT (id) DO NOTHING;
            """)

            # Existing installations may already contain chapters, chats or
            # memories without a story metadata row. Register those IDs with
            # placeholder metadata which may be initialized once from the old
            # browser workspace.
            await conn.execute("""
                WITH known_story_ids AS (
                    SELECT story_id FROM generation_jobs
                    UNION
                    SELECT story_id FROM story_chapters
                    UNION
                    SELECT story_id FROM story_chat_threads
                    UNION
                    SELECT story_id FROM story_memories
                ),
                latest_owner AS (
                    SELECT DISTINCT ON (story_id)
                        story_id,
                        tenant_id,
                        user_id
                    FROM generation_jobs
                    ORDER BY story_id, created_at DESC
                )
                INSERT INTO stories (
                    id,
                    tenant_id,
                    user_id,
                    title,
                    metadata_initialized
                )
                SELECT
                    known_story_ids.story_id,
                    COALESCE(latest_owner.tenant_id, 'tenant_web_01'),
                    COALESCE(latest_owner.user_id, 'user_web_01'),
                    'Truyện đã nhập',
                    FALSE
                FROM known_story_ids
                LEFT JOIN latest_owner USING (story_id)
                ON CONFLICT (id) DO NOTHING;
            """)

            logger.info("PostgreSQL database initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize PostgreSQL: {e}")
        raise


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
    for key in (
        "request_payload",
        "result_payload",
        "error_payload",
        "generation_metadata",
        "analysis_result",
        "metadata",
    ):
        if isinstance(d.get(key), str):
            with suppress(Exception):
                d[key] = json.loads(d[key])
    return d


async def list_stories(tenant_id: str, user_id: str) -> list[dict]:
    pool = get_db_pool()
    rows = await pool.fetch(
        """
        SELECT
            story.id,
            story.title,
            story.master_tone,
            story.master_outline,
            story.created_at,
            story.updated_at,
            story.archived_at,
            COUNT(DISTINCT chapter.id) FILTER (WHERE chapter.deleted_at IS NULL) AS chapter_count,
            COUNT(DISTINCT thread.id) AS chat_count
        FROM stories AS story
        LEFT JOIN story_chapters AS chapter ON chapter.story_id = story.id
        LEFT JOIN story_chat_threads AS thread ON thread.story_id = story.id
        WHERE story.tenant_id = $1
          AND story.user_id = $2
          AND story.metadata_initialized = TRUE
        GROUP BY story.id
        ORDER BY
            (story.archived_at IS NOT NULL),
            story.updated_at DESC,
            story.created_at DESC
        """,
        tenant_id,
        user_id,
    )
    return [pg_row_to_dict(row) for row in rows]


async def create_story(
    tenant_id: str,
    user_id: str,
    title: str,
    master_tone: str = "",
    master_outline: str = "",
) -> dict:
    pool = get_db_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO stories (
            id,
            tenant_id,
            user_id,
            title,
            master_tone,
            master_outline,
            metadata_initialized
        )
        VALUES ($1, $2, $3, $4, $5, $6, TRUE)
        RETURNING *
        """,
        uuid4(),
        tenant_id,
        user_id,
        title,
        master_tone,
        master_outline,
    )
    return pg_row_to_dict(row)


async def import_legacy_stories(
    tenant_id: str,
    user_id: str,
    stories: list[dict],
) -> int:
    """Initializes metadata once; later browser data can never overwrite it."""
    if not stories:
        return 0
    pool = get_db_pool()
    imported = 0
    async with pool.acquire() as conn, conn.transaction():
        for story in stories:
            row = await conn.fetchrow(
                """
                    INSERT INTO stories (
                        id,
                        tenant_id,
                        user_id,
                        title,
                        master_tone,
                        master_outline,
                        metadata_initialized,
                        created_at,
                        updated_at,
                        archived_at
                    )
                    VALUES (
                        $1, $2, $3, $4, $5, $6, TRUE,
                        COALESCE($7, NOW()), NOW(), $8
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        title = EXCLUDED.title,
                        master_tone = EXCLUDED.master_tone,
                        master_outline = EXCLUDED.master_outline,
                        archived_at = EXCLUDED.archived_at,
                        metadata_initialized = TRUE,
                        updated_at = NOW()
                    WHERE stories.tenant_id = EXCLUDED.tenant_id
                      AND stories.user_id = EXCLUDED.user_id
                      AND stories.metadata_initialized = FALSE
                    RETURNING id
                    """,
                story["id"],
                tenant_id,
                user_id,
                story["title"],
                story.get("master_tone") or "",
                story.get("master_outline") or "",
                story.get("created_at"),
                story.get("archived_at"),
            )
            imported += int(row is not None)
    return imported


async def update_story(
    story_id: str,
    tenant_id: str,
    user_id: str,
    *,
    title: str | None = None,
    master_tone: str | None = None,
    master_outline: str | None = None,
    archived: bool | None = None,
) -> dict | None:
    pool = get_db_pool()
    row = await pool.fetchrow(
        """
        UPDATE stories
        SET
            title = COALESCE($4, title),
            master_tone = COALESCE($5, master_tone),
            master_outline = COALESCE($6, master_outline),
            archived_at = CASE
                WHEN $7::BOOLEAN IS NULL THEN archived_at
                WHEN $7 THEN COALESCE(archived_at, NOW())
                ELSE NULL
            END,
            metadata_initialized = TRUE,
            updated_at = NOW()
        WHERE id = $1
          AND tenant_id = $2
          AND user_id = $3
        RETURNING *
        """,
        UUID(story_id),
        tenant_id,
        user_id,
        title,
        master_tone,
        master_outline,
        archived,
    )
    return pg_row_to_dict(row)


def _default_chapter_title(title: str | None, chapter_number: int) -> str:
    candidate = (title or "").strip()
    if not candidate or re.fullmatch(r"chương\s+\d+", candidate, re.IGNORECASE):
        return f"Chương {chapter_number}"
    return candidate[:200]


def _optional_uuid(value: str | UUID | None) -> UUID | None:
    if value is None:
        return None
    try:
        return value if isinstance(value, UUID) else UUID(str(value))
    except (TypeError, ValueError):
        return None


# --- Generation Jobs Helpers ---


async def save_job(
    job_id: str,
    tenant_id: str,
    user_id: str,
    story_id: str,
    operation: str,
    status: str,
    model_alias: str,
    idempotency_key: str,
    request_payload: dict,
    max_attempts: int = 3,
) -> dict:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO generation_jobs (
                id, tenant_id, user_id, story_id, operation, status,
                model_alias, idempotency_key, request_payload, max_attempts, created_at
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
            ON CONFLICT (tenant_id, idempotency_key) DO UPDATE
            SET idempotency_key = generation_jobs.idempotency_key
            RETURNING *
        """,
            UUID(job_id),
            tenant_id,
            user_id,
            UUID(story_id),
            operation,
            status,
            model_alias,
            idempotency_key,
            json.dumps(request_payload),
            max_attempts,
        )
        return pg_row_to_dict(row)


async def update_job(
    job_id: str,
    status: str,
    current_step: str | None = None,
    progress: int | None = None,
    attempt: int | None = None,
    result_payload: dict | None = None,
    error_payload: dict | None = None,
    chapter_id: str | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> dict | None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
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
        """,
            status,
            progress,
            attempt,
            current_step,
            json.dumps(result_payload) if result_payload is not None else None,
            json.dumps(error_payload) if error_payload is not None else None,
            UUID(chapter_id) if chapter_id is not None else None,
            started_at,
            completed_at,
            UUID(job_id),
        )
        return pg_row_to_dict(row) if row else None


async def get_job(job_id: str) -> dict | None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM generation_jobs WHERE id = $1", UUID(job_id))
        return pg_row_to_dict(row) if row else None


# --- Story Chapter Helpers ---


async def create_story_chapter(
    story_id: str,
    chapter_id: str,
    title: str | None = None,
    source_thread_id: str | None = None,
    source_message_index: int | None = None,
    model_alias: str | None = None,
) -> dict:
    """Registers a chapter and allocates its immutable number on the server."""
    pool = get_db_pool()
    story_uuid, chapter_uuid = UUID(story_id), UUID(chapter_id)
    async with pool.acquire() as conn, conn.transaction():
        existing = await conn.fetchrow(
            "SELECT * FROM story_chapters WHERE id = $1 FOR UPDATE",
            chapter_uuid,
        )
        if existing:
            return pg_row_to_dict(existing)

        # Serialize number allocation per story without requiring a separate
        # sequence table.
        await conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            str(story_uuid),
        )
        chapter_number = await conn.fetchval(
            """
                SELECT COALESCE(MAX(chapter_number), 0) + 1
                FROM story_chapters
                WHERE story_id = $1
                """,
            story_uuid,
        )
        resolved_title = _default_chapter_title(title, chapter_number)
        row = await conn.fetchrow(
            """
                INSERT INTO story_chapters (
                    id, story_id, chapter_number, title, status,
                    source_thread_id, source_message_index, model_alias
                )
                VALUES ($1, $2, $3, $4, 'ACTIVE', $5, $6, $7)
                RETURNING *
                """,
            chapter_uuid,
            story_uuid,
            chapter_number,
            resolved_title,
            _optional_uuid(source_thread_id),
            source_message_index,
            model_alias,
        )
        return pg_row_to_dict(row)


async def attach_job_chapter(job_id: str, chapter_id: str) -> bool:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE generation_jobs
            SET chapter_id = $2
            WHERE id = $1
              AND status NOT IN ('COMPLETED', 'FAILED', 'CANCELLED')
            """,
            UUID(job_id),
            UUID(chapter_id),
        )
        return result != "UPDATE 0"


async def list_story_chapters(story_id: str) -> list[dict]:
    """Returns the canonical active chapter list with one latest version each."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                chapter.id AS chapter_id,
                chapter.chapter_number,
                chapter.title,
                chapter.status AS chapter_status,
                chapter.source_thread_id,
                chapter.source_message_index,
                chapter.model_alias AS chapter_model_alias,
                version.id AS version_id,
                version.content,
                version.status,
                version.model_alias,
                version.generation_metadata,
                version.created_at
            FROM story_chapters AS chapter
            JOIN LATERAL (
                SELECT candidate.*
                FROM chapter_versions AS candidate
                WHERE candidate.chapter_id = chapter.id
                ORDER BY candidate.version_number DESC, candidate.created_at DESC
                LIMIT 1
            ) AS version ON TRUE
            WHERE chapter.story_id = $1
              AND chapter.deleted_at IS NULL
            ORDER BY chapter.chapter_number DESC
            """,
            UUID(story_id),
        )
        return [pg_row_to_dict(row) for row in rows]


async def list_deleted_chapter_sources(story_id: str) -> list[dict]:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id AS chapter_id, source_thread_id, source_message_index
            FROM story_chapters
            WHERE story_id = $1
              AND deleted_at IS NOT NULL
              AND source_thread_id IS NOT NULL
              AND source_message_index IS NOT NULL
            """,
            UUID(story_id),
        )
        return [pg_row_to_dict(row) for row in rows]


async def get_active_story_chapter(story_id: str, chapter_id: str) -> dict | None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT *
            FROM story_chapters
            WHERE story_id = $1 AND id = $2 AND deleted_at IS NULL
            """,
            UUID(story_id),
            UUID(chapter_id),
        )
        return pg_row_to_dict(row) if row else None


# --- Story Chat Helpers ---


async def save_chat_thread(story_id: str, thread_id: str, title: str, messages: list[dict]) -> dict:
    story_uuid, thread_uuid = UUID(story_id), UUID(thread_id)
    pool = get_db_pool()
    async with pool.acquire() as conn, conn.transaction():
        thread = await conn.fetchrow(
            """
                INSERT INTO story_chat_threads (id, story_id, title)
                VALUES ($1, $2, $3)
                ON CONFLICT (story_id, id) DO UPDATE
                SET title = EXCLUDED.title, updated_at = NOW()
                RETURNING *
            """,
            thread_uuid,
            story_uuid,
            title,
        )
        await conn.execute(
            "DELETE FROM story_chat_messages WHERE story_id = $1 AND thread_id = $2",
            story_uuid,
            thread_uuid,
        )
        if messages:
            await conn.executemany(
                """
                    INSERT INTO story_chat_messages (story_id, thread_id, position, role, content)
                    VALUES ($1, $2, $3, $4, $5)
                """,
                [
                    (story_uuid, thread_uuid, position, message["role"], message["content"])
                    for position, message in enumerate(messages)
                ],
            )
        return pg_row_to_dict(thread)


async def append_chat_message(
    story_id: str, thread_id: str, title: str, role: str, content: str
) -> dict:
    story_uuid, thread_uuid = UUID(story_id), UUID(thread_id)
    pool = get_db_pool()
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """
                INSERT INTO story_chat_threads (id, story_id, title)
                VALUES ($1, $2, $3)
                ON CONFLICT (story_id, id) DO UPDATE
                SET title = EXCLUDED.title, updated_at = NOW()
            """,
            thread_uuid,
            story_uuid,
            title,
        )
        row = await conn.fetchrow(
            """
                INSERT INTO story_chat_messages (story_id, thread_id, position, role, content)
                SELECT $1, $2, COALESCE(MAX(position) + 1, 0), $3, $4
                FROM story_chat_messages
                WHERE story_id = $1 AND thread_id = $2
                RETURNING *
            """,
            story_uuid,
            thread_uuid,
            role,
            content,
        )
        return pg_row_to_dict(row)


async def get_story_chat_threads(story_id: str) -> list[dict]:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                thread.id, thread.title, thread.created_at, thread.updated_at,
                message.role, message.content, message.position
            FROM story_chat_threads AS thread
            LEFT JOIN story_chat_messages AS message
              ON message.story_id = thread.story_id AND message.thread_id = thread.id
            WHERE thread.story_id = $1
            ORDER BY thread.updated_at DESC, thread.created_at DESC, message.position ASC
        """,
            UUID(story_id),
        )

    threads = {}
    for row in rows:
        thread_id = str(row["id"])
        thread = threads.setdefault(
            thread_id,
            {
                "id": thread_id,
                "title": row["title"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "messages": [],
            },
        )
        if row["role"] is not None:
            thread["messages"].append({"role": row["role"], "content": row["content"]})
    return list(threads.values())


async def delete_chat_thread(story_id: str, thread_id: str) -> bool:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM story_chat_threads WHERE story_id = $1 AND id = $2",
            UUID(story_id),
            UUID(thread_id),
        )
        return result != "DELETE 0"


# --- Chapter Versions Helpers ---


async def save_chapter_version(
    chapter_id: str,
    version_number: int,
    content: str,
    status: str,
    model_alias: str | None = None,
    prompt_template_version: str | None = None,
    generation_metadata: dict | None = None,
    analysis_result: dict | None = None,
    user_feedback: str | None = None,
    created_by: str = "system",
    story_id: str | None = None,
) -> dict | None:
    pool = get_db_pool()
    async with pool.acquire() as conn, conn.transaction():
        if story_id is not None:
            active = await conn.fetchrow(
                """
                    SELECT id
                    FROM story_chapters
                    WHERE story_id = $1 AND id = $2 AND deleted_at IS NULL
                    FOR UPDATE
                    """,
                UUID(story_id),
                UUID(chapter_id),
            )
            if not active:
                return None

        row = await conn.fetchrow(
            """
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
            """,
            uuid4(),
            UUID(chapter_id),
            version_number,
            content,
            status,
            model_alias,
            prompt_template_version,
            json.dumps(generation_metadata) if generation_metadata else None,
            json.dumps(analysis_result) if analysis_result else None,
            user_feedback,
            created_by,
        )
        return pg_row_to_dict(row)


async def save_next_chapter_version(
    story_id: str,
    chapter_id: str,
    content: str,
    status: str,
    model_alias: str | None = None,
    prompt_template_version: str | None = None,
    generation_metadata: dict | None = None,
    analysis_result: dict | None = None,
    user_feedback: str | None = None,
    created_by: str = "system",
) -> dict | None:
    """Atomically allocates and writes the next version of an active chapter."""
    pool = get_db_pool()
    async with pool.acquire() as conn, conn.transaction():
        active = await conn.fetchrow(
            """
                SELECT id
                FROM story_chapters
                WHERE story_id = $1 AND id = $2 AND deleted_at IS NULL
                FOR UPDATE
                """,
            UUID(story_id),
            UUID(chapter_id),
        )
        if not active:
            return None
        version_number = await conn.fetchval(
            """
                SELECT COALESCE(MAX(version_number), 0) + 1
                FROM chapter_versions
                WHERE chapter_id = $1
                """,
            UUID(chapter_id),
        )
        row = await conn.fetchrow(
            """
                INSERT INTO chapter_versions (
                    id, chapter_id, version_number, content, status, model_alias,
                    prompt_template_version, generation_metadata, analysis_result,
                    user_feedback, created_by, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, NOW())
                RETURNING *
                """,
            uuid4(),
            UUID(chapter_id),
            version_number,
            content,
            status,
            model_alias,
            prompt_template_version,
            json.dumps(generation_metadata) if generation_metadata else None,
            json.dumps(analysis_result) if analysis_result else None,
            user_feedback,
            created_by,
        )
        return pg_row_to_dict(row)


async def update_chapter_version(
    chapter_id: str,
    version: dict,
    story_id: str | None = None,
    **changes,
) -> dict | None:
    fields = (
        "version_number",
        "content",
        "status",
        "model_alias",
        "prompt_template_version",
        "generation_metadata",
        "analysis_result",
        "user_feedback",
        "created_by",
    )
    values = version | changes
    return await save_chapter_version(
        chapter_id=chapter_id, story_id=story_id, **{field: values[field] for field in fields}
    )


async def get_latest_chapter_version(chapter_id: str) -> dict | None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM chapter_versions 
            WHERE chapter_id = $1 
            ORDER BY version_number DESC 
            LIMIT 1
        """,
            UUID(chapter_id),
        )
        return pg_row_to_dict(row) if row else None


async def get_story_chapter(story_id: str, chapter_id: str) -> dict | None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT cv.*
            FROM story_chapters chapter
            JOIN chapter_versions cv ON cv.chapter_id = chapter.id
            WHERE chapter.story_id = $1
              AND chapter.id = $2
              AND chapter.deleted_at IS NULL
            ORDER BY cv.version_number DESC, cv.created_at DESC
            LIMIT 1
        """,
            UUID(story_id),
            UUID(chapter_id),
        )
        return pg_row_to_dict(row) if row else None


async def resolve_story_chapter_version(
    story_id: str,
    chapter_id: str,
    version_id_or_num: str,
) -> dict | None:
    pool = get_db_pool()
    version_id = None
    version_number = None
    try:
        version_id = UUID(version_id_or_num)
    except ValueError:
        if version_id_or_num.isdigit():
            version_number = int(version_id_or_num)
        else:
            return None

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT version.*
            FROM story_chapters AS chapter
            JOIN chapter_versions AS version ON version.chapter_id = chapter.id
            WHERE chapter.story_id = $1
              AND chapter.id = $2
              AND chapter.deleted_at IS NULL
              AND (
                  ($3::uuid IS NOT NULL AND version.id = $3)
                  OR ($4::integer IS NOT NULL AND version.version_number = $4)
              )
            """,
            UUID(story_id),
            UUID(chapter_id),
            version_id,
            version_number,
        )
        return pg_row_to_dict(row) if row else None


async def get_chapter_version(chapter_id: str, version_number: int) -> dict | None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM chapter_versions 
            WHERE chapter_id = $1 AND version_number = $2
        """,
            UUID(chapter_id),
            version_number,
        )
        return pg_row_to_dict(row) if row else None


async def get_chapter_version_by_id(version_id: str) -> dict | None:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT * FROM chapter_versions 
            WHERE id = $1
        """,
            UUID(version_id),
        )
        return pg_row_to_dict(row) if row else None


async def resolve_chapter_version(chapter_id: str, version_id_or_num: str) -> dict | None:
    try:
        version = await get_chapter_version_by_id(str(UUID(version_id_or_num)))
        if version and str(version["chapter_id"]) == str(UUID(chapter_id)):
            return version
        return None
    except ValueError:
        pass

    return (
        await get_chapter_version(chapter_id, int(version_id_or_num))
        if version_id_or_num.isdigit()
        else None
    )


async def get_chapter_versions(chapter_id: str) -> list[dict]:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM chapter_versions 
            WHERE chapter_id = $1 
            ORDER BY version_number ASC
        """,
            UUID(chapter_id),
        )
        return [pg_row_to_dict(r) for r in rows]


async def delete_chapter(story_id: str, chapter_id: str) -> bool:
    pool = get_db_pool()
    story_uuid, chapter_uuid = UUID(story_id), UUID(chapter_id)
    async with pool.acquire() as conn, conn.transaction():
        chapter = await conn.fetchrow(
            """
                SELECT id
                FROM story_chapters
                WHERE story_id = $1 AND id = $2 AND deleted_at IS NULL
                FOR UPDATE
                """,
            story_uuid,
            chapter_uuid,
        )
        if not chapter:
            return False

        await conn.execute(
            """
                UPDATE story_chapters
                SET status = 'DELETED', deleted_at = NOW(), updated_at = NOW()
                WHERE story_id = $1 AND id = $2
                """,
            story_uuid,
            chapter_uuid,
        )
        await conn.execute(
            """
                UPDATE generation_jobs
                SET status = 'CANCELLED',
                    current_step = NULL,
                    completed_at = COALESCE(completed_at, NOW()),
                    error_payload = COALESCE(
                        error_payload,
                        '{"message":"Chapter was deleted while generation was active."}'::jsonb
                    )
                WHERE story_id = $1
                  AND chapter_id = $2
                  AND status NOT IN ('COMPLETED', 'FAILED', 'CANCELLED')
                """,
            story_uuid,
            chapter_uuid,
        )
        await conn.execute(
            "DELETE FROM story_memories WHERE story_id = $1 AND chapter_id = $2",
            story_uuid,
            chapter_uuid,
        )
        await conn.execute("DELETE FROM chapter_versions WHERE chapter_id = $1", chapter_uuid)
        await conn.execute(
            "DELETE FROM generation_jobs WHERE story_id = $1 AND chapter_id = $2",
            story_uuid,
            chapter_uuid,
        )
        return True


async def rename_chapter(story_id: str, chapter_id: str, title: str) -> bool:
    pool = get_db_pool()
    async with pool.acquire() as conn, conn.transaction():
        result = await conn.execute(
            """
            UPDATE story_chapters
            SET title = $3, updated_at = NOW()
            WHERE story_id = $1 AND id = $2 AND deleted_at IS NULL
            """,
            UUID(story_id),
            UUID(chapter_id),
            title,
        )
        if result == "UPDATE 0":
            return False
        await conn.execute(
            """
            UPDATE generation_jobs
            SET request_payload = jsonb_set(request_payload, '{chapter,title}', to_jsonb($3::text), true)
            WHERE story_id = $1 AND chapter_id = $2
        """,
            UUID(story_id),
            UUID(chapter_id),
            title,
        )
        return True


async def get_recent_chapters_content(story_id: str, limit: int = 3) -> list[dict]:
    pool = get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT selected_version.*
            FROM story_chapters sc
            JOIN LATERAL (
                SELECT cv.*
                FROM chapter_versions cv
                WHERE cv.chapter_id = sc.id
                  AND cv.status IN ('APPROVED', 'PUBLISHED')
                ORDER BY
                    CASE cv.status WHEN 'PUBLISHED' THEN 0 ELSE 1 END,
                    cv.version_number DESC,
                    cv.created_at DESC
                LIMIT 1
            ) selected_version ON TRUE
            WHERE sc.story_id = $1
              AND sc.deleted_at IS NULL
            ORDER BY sc.chapter_number DESC
            LIMIT $2
        """,
            UUID(story_id),
            limit,
        )
        return [pg_row_to_dict(r) for r in rows]


# ==============================================================================
# AUTHENTICATION DATA HELPERS (USERS, IDENTITIES, SESSIONS)
# ==============================================================================

async def get_user_by_email(email: str) -> dict | None:
    """Find a user by normalized email address."""
    normalized_email = email.strip().lower()
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, email, display_name, avatar_url, tier, is_active, created_at, updated_at
            FROM users
            WHERE email = $1
            """,
            normalized_email,
        )
        return pg_row_to_dict(row) if row else None


async def get_user_by_id(user_id: str | UUID) -> dict | None:
    """Find a user by user UUID."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, email, display_name, avatar_url, tier, is_active, created_at, updated_at
            FROM users
            WHERE id = $1
            """,
            UUID(str(user_id)),
        )
        return pg_row_to_dict(row) if row else None


async def get_identity_with_user(provider: str, provider_user_id: str) -> dict | None:
    """Find an auth identity along with its associated active user."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                i.id AS identity_id,
                i.user_id,
                i.provider,
                i.provider_user_id,
                i.password_hash,
                u.email,
                u.display_name,
                u.avatar_url,
                u.tier,
                u.is_active
            FROM auth_identities i
            JOIN users u ON u.id = i.user_id
            WHERE i.provider = $1 AND i.provider_user_id = $2
            """,
            provider,
            provider_user_id,
        )
        return pg_row_to_dict(row) if row else None


async def get_user_identities(user_id: str | UUID) -> list[str]:
    """List provider names linked to this user (e.g. ['password', 'google'])."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT provider FROM auth_identities WHERE user_id = $1",
            UUID(str(user_id)),
        )
        return [r["provider"] for r in rows]


async def create_user_with_identity(
    email: str,
    display_name: str,
    provider: str,
    provider_user_id: str,
    password_hash: str | None = None,
    avatar_url: str | None = None,
) -> dict:
    """Create a new user and their initial auth identity atomically."""
    normalized_email = email.strip().lower()
    pool = get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            user_row = await conn.fetchrow(
                """
                INSERT INTO users (email, display_name, avatar_url, tier, is_active)
                VALUES ($1, $2, $3, 'author', TRUE)
                RETURNING id, email, display_name, avatar_url, tier, is_active, created_at, updated_at
                """,
                normalized_email,
                display_name.strip(),
                avatar_url,
            )
            user_id = user_row["id"]

            await conn.execute(
                """
                INSERT INTO auth_identities (user_id, provider, provider_user_id, password_hash)
                VALUES ($1, $2, $3, $4)
                """,
                user_id,
                provider,
                provider_user_id,
                password_hash,
            )

            return pg_row_to_dict(user_row)


async def link_identity_to_user(
    user_id: str | UUID,
    provider: str,
    provider_user_id: str,
    password_hash: str | None = None,
) -> None:
    """Link an additional auth identity (e.g. Google) to an existing user."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO auth_identities (user_id, provider, provider_user_id, password_hash)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id, provider) DO NOTHING
            """,
            UUID(str(user_id)),
            provider,
            provider_user_id,
            password_hash,
        )


async def create_session(
    session_id: str,
    user_id: str | UUID,
    expires_at: datetime,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> None:
    """Create an active server-side session in PostgreSQL."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sessions (id, user_id, expires_at, ip_address, user_agent, last_activity_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
            """,
            session_id,
            UUID(str(user_id)),
            expires_at,
            ip_address,
            user_agent,
        )


async def get_session_user(session_id: str) -> dict | None:
    """Validate a session ID and return the authenticated user if unexpired."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                u.id,
                u.email,
                u.display_name,
                u.avatar_url,
                u.tier,
                u.is_active,
                s.expires_at,
                s.last_activity_at
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.id = $1
              AND s.expires_at > NOW()
              AND u.is_active = TRUE
            """,
            session_id,
        )
        if not row:
            return None

        # Touch last_activity_at
        await conn.execute(
            "UPDATE sessions SET last_activity_at = NOW() WHERE id = $1",
            session_id,
        )
        return pg_row_to_dict(row)


async def delete_session(session_id: str) -> None:
    """Revoke a single session."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM sessions WHERE id = $1", session_id)


async def delete_user_sessions(user_id: str | UUID) -> None:
    """Revoke all active sessions for a user (e.g. on password reset)."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM sessions WHERE user_id = $1", UUID(str(user_id)))


async def claim_legacy_stories_for_user(new_user_id: str | UUID) -> int:
    """Transfer unowned stories previously attributed to 'user_web_01' to the newly registered author."""
    pool = get_db_pool()
    uid_str = str(new_user_id)
    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            UPDATE stories
            SET user_id = $1
            WHERE user_id = 'user_web_01'
            """,
            uid_str,
        )
        # asyncpg execute returns e.g. "UPDATE 3"
        parts = result.split()
        return int(parts[-1]) if len(parts) >= 2 and parts[-1].isdigit() else 0


async def create_password_reset_token(
    user_id: str | UUID,
    token_hash: str,
    expires_at: datetime,
) -> None:
    """Store a SHA-256 hashed password reset token."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO password_reset_tokens (user_id, token_hash, expires_at)
            VALUES ($1, $2, $3)
            """,
            UUID(str(user_id)),
            token_hash,
            expires_at,
        )


async def get_valid_password_reset_token(token_hash: str) -> dict | None:
    """Fetch an unexpired, unused reset token by hash."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, user_id, token_hash, expires_at, used_at, created_at
            FROM password_reset_tokens
            WHERE token_hash = $1
              AND expires_at > NOW()
              AND used_at IS NULL
            """,
            token_hash,
        )
        return pg_row_to_dict(row) if row else None


async def reset_user_password(
    token_id: str | UUID,
    user_id: str | UUID,
    new_password_hash: str,
) -> None:
    """Mark reset token as used, update password hash, and revoke all sessions."""
    pool = get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE password_reset_tokens SET used_at = NOW() WHERE id = $1",
                UUID(str(token_id)),
            )
            await conn.execute(
                """
                UPDATE auth_identities
                SET password_hash = $1, updated_at = NOW()
                WHERE user_id = $2 AND provider = 'password'
                """,
                new_password_hash,
                UUID(str(user_id)),
            )
            await conn.execute(
                "DELETE FROM sessions WHERE user_id = $1",
                UUID(str(user_id)),
            )

