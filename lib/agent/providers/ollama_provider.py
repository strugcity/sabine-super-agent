"""Ollama provider adapter for local model inference."""

import os
from typing import Optional

from langchain_core.language_models import BaseChatModel

from ..llm_config import ModelConfig
from .base import BaseLLMProvider


class OllamaProvider(BaseLLMProvider):
    """
    Provider adapter for Ollama local models.

    Ollama runs models locally on your GPU (RTX 4080 Super = 16GB VRAM).
    This is Tier 1 (Local) for simple tasks with zero API cost.

    Supported models on 16GB VRAM:
    - Llama 3.2 3B (fast, simple tasks)
    - Phi-4 14B (good quality/speed balance)
    - Qwen 2.5 14B (strong coding)

    Note: Tool support in Ollama is experimental and limited,
    so this provider returns supports_tool_binding=False by default.
    """

    def __init__(self):
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    def create_llm(
        self,
        config: ModelConfig,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> BaseChatModel:
        """Create a ChatOllama instance."""
        # Import here to avoid requiring ollama if not used
        try:
            from langchain_ollama import ChatOllama
        except ImportError:
            raise ImportError(
                "langchain-ollama not installed. "
                "Run: pip install langchain-ollama"
            )

        return ChatOllama(
            model=config.model_id,
            base_url=self.base_url,
            temperature=temperature,
            num_predict=max_tokens or config.max_tokens,
        )

    def supports_tool_binding(self) -> bool:
        """
        Ollama tool support is experimental.

        While some Ollama models support tool calling, it's not reliable
        enough for production use. Return False to trigger escalation
        to a tier that supports tools when needed.
        """
        return False

    @property
    def provider_name(self) -> str:
        return "Ollama"
