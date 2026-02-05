"""
Model Router - Intelligent LLM Selection

Routes requests to appropriate model tier based on:
1. Role configuration (model_preference in RoleManifest)
2. Role-based tier assignment
3. Task complexity analysis (keyword escalation)
4. Tool/vision requirements
5. Provider availability

Includes automatic fallback cascade when models fail.
"""

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .llm_config import (
    MODEL_REGISTRY,
    ModelConfig,
    ModelProvider,
    ModelTier,
    TierRoutingConfig,
    get_model_config,
    get_routing_config,
)
from .models import RoleManifest

logger = logging.getLogger(__name__)


@dataclass
class RoutingDecision:
    """Result of a routing decision."""
    model_config: ModelConfig
    tier: ModelTier
    reason: str
    fallback_chain: List[str]  # Ordered list of fallback model keys


class ModelRouter:
    """
    Routes LLM requests to appropriate model tier.

    Decision Flow:
    1. Check role's explicit model_preference (from RoleManifest)
    2. Check role's tier assignment (from config)
    3. Analyze task for complexity escalation keywords
    4. Verify tool/vision requirements are met
    5. Check provider availability
    6. Build fallback chain for resilience
    """

    def __init__(self, config: Optional[TierRoutingConfig] = None):
        self.config = config or get_routing_config()
        self._provider_available_cache: Dict[ModelProvider, bool] = {}

    def route(
        self,
        role: Optional[str] = None,
        role_manifest: Optional[RoleManifest] = None,
        task_payload: Optional[Dict[str, Any]] = None,
        requires_tools: bool = True,
        requires_vision: bool = False,
    ) -> RoutingDecision:
        """
        Determine the best model for a request.

        Args:
            role: Role ID (e.g., "backend-architect-sabine")
            role_manifest: Full role manifest if available
            task_payload: Task payload for complexity analysis
            requires_tools: Whether task needs tool calling
            requires_vision: Whether task needs vision capability

        Returns:
            RoutingDecision with selected model and fallback chain
        """
        # Step 1: Check explicit model preference in manifest
        if role_manifest and role_manifest.model_preference:
            model_key = role_manifest.model_preference
            if model_key in MODEL_REGISTRY:
                config = MODEL_REGISTRY[model_key]
                if self._meets_requirements(config, requires_tools, requires_vision):
                    if self._is_provider_available(config.provider):
                        logger.info(
                            f"Using explicit model_preference: {model_key} "
                            f"for role {role}"
                        )
                        return RoutingDecision(
                            model_config=config,
                            tier=config.tier,
                            reason=f"Explicit model_preference: {model_key}",
                            fallback_chain=self._build_fallback_chain(config.tier),
                        )
                logger.warning(
                    f"Model {model_key} unavailable or doesn't meet requirements, "
                    f"falling through to tier-based routing"
                )

        # Step 2: Determine tier from role
        tier = self._determine_tier_for_role(role)
        logger.debug(f"Role {role} mapped to tier: {tier.value}")

        # Step 3: Check for complexity escalation
        if task_payload:
            original_tier = tier
            tier = self._check_complexity_escalation(task_payload, tier)
            if tier != original_tier:
                logger.info(
                    f"Escalated from {original_tier.value} to {tier.value} "
                    f"due to complexity keywords"
                )

        # Step 4: Select model from tier with requirement checks
        model_config = self._select_model_from_tier(
            tier, requires_tools, requires_vision
        )

        if not model_config:
            # Escalate to premium as last resort
            logger.warning(
                f"No suitable model in {tier.value}, escalating to PREMIUM"
            )
            tier = ModelTier.PREMIUM
            model_config = get_model_config(self.config.default_premium)

        reason = f"Role-based routing: {role or 'consumer'} -> {tier.value}"

        return RoutingDecision(
            model_config=model_config,
            tier=tier,
            reason=reason,
            fallback_chain=self._build_fallback_chain(tier),
        )

    def _determine_tier_for_role(self, role: Optional[str]) -> ModelTier:
        """Determine the default tier for a role."""
        if not role:
            # Consumer/Sabine requests (no role) default to premium for quality
            return ModelTier.PREMIUM

        # Check explicit role->tier mapping
        if role in self.config.role_tier_map:
            return self.config.role_tier_map[role]

        # Infer from role name patterns
        engineering_patterns = ["architect", "engineer", "frontend", "backend", "ops"]
        if any(pattern in role.lower() for pattern in engineering_patterns):
            return ModelTier.API

        # Default to premium for unknown roles
        return ModelTier.PREMIUM

    def _check_complexity_escalation(
        self,
        payload: Dict[str, Any],
        current_tier: ModelTier
    ) -> ModelTier:
        """Check if task complexity warrants tier escalation."""
        if current_tier == ModelTier.PREMIUM:
            return current_tier  # Already at highest tier

        # Convert payload to searchable text
        payload_text = str(payload).lower()

        # Check for escalation keywords
        for keyword in self.config.escalation_keywords:
            if keyword.lower() in payload_text:
                logger.debug(f"Escalation keyword found: {keyword}")
                if current_tier == ModelTier.LOCAL:
                    return ModelTier.API
                elif current_tier == ModelTier.API:
                    return ModelTier.PREMIUM

        return current_tier

    def _select_model_from_tier(
        self,
        tier: ModelTier,
        requires_tools: bool,
        requires_vision: bool,
    ) -> Optional[ModelConfig]:
        """Select the best available model from a tier."""
        # Get default model for tier
        default_key = {
            ModelTier.LOCAL: self.config.default_local,
            ModelTier.API: self.config.default_api,
            ModelTier.PREMIUM: self.config.default_premium,
        }.get(tier)

        if default_key:
            model = get_model_config(default_key)
            if model and self._meets_requirements(model, requires_tools, requires_vision):
                if self._is_provider_available(model.provider):
                    return model

        # Try other models in the tier
        for key, config in MODEL_REGISTRY.items():
            if config.tier == tier:
                if self._meets_requirements(config, requires_tools, requires_vision):
                    if self._is_provider_available(config.provider):
                        logger.info(f"Selected alternate model {key} for tier {tier.value}")
                        return config

        return None

    def _meets_requirements(
        self,
        config: ModelConfig,
        requires_tools: bool,
        requires_vision: bool,
    ) -> bool:
        """Check if a model meets the task requirements."""
        if requires_tools and not config.supports_tools:
            return False
        if requires_vision and not config.supports_vision:
            return False
        return True

    def _is_provider_available(self, provider: ModelProvider) -> bool:
        """Check if a provider is available (API key configured, etc.)."""
        if provider in self._provider_available_cache:
            return self._provider_available_cache[provider]

        available = False

        if provider == ModelProvider.ANTHROPIC:
            available = bool(os.getenv("ANTHROPIC_API_KEY"))
        elif provider == ModelProvider.GROQ:
            available = bool(os.getenv("GROQ_API_KEY"))
        elif provider == ModelProvider.TOGETHER:
            available = bool(os.getenv("TOGETHER_API_KEY"))
        elif provider == ModelProvider.OLLAMA:
            # Ollama availability - check if URL is configured
            # Could add health check here in the future
            ollama_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            available = bool(ollama_url)

        self._provider_available_cache[provider] = available

        if not available:
            logger.debug(f"Provider {provider.value} not available")

        return available

    def _build_fallback_chain(self, starting_tier: ModelTier) -> List[str]:
        """Build ordered fallback chain from current tier upward."""
        chain = []

        if starting_tier == ModelTier.LOCAL:
            chain.append(self.config.default_local)
            chain.append(self.config.default_api)
            chain.append(self.config.default_premium)
        elif starting_tier == ModelTier.API:
            chain.append(self.config.default_api)
            chain.append(self.config.default_premium)
        else:
            chain.append(self.config.default_premium)

        return chain

    def clear_availability_cache(self):
        """Clear the provider availability cache (useful for testing)."""
        self._provider_available_cache.clear()


