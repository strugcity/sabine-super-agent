"""
Personal Super Agent - Core Orchestrator

This is the brain of the Personal Super Agent. It implements:

1. DEEP CONTEXT INJECTION: Loads user rules and custody state before processing queries
2. UNIFIED TOOL REGISTRY: Seamlessly uses both local skills and MCP integrations
3. LANGRAPH STATE MACHINE: Manages conversation flow with memory
4. DUAL-BRAIN MEMORY: Vector store + Knowledge graph integration

The agent is powered by Anthropic Claude 3.5 Sonnet for primary logic
and GPT-4o-Mini for routing decisions.
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, TypedDict

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.prebuilt import create_react_agent
from supabase import create_client, Client

from .registry import get_all_tools

logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

# Supabase client (for database access)
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

supabase: Optional[Client] = None
if SUPABASE_URL and SUPABASE_SERVICE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        logger.info("✓ Supabase client initialized")
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {e}")

# =============================================================================
# Agent State
# =============================================================================

class AgentState(TypedDict):
    """State for the LangGraph agent."""
    messages: List[BaseMessage]
    user_id: str
    session_id: str
    deep_context: Dict[str, Any]
    tools: List[StructuredTool]


# =============================================================================
# Deep Context Injection
# =============================================================================

async def load_deep_context(user_id: str) -> Dict[str, Any]:
    """
    Load "Deep Context" for a user.

    This is CRITICAL for the agent to understand the user's situation.
    Deep Context includes:
    - Active rules and triggers
    - Current custody schedule state
    - User preferences and settings
    - Recent memories (from vector store)

    Args:
        user_id: The user's UUID

    Returns:
        Dictionary containing all deep context data
    """
    context: Dict[str, Any] = {
        "user_id": user_id,
        "loaded_at": datetime.now().isoformat(),
        "rules": [],
        "custody_state": {},
        "user_config": {},
        "recent_memories": []
    }

    if not supabase:
        logger.warning("Supabase not initialized - returning empty context")
        return context

    try:
        # Load active rules
        rules_response = supabase.table("rules") \
            .select("*") \
            .eq("user_id", user_id) \
            .eq("is_active", True) \
            .order("priority", desc=True) \
            .execute()

        context["rules"] = rules_response.data if rules_response.data else []
        logger.info(f"Loaded {len(context['rules'])} active rules for user {user_id}")

        # Load current custody schedule
        today = datetime.now().date()
        week_ahead = today + timedelta(days=7)

        custody_response = supabase.table("custody_schedule") \
            .select("*") \
            .eq("user_id", user_id) \
            .gte("start_date", str(today)) \
            .lte("end_date", str(week_ahead)) \
            .order("start_date") \
            .execute()

        context["custody_state"] = {
            "current_period": custody_response.data[0] if custody_response.data else None,
            "upcoming_periods": custody_response.data if custody_response.data else [],
            "query_range": {
                "start": str(today),
                "end": str(week_ahead)
            }
        }
        logger.info(f"Loaded custody schedule for user {user_id}")

        # Load user configuration
        config_response = supabase.table("user_config") \
            .select("*") \
            .eq("user_id", user_id) \
            .execute()

        if config_response.data:
            # Convert list of {key, value} to a dict
            context["user_config"] = {
                item["key"]: item["value"]
                for item in config_response.data
            }
        logger.info(f"Loaded {len(context['user_config'])} config settings for user {user_id}")

        # Load recent memories (last 10, most important first)
        # Note: In production, you'd use vector similarity search for relevant memories
        memories_response = supabase.table("memories") \
            .select("content, metadata, importance_score, created_at") \
            .eq("user_id", user_id) \
            .order("importance_score", desc=True) \
            .order("created_at", desc=True) \
            .limit(10) \
            .execute()

        context["recent_memories"] = memories_response.data if memories_response.data else []
        logger.info(f"Loaded {len(context['recent_memories'])} recent memories for user {user_id}")

    except Exception as e:
        logger.error(f"Error loading deep context for user {user_id}: {e}")

    return context


def build_system_prompt(deep_context: Dict[str, Any]) -> str:
    """
    Build the system prompt with injected deep context.

    This is where the agent's personality and awareness come from.
    The system prompt includes:
    - Agent identity and purpose
    - Available tools (local + MCP)
    - User-specific rules
    - Current custody state
    - User preferences

    Args:
        deep_context: The loaded deep context

    Returns:
        Complete system prompt string
    """
    user_id = deep_context.get("user_id", "unknown")
    rules = deep_context.get("rules", [])
    custody_state = deep_context.get("custody_state", {})
    user_config = deep_context.get("user_config", {})
    memories = deep_context.get("recent_memories", [])

    prompt = f"""You are the Personal Super Agent, an AI assistant specialized in managing family logistics, complex tasks, and deep contextual information.

