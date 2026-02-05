"""Groq provider adapter for fast inference."""

import os
from typing import Optional

from langchain_core.language_models import BaseChatModel

from ..llm_config import ModelConfig
from .base import BaseLLMProvider


class GroqProvider(BaseLLMProvider):
    """
    Provider adapter for Groq API.

    Groq offers extremely fast inference with models like Llama 3.3 70B.
    This is the primary Tier 2 (API) provider for engineering tasks.

    Features:
    - Very fast inference (~276 tokens/sec)
    - Tool calling support
    - Low cost (~$0.05-0.08/M tokens)
    """

    def create_llm(
        self,
        config: ModelConfig,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> BaseChatModel:
        """Create a ChatGroq instance."""
        # Import here to avoid requiring groq if not used
        try:
            from langchain_groq import ChatGroq
        except ImportError:
            raise ImportError(
                "langchain-groq not installed. "
                "Run: pip install langchain-groq"
            )

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY environment variable not set")

        return ChatGroq(
            model=config.model_id,
            groq_api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens or config.max_tokens,
        )

    def supports_tool_binding(self) -> bool:
        """Groq supports tool binding."""
        return True

    @property
    def provider_name(self) -> str:
        return "Groq"
