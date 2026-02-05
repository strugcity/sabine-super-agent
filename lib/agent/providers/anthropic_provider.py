"""Anthropic Claude provider adapter."""

import os
from typing import Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel

from ..llm_config import ModelConfig
from .base import BaseLLMProvider


class AnthropicProvider(BaseLLMProvider):
    """
    Provider adapter for Anthropic Claude models.

    This is the premium tier provider with:
    - Best reasoning capability
    - Full tool support
    - Vision support
    - Prompt caching (handled separately in core.py)
    """

    def create_llm(
        self,
        config: ModelConfig,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> BaseChatModel:
        """Create a ChatAnthropic instance."""
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable not set")

        return ChatAnthropic(
            model=config.model_id,
            anthropic_api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens or config.max_tokens,
        )

    def supports_tool_binding(self) -> bool:
        """Anthropic fully supports tool binding."""
        return True

    @property
    def provider_name(self) -> str:
        return "Anthropic"
