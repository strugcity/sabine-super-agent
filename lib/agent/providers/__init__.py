"""
LLM Provider Adapters

Each adapter provides a unified interface for creating LangChain-compatible
LLM instances from different providers (Anthropic, Groq, Ollama, Together).

Usage:
    from lib.agent.providers import get_provider
    from lib.agent.llm_config import ModelProvider

    provider = get_provider(ModelProvider.GROQ)
    llm = provider.create_llm(model_config, temperature=0.7)
"""

from typing import Dict

from .base import BaseLLMProvider
from .anthropic_provider import AnthropicProvider
from .groq_provider import GroqProvider
from .ollama_provider import OllamaProvider

from ..llm_config import ModelProvider

__all__ = [
    "BaseLLMProvider",
    "AnthropicProvider",
    "GroqProvider",
    "OllamaProvider",
    "get_provider",
    "PROVIDER_MAP",
]

# Provider instances (singleton-like)
PROVIDER_MAP: Dict[ModelProvider, BaseLLMProvider] = {
    ModelProvider.ANTHROPIC: AnthropicProvider(),
    ModelProvider.GROQ: GroqProvider(),
    ModelProvider.OLLAMA: OllamaProvider(),
    # Together can be added when needed
}


def get_provider(provider: ModelProvider) -> BaseLLMProvider:
    """
    Get the provider adapter for a given provider type.

    Args:
        provider: The ModelProvider enum value

    Returns:
        BaseLLMProvider instance for the provider

    Raises:
        ValueError: If provider is not supported
    """
    if provider not in PROVIDER_MAP:
        raise ValueError(
            f"Provider {provider.value} not supported. "
            f"Available: {list(PROVIDER_MAP.keys())}"
        )
    return PROVIDER_MAP[provider]
