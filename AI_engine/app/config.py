import os
from dotenv import load_dotenv

# Load variables from .env file if it exists
api_env_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../API/.env"))
if os.path.exists(api_env_path):
    load_dotenv(dotenv_path=api_env_path)
load_dotenv()


# Database configuration
# Expected format: postgresql://username:password@host:port/database_name
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgrespassword@localhost:5433/ai_story_db")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# API Keys for LLM Providers
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
LLM_VERIFY_TLS = os.getenv("LLM_VERIFY_TLS", "true").lower() == "true"

# Model Names Configured via Env
CLAUDE_MODEL_NAME = os.getenv("CLAUDE_MODEL_NAME", "claude-sonnet-4-6")
GPT_MODEL_NAME = os.getenv("GPT_MODEL_NAME", "gpt-4o")
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-3.6-flash")

# Model Registry
# Map simple user-facing aliases to actual provider model identifiers
MODEL_REGISTRY = {
    "claude-sonnet": {
        "provider": "anthropic",
        "model_name": CLAUDE_MODEL_NAME,
        "enabled": True,
        "capabilities": ["text_generation", "long_context"],
        "recommended_for": ["CHAPTER_WRITING"],
    },
    "gpt-writing": {
        "provider": "openai",
        "model_name": GPT_MODEL_NAME,
        "enabled": True,
        "capabilities": ["text_generation", "structured_output"],
        "recommended_for": ["PLANNING", "ANALYSIS"],
    },
    "gemini-long-context": {
        "provider": "google",
        "model_name": GEMINI_MODEL_NAME,
        "enabled": True,
        "capabilities": ["text_generation", "long_context"],
        "recommended_for": ["CHAPTER_WRITING"],
    },
    "local-llama": {
        "provider": "ollama",
        "model_name": "llama3",
        "enabled": False,
        "capabilities": ["text_generation"],
        "recommended_for": [],
    }
}

# Routing configurations
ROUTING_CONFIG = {
    "planner": "gemini-long-context",
    "analyzer": "gemini-long-context",
    "summarizer": "gemini-long-context"
}

# Fallbacks configuration
FALLBACKS = {
    "claude-sonnet": ["gpt-writing", "gemini-long-context"],
    "gpt-writing": ["claude-sonnet", "gemini-long-context"],
    "gemini-long-context": ["gpt-writing", "claude-sonnet"]
}
