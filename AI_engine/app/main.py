import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.infrastructure.db.postgres_client import init_postgres, close_postgres
from app.infrastructure.redis.redis_client import init_redis, close_redis
from app.workers.generation_worker import worker_loop

from app.api.v1.story_generation_router import router as generation_router
from app.api.v1.story_analysis_router import router as analysis_router
from app.api.v1.job_router import router as job_router
from app.api.v1.model_router import router as model_router

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting AI Story Engine components...")
    
    # 1. Initialize DB and Cache
    await init_postgres()
    await init_redis()
    
    # 2. Start generation worker in the background
    worker_task = asyncio.create_task(worker_loop())
    logger.info("AI Story Engine services running.")
    
    yield
    
    # Shutdown
    logger.info("Stopping AI Story Engine components...")
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass
        
    await close_postgres()
    await close_redis()
    logger.info("AI Story Engine components stopped.")


tags_metadata = [
    {
        "name": "Story Generation",
        "description": "Quản lý và điều phối luồng sinh chương truyện, viết tiếp (continue), tái tạo bằng feedback (regenerate), duyệt lưu chương.",
    },
    {
        "name": "Story Analysis",
        "description": "Đánh giá chất lượng và phân tích lỗi logic, lỗi nhất quán nhân vật độc lập.",
    },
    {
        "name": "Jobs",
        "description": "Theo dõi tiến độ, hủy bỏ tiến trình và stream tokens thời gian thực qua Server-Sent Events (SSE).",
    },
    {
        "name": "Models",
        "description": "Xem danh sách các mô hình LLM đã đăng ký kèm năng lực và mức độ khuyên dùng.",
    },
]

app = FastAPI(
    title="AI Long-Form Story Generation Engine",
    version="1.0.0",
    description="Lõi xử lý Backend sinh truyện dài tập tích hợp PostgreSQL + pgvector và Redis (AI Engine).",
    openapi_tags=tags_metadata,
    lifespan=lifespan
)

# CORS middleware for local frontend development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include v1 routers
app.include_router(generation_router, prefix="/api/v1/ai")
app.include_router(analysis_router, prefix="/api/v1/ai")
app.include_router(job_router, prefix="/api/v1/ai")
app.include_router(model_router, prefix="/api/v1/ai")
