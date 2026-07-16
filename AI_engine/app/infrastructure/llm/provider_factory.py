from typing import Union
from app.config import MODEL_REGISTRY
from app.infrastructure.llm.providers.openai_provider import OpenAIProvider
from app.infrastructure.llm.providers.anthropic_provider import AnthropicProvider
from app.infrastructure.llm.providers.gemini_provider import GeminiProvider
from app.infrastructure.llm.providers.ollama_provider import OllamaProvider

ProviderType = Union[OpenAIProvider, AnthropicProvider, GeminiProvider, OllamaProvider]

class LLMProviderFactory:
    @staticmethod
    def get_provider(model_alias: str) -> ProviderType:
        config = MODEL_REGISTRY.get(model_alias)
        if not config:
            raise ValueError(f"Model alias '{model_alias}' is not registered.")
            
        if not config.get("enabled", True):
            raise ValueError(f"Model alias '{model_alias}' is disabled.")
            
        provider = config["provider"]
        model_name = config["model_name"]
        
        if provider == "openai":
            return OpenAIProvider(model_name)
        elif provider == "anthropic":
            return AnthropicProvider(model_name)
        elif provider == "google":
            return GeminiProvider(model_name)
        elif provider == "ollama":
            return OllamaProvider(model_name)
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")