# YOUR IDENTITY
- You have access to both internal skills and external integrations
- You can seamlessly use local tools and remote services (via MCP)
- You understand family schedules, custody arrangements, and user preferences

# USER CONTEXT (User ID: {user_id})

## Active Rules
"""

    # Inject rules
    if rules:
        for i, rule in enumerate(rules, 1):
            prompt += f"\n{i}. **{rule.get('name', 'Unnamed Rule')}**\n"
            prompt += f"   - Trigger: {rule.get('trigger_condition', {})}\n"
            prompt += f"   - Action: {rule.get('action_logic', {})}\n"
            if rule.get('description'):
                prompt += f"   - Description: {rule['description']}\n"
    else:
        prompt += "\n*No active rules configured*\n"

    # Inject custody schedule
    prompt += "\n## Current Custody Schedule\n"
    current_period = custody_state.get("current_period")
    if current_period:
        prompt += f"\n**Current Period:**\n"
        prompt += f"- Child: {current_period.get('child_name', 'Unknown')}\n"
        prompt += f"- With: {current_period.get('parent_with_custody', 'Unknown')}\n"
        prompt += f"- Dates: {current_period.get('start_date')} to {current_period.get('end_date')}\n"
        if current_period.get('notes'):
            prompt += f"- Notes: {current_period['notes']}\n"
    else:
        prompt += "\n*No current custody period found*\n"

    upcoming = custody_state.get("upcoming_periods", [])
    if len(upcoming) > 1:
        prompt += f"\n**Upcoming Periods:** {len(upcoming) - 1} periods in the next 7 days\n"

    # Inject user preferences
    prompt += "\n## User Preferences\n"
    if user_config:
        for key, value in user_config.items():
            prompt += f"- {key}: {value}\n"
    else:
        prompt += "*No preferences configured*\n"

    # Inject recent memories
    if memories:
        prompt += f"\n## Recent Context (Last {len(memories)} memories)\n"
        for memory in memories[:5]:  # Show top 5
            content = memory.get("content", "")
            if len(content) > 100:
                content = content[:97] + "..."
            prompt += f"- {content}\n"

    # Core instructions
    prompt += """

# YOUR CAPABILITIES

You have access to multiple tools:
- **Local Skills**: Python functions for core agent capabilities
- **MCP Integrations**: External services like Google Drive, Calendar, etc.

Use these tools seamlessly to help the user. You don't need to explain which type of tool you're using.

# GUIDELINES

1. **Proactive**: Use the custody schedule and rules to anticipate needs
2. **Contextual**: Reference the user's preferences and memories when relevant
3. **Efficient**: Execute rules and triggers automatically when conditions are met
4. **Clear**: Communicate in a friendly, concise manner
5. **Reliable**: Double-check dates and critical information

# IMPORTANT

- Always check the custody schedule before making plans
- Follow the user's active rules strictly
- Store important information as memories for future reference
- Be aware of the current date and time for scheduling

