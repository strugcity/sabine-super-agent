"""
LLM Configuration and Model Registry

Defines available models, tiers, and provider configurations for hybrid LLM routing.
This enables cost optimization by routing tasks to appropriate model tiers:
- Tier 1 (Local): Ollama models for simple tasks ($0)
- Tier 2 (API): Groq/Together for engineering tasks (~$0.05-0.20/M tokens)
- Tier 3 (Premium): Claude for consumer/security (~$3-15/M tokens)
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional
import os


class ModelTier(str, Enum):
    """Model tier classification for routing decisions."""
    LOCAL = "local"      # Tier 1: Local Ollama models (free)
    API = "api"          # Tier 2: Fast API models (Groq, Together)
    PREMIUM = "premium"  # Tier 3: Claude Sonnet/Opus


class ModelProvider(str, Enum):
    """Supported model providers."""
    OLLAMA = "ollama"
    GROQ = "groq"
    TOGETHER = "together"
    ANTHROPIC = "anthropic"


@dataclass
class ModelConfig:
    """Configuration for a specific model."""
    model_id: str
    provider: ModelProvider
    tier: ModelTier
    display_name: str
    max_tokens: int = 4096
    supports_tools: bool = True
    supports_vision: bool = False
    cost_per_1m_input: float = 0.0   # USD per 1M tokens
    cost_per_1m_output: float = 0.0  # USD per 1M tokens
    context_window: int = 8192


# =============================================================================
# Model Registry - All available models
# =============================================================================

MODEL_REGISTRY: Dict[str, ModelConfig] = {
    # -------------------------------------------------------------------------
    # Tier 1: Local Models (Ollama) - $0 cost
    # -------------------------------------------------------------------------
    "llama-3.2-3b": ModelConfig(
        model_id="llama3.2:3b",
        provider=ModelProvider.OLLAMA,
        tier=ModelTier.LOCAL,
        display_name="Llama 3.2 3B",
        max_tokens=2048,
        supports_tools=False,  # Limited tool support in small models
        cost_per_1m_input=0.0,
        cost_per_1m_output=0.0,
        context_window=8192,
    ),
    "phi-4": ModelConfig(
        model_id="phi4:latest",
        provider=ModelProvider.OLLAMA,
        tier=ModelTier.LOCAL,
        display_name="Phi-4 14B",
        max_tokens=2048,
        supports_tools=False,
        cost_per_1m_input=0.0,
        cost_per_1m_output=0.0,
        context_window=16384,
    ),
    "qwen-2.5-14b": ModelConfig(
        model_id="qwen2.5:14b",
        provider=ModelProvider.OLLAMA,
        tier=ModelTier.LOCAL,
        display_name="Qwen 2.5 14B",
        max_tokens=2048,
        supports_tools=False,
        cost_per_1m_input=0.0,
        cost_per_1m_output=0.0,
        context_window=32768,
    ),

    # -------------------------------------------------------------------------
    # Tier 2: API Models - Low cost, good performance
    # -------------------------------------------------------------------------
    "groq-llama-70b": ModelConfig(
        model_id="llama-3.3-70b-versatile",
        provider=ModelProvider.GROQ,
        tier=ModelTier.API,
        display_name="Groq Llama 3.3 70B",
        max_tokens=4096,
        supports_tools=True,
        cost_per_1m_input=0.059,   # $0.059/M input
        cost_per_1m_output=0.079,  # $0.079/M output
        context_window=128000,
    ),
    "together-qwen-72b": ModelConfig(
        model_id="Qwen/Qwen2.5-72B-Instruct-Turbo",
        provider=ModelProvider.TOGETHER,
        tier=ModelTier.API,
        display_name="Together Qwen 2.5 72B",
        max_tokens=4096,
        supports_tools=True,
        cost_per_1m_input=0.12,
        cost_per_1m_output=0.12,
        context_window=32768,
    ),

    # -------------------------------------------------------------------------
    # Tier 3: Premium Models (Anthropic) - Highest quality
    # -------------------------------------------------------------------------
    "claude-sonnet": ModelConfig(
        model_id="claude-sonnet-4-20250514",
        provider=ModelProvider.ANTHROPIC,
        tier=ModelTier.PREMIUM,
        display_name="Claude Sonnet 4",
        max_tokens=4096,
        supports_tools=True,
        supports_vision=True,
        cost_per_1m_input=3.0,    # $3/M input
        cost_per_1m_output=15.0,  # $15/M output
        context_window=200000,
    ),
    "claude-opus": ModelConfig(
        model_id="claude-opus-4-20250514",
        provider=ModelProvider.ANTHROPIC,
        tier=ModelTier.PREMIUM,
        display_name="Claude Opus 4",
        max_tokens=4096,
        supports_tools=True,
        supports_vision=True,
        cost_per_1m_input=15.0,
        cost_per_1m_output=75.0,
        context_window=200000,
    ),
}


# =============================================================================
# Tier Routing Configuration
# =============================================================================

@dataclass
class TierRoutingConfig:
    """Configuration for tier-based model routing."""

    # Default model per tier
    default_local: str = "phi-4"
    default_api: str = "groq-llama-70b"
    default_premium: str = "claude-sonnet"

    # Role -> Tier mapping
    # Engineering roles use cheaper models, consumer/security use premium
    role_tier_map: Dict[str, ModelTier] = field(default_factory=lambda: {
        # Engineering roles -> API tier (Groq)
        "backend-architect-sabine": ModelTier.API,
        "frontend-ops-sabine": ModelTier.API,
        "data-ai-engineer-sabine": ModelTier.API,
        "product-manager-sabine": ModelTier.API,
        # Security and orchestration -> Premium (Claude)
        "qa-security-sabine": ModelTier.PREMIUM,
        "SABINE_ARCHITECT": ModelTier.PREMIUM,
        # Consumer (no role) defaults to premium in router
    })

    # Keywords that trigger escalation to premium tier
    escalation_keywords: List[str] = field(default_factory=lambda: [
        "security", "vulnerability", "authentication", "authorization",
        "architecture", "design", "critical", "production",
        "refactor", "migrate", "integrate", "complex"
    ])


# =============================================================================
# Helper Functions
# =============================================================================

def get_routing_config() -> TierRoutingConfig:
    """Get the current routing configuration."""
    return TierRoutingConfig()


def get_model_config(model_key: str) -> Optional[ModelConfig]:
    """Get configuration for a specific model by key."""
    return MODEL_REGISTRY.get(model_key)


def get_models_by_tier(tier: ModelTier) -> List[ModelConfig]:
    """Get all models in a specific tier."""
    return [m for m in MODEL_REGISTRY.values() if m.tier == tier]


def get_models_by_provider(provider: ModelProvider) -> List[ModelConfig]:
    """Get all models from a specific provider."""
    return [m for m in MODEL_REGISTRY.values() if m.provider == provider]


def estimate_cost(
    model_key: str,
    input_tokens: int,
    output_tokens: int
) -> float:
    """
    Estimate the cost for a request in USD.

    Args:
        model_key: Key from MODEL_REGISTRY
        input_tokens: Number of input tokens
        output_tokens: Number of output tokens

    Returns:
        Estimated cost in USD
    """
    config = get_model_config(model_key)
    if not config:
        return 0.0

    input_cost = (input_tokens / 1_000_000) * config.cost_per_1m_input
    output_cost = (output_tokens / 1_000_000) * config.cost_per_1m_output
    return input_cost + output_cost