# =============================================================================
# Singleton and Helpers
# =============================================================================

_router: Optional[ModelRouter] = None


def get_model_router() -> ModelRouter:
    """Get or create the singleton model router."""
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router


def reset_model_router():
    """Reset the singleton router (useful for testing)."""
    global _router
    _router = None


# =============================================================================
# Fallback Execution Helper
# =============================================================================

class FallbackError(Exception):
    """Raised when all fallback models have failed."""

    def __init__(self, attempts: List[Dict[str, Any]]):
        self.attempts = attempts
        models = [a.get("model", "unknown") for a in attempts]
        super().__init__(f"All fallback attempts failed: {models}")


async def execute_with_fallback(
    execute_fn,
    routing_decision: RoutingDecision,
    max_attempts: int = 3,
) -> Any:
    """
    Execute a function with automatic fallback on failure.

    Args:
        execute_fn: Async function that takes (model_config) and returns result
        routing_decision: Initial routing decision with fallback chain
        max_attempts: Maximum number of fallback attempts

    Returns:
        Result from the first successful execution

    Raises:
        FallbackError: If all attempts fail
    """
    attempts = []
    fallback_chain = routing_decision.fallback_chain[:max_attempts]

    for i, model_key in enumerate(fallback_chain):
        model_config = get_model_config(model_key)
        if not model_config:
            logger.warning(f"Fallback model {model_key} not found, skipping")
            continue

        try:
            logger.info(
                f"Attempt {i + 1}/{len(fallback_chain)}: "
                f"Trying {model_config.display_name}"
            )
            result = await execute_fn(model_config)

            if i > 0:
                logger.info(
                    f"Fallback successful: {model_config.display_name} "
                    f"(after {i} failed attempts)"
                )

            return result

        except Exception as e:
            logger.warning(
                f"Model {model_config.display_name} failed: {type(e).__name__}: {e}"
            )
            attempts.append({
                "model": model_key,
                "error": str(e),
                "error_type": type(e).__name__,
            })

    raise FallbackError(attempts)