Current date: {datetime.now().strftime("%A, %B %d, %Y")}
Current time: {datetime.now().strftime("%I:%M %p")}
"""

    return prompt


# =============================================================================
# Agent Creation
# =============================================================================

async def create_agent(
    user_id: str,
    session_id: str,
    model_name: str = "claude-3-5-sonnet-20241022"
) -> tuple[Any, Dict[str, Any]]:
    """
    Create a Personal Super Agent instance with full context.

    This function:
    1. Loads all available tools (local + MCP)
    2. Loads deep context for the user
    3. Builds the system prompt
    4. Creates a LangGraph ReAct agent

    Args:
        user_id: The user's UUID
        session_id: The conversation session ID
        model_name: The Anthropic model to use (default: Claude 3.5 Sonnet)

    Returns:
        Tuple of (agent, deep_context)
    """
    logger.info(f"Creating agent for user {user_id}, session {session_id}")

    # Load all tools
    tools = await get_all_tools()
    logger.info(f"Loaded {len(tools)} tools for agent")

    # Load deep context
    deep_context = await load_deep_context(user_id)
    logger.info(f"Loaded deep context for user {user_id}")

    # Build system prompt
    system_prompt = build_system_prompt(deep_context)

    # Create LLM
    llm = ChatAnthropic(
        model=model_name,
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        temperature=0.7,
        max_tokens=4096
    )

    # Create ReAct agent with system prompt as messages_modifier
    # The messages_modifier is a function that prepends the system prompt
    def add_system_prompt(state):
        """Add system prompt to the beginning of messages."""
        from langchain_core.messages import SystemMessage
        messages = state.get("messages", [])
        if not messages or not isinstance(messages[0], SystemMessage):
            return [SystemMessage(content=system_prompt)] + messages
        return messages

    agent = create_react_agent(
        llm,
        tools,
        messages_modifier=add_system_prompt
    )

    logger.info("✓ Agent created successfully")

    return agent, deep_context


# =============================================================================
# Agent Execution
# =============================================================================

async def run_agent(
    user_id: str,
    session_id: str,
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None
) -> Dict[str, Any]:
    """
    Run the Personal Super Agent with a user message.

    Args:
        user_id: The user's UUID
        session_id: The conversation session ID
        user_message: The user's input message
        conversation_history: Optional previous conversation history

    Returns:
        Dictionary with agent response and metadata
    """
    try:
        # Create agent
        agent, deep_context = await create_agent(user_id, session_id)

        # Build message history
        messages: List[BaseMessage] = []

        # Add conversation history if provided
        if conversation_history:
            for msg in conversation_history:
                if msg["role"] == "user":
                    messages.append(HumanMessage(content=msg["content"]))
                elif msg["role"] == "assistant":
                    messages.append(AIMessage(content=msg["content"]))

        # Add current user message
        messages.append(HumanMessage(content=user_message))

        # Run agent
        logger.info(f"Running agent for user {user_id}")
        result = await agent.ainvoke({"messages": messages})

        # Extract response
        agent_messages = result.get("messages", [])
        if agent_messages:
            last_message = agent_messages[-1]
            response_text = last_message.content if hasattr(last_message, "content") else str(last_message)
        else:
            response_text = "I apologize, but I couldn't generate a response."

        return {
            "success": True,
            "response": response_text,
            "user_id": user_id,
            "session_id": session_id,
            "deep_context_loaded": True,
            "tools_available": len(await get_all_tools()),
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        logger.error(f"Error running agent: {e}")
        return {
            "success": False,
            "error": str(e),
            "user_id": user_id,
            "session_id": session_id,
            "timestamp": datetime.now().isoformat()
        }


# =============================================================================
# Convenience Functions
# =============================================================================

def run_agent_sync(
    user_id: str,
    session_id: str,
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None
) -> Dict[str, Any]:
    """
    Synchronous wrapper for run_agent.

    Args:
        user_id: The user's UUID
        session_id: The conversation session ID
        user_message: The user's input message
        conversation_history: Optional previous conversation history

    Returns:
        Dictionary with agent response and metadata
    """
    return asyncio.run(run_agent(user_id, session_id, user_message, conversation_history))
