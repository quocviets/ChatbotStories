import os
from dotenv import load_dotenv

# Load variables from .env file if it exists
load_dotenv()

# Database configuration
# Expected format: postgresql://username:password@host:port/database_name
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/ai_story_db")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# API Keys for LLM Providers
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Model Registry
# Map simple user-facing aliases to actual provider model identifiers
MODEL_REGISTRY = {
    "claude-sonnet": {
        "provider": "anthropic",
        "model_name": "claude-3-5-sonnet-20241022",
        "enabled": True,
        "capabilities": ["text_generation", "long_context"],
        "default_temperature": 0.8,
        "max_output_tokens": 8192,
        "recommended_for": ["CHAPTER_WRITING"],
    },
    "gpt-writing": {
        "provider": "openai",
        "model_name": "gpt-4o",
        "enabled": True,
        "capabilities": ["text_generation", "structured_output"],
        "default_temperature": 0.7,
        "max_output_tokens": 4096,
        "recommended_for": ["PLANNING", "ANALYSIS"],
    },
    "gemini-long-context": {
        "provider": "google",
        "model_name": "gemini-2.5-flash",
        "enabled": True,
        "capabilities": ["text_generation", "long_context"],
        "default_temperature": 0.8,
        "max_output_tokens": 8192,
        "recommended_for": ["CHAPTER_WRITING"],
    },
    "local-llama": {
        "provider": "ollama",
        "model_name": "llama3",
        "enabled": False,
        "capabilities": ["text_generation"],
        "default_temperature": 0.7,
        "max_output_tokens": 2048,
        "recommended_for": [],
    }
}

# Routing configurations
ROUTING_CONFIG = {
    "planner": "gpt-writing",
    "writer": "claude-sonnet",
    "analyzer": "gpt-writing",
    "summarizer": "gpt-writing",
    "embedding": "openai-embedding"
}

# Fallbacks configuration
FALLBACKS = {
    "claude-sonnet": ["gpt-writing", "gemini-long-context"],
    "gpt-writing": ["claude-sonnet"]
}
