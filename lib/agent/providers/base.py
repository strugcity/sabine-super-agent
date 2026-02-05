"""Base class for LLM provider adapters."""

from abc import ABC, abstractmethod
from typing import List, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from ..llm_config import ModelConfig


class BaseLLMProvider(ABC):
    """
    Abstract base class for LLM provider adapters.

    Each provider (Anthropic, Groq, Ollama, etc.) implements this interface
    to provide a consistent way to create LLM instances and bind tools.
    """

    @abstractmethod
    def create_llm(
        self,
        config: ModelConfig,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> BaseChatModel:
        """
        Create a LangChain-compatible LLM instance.

        Args:
            config: Model configuration from MODEL_REGISTRY
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Maximum output tokens (uses config default if None)

        Returns:
            BaseChatModel instance ready for use with LangGraph
        """
        pass

    @abstractmethod
    def supports_tool_binding(self) -> bool:
        """
        Whether this provider supports native tool binding.

        Returns:
            True if bind_tools() will work, False otherwise
        """
        pass

    def bind_tools(
        self,
        llm: BaseChatModel,
        tools: List[BaseTool],
    ) -> BaseChatModel:
        """
        Bind tools to the LLM if supported.

        Args:
            llm: The LLM instance to bind tools to
            tools: List of tools to bind

        Returns:
            LLM with tools bound (or original LLM if not supported)
        """
        if self.supports_tool_binding() and tools:
            return llm.bind_tools(tools)
        return llm

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name for logging."""
        pass
