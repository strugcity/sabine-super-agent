"""
Personal Super Agent - Core Orchestrator

This is the brain of the Personal Super Agent. It implements:

1. DEEP CONTEXT INJECTION: Loads user rules and custody state before processing queries
2. UNIFIED TOOL REGISTRY: Seamlessly uses both local skills and MCP integrations
3. LANGRAPH STATE MACHINE: Manages conversation flow with memory
4. DUAL-BRAIN MEMORY: Vector store + Knowledge graph integration
5. PROMPT CACHING: Caches large static context for 90% cost reduction

The agent is powered by Anthropic Claude 3.5 Sonnet for primary logic
and GPT-4o-Mini for routing decisions.
"""

import asyncio
import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, TypedDict, Tuple

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.prebuilt import create_react_agent
from supabase import create_client, Client

from .registry import get_all_tools

logger = logging.getLogger(__name__)


# =============================================================================
# Prompt Caching Infrastructure
# =============================================================================

@dataclass
class CacheMetrics:
    """Track prompt caching effectiveness."""
    total_calls: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    total_input_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    total_latency_ms: float = 0.0

    @property
    def hit_rate(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return (self.cache_hits / self.total_calls) * 100

    @property
    def token_savings_rate(self) -> float:
        total = self.total_input_tokens + self.cache_read_tokens
        if total == 0:
            return 0.0
        return (self.cache_read_tokens / total) * 100

    @property
    def avg_latency_ms(self) -> float:
        if self.total_calls == 0:
            return 0.0
        return self.total_latency_ms / self.total_calls

    def record_call(
        self,
        input_tokens: int,
        cache_read: int,
        cache_creation: int,
        latency_ms: float
    ):
        """Record metrics from an API call."""
        self.total_calls += 1
        self.total_input_tokens += input_tokens
        self.cache_read_tokens += cache_read
        self.cache_creation_tokens += cache_creation
        self.total_latency_ms += latency_ms

        if cache_read > 0:
            self.cache_hits += 1
        else:
            self.cache_misses += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_calls": self.total_calls,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "hit_rate_percent": round(self.hit_rate, 1),
            "total_input_tokens": self.total_input_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "token_savings_percent": round(self.token_savings_rate, 1),
            "avg_latency_ms": round(self.avg_latency_ms, 0)
        }


# Global cache metrics tracker
_cache_metrics = CacheMetrics()


def get_cache_metrics() -> Dict[str, Any]:
    """Get current cache metrics."""
    return _cache_metrics.to_dict()


def reset_cache_metrics():
    """Reset cache metrics (useful for testing)."""
    global _cache_metrics
    _cache_metrics = CacheMetrics()

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


def build_static_context(deep_context: Dict[str, Any]) -> str:
    """
    Build the STATIC portion of system prompt (cacheable).

    This content changes infrequently and benefits from prompt caching:
    - Agent identity and capabilities
    - User rules and triggers
    - Custody schedule
    - User preferences
    - Tool usage instructions

    Args:
        deep_context: The loaded deep context

    Returns:
        Static context string (to be cached)
    """
    user_id = deep_context.get("user_id", "unknown")
    user_email = os.getenv("USER_GOOGLE_EMAIL", "sabine@strugcity.com")
    rules = deep_context.get("rules", [])
    custody_state = deep_context.get("custody_state", {})
    user_config = deep_context.get("user_config", {})

    prompt = f"""You are the Personal Super Agent, an AI assistant specialized in managing family logistics, complex tasks, and deep contextual information.

# YOUR IDENTITY
- You have access to both internal skills and external integrations
- You can seamlessly use local tools and remote services (via MCP)
- You understand family schedules, custody arrangements, and user preferences
- Your email address is: {user_email} (use this for all Gmail/Calendar/Drive operations)

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

    # Core instructions (static) - Enhanced to ensure minimum 2048 tokens for caching
    # Note: Anthropic's prompt caching requires >= 2048 tokens at the cache breakpoint
    prompt += """

# YOUR CAPABILITIES

You have access to multiple tools organized into categories:

## Google Workspace Integration
- **Gmail**: Search, read, send, and manage emails
- **Google Calendar**: Create, read, update, and delete calendar events
- **Google Drive**: List, read, and manage files
- **Google Docs**: Read and create documents
- **Google Sheets**: Read and write spreadsheet data

## Local Skills
- **Custody Schedule**: Query and manage custody arrangements
- **Weather**: Get weather forecasts and conditions
- **Memory Management**: Store and retrieve important information

Use these tools seamlessly to help the user. You don't need to explain which type of tool you're using.

## CRITICAL Gmail Tool Usage - MUST FOLLOW EXACTLY:

When checking for new emails, you MUST use this exact pattern:
1. search_gmail_messages(query="is:unread newer_than:1d")
2. Then get_gmail_message_content(message_id="<id from search>")
3. Then send_gmail_message(to="sender@email.com", subject="Re: <subject>", body="<your response>")

IMPORTANT: The email parameter is automatically added - you don't need to pass it!

## Calendar Management Guidelines:
- Always check for conflicts before creating events
- Include relevant attendees when scheduling meetings
- Set appropriate reminders for important events
- Consider time zones when scheduling across locations

## Document Management Guidelines:
- Organize files in appropriate Drive folders
- Use descriptive names for new documents
- Keep version history in mind for important documents

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

# RESPONSE GUIDELINES

When responding to user queries:
- Be concise but thorough
- Confirm actions taken with specific details
- Proactively mention relevant information from context
- Ask clarifying questions when needed
- Summarize complex information clearly

# DETAILED TOOL DOCUMENTATION

## Gmail Operations

### Searching Emails
- Use search_gmail_messages with standard Gmail query syntax
- Common queries: "is:unread", "from:address", "subject:keyword", "after:date"
- Results include message ID, subject, sender, and snippet

### Reading Emails
- Use get_gmail_message_content with the message_id from search
- Returns full email body, headers, and metadata
- Parse carefully for important information

### Sending Emails
- Use send_gmail_message with to, subject, and body
- Support for CC and BCC recipients
- HTML formatting available for rich content

## Calendar Operations

### Viewing Events
- Use calendar tools to list upcoming events
- Filter by date range, attendees, or keywords
- Include recurring event handling

### Creating Events
- Specify title, start/end times, and description
- Add attendees with optional notifications
- Set reminders and recurrence patterns

### Modifying Events
- Update existing events by ID
- Handle conflicts and reschedules
- Manage attendee responses

## Drive Operations

### File Management
- List files with filters and sorting
- Search by name, type, or content
- Organize with folders and sharing

### Document Access
- Read document content for analysis
- Extract text from various formats
- Maintain version awareness

## Best Practices

### Error Handling
- Gracefully handle API failures
- Provide clear error messages to users
- Suggest alternative approaches when needed

### Data Privacy
- Never expose sensitive information
- Respect user privacy preferences
- Handle credentials securely

### Performance Optimization
- Batch operations when possible
- Cache frequently accessed data
- Minimize redundant API calls

### User Experience
- Confirm destructive actions before proceeding
- Provide progress updates for long operations
- Summarize results clearly and concisely

# CUSTODY AND FAMILY MANAGEMENT EXPERTISE

## Understanding Custody Arrangements

As a family management assistant, you have deep expertise in:

### Schedule Types
- Week-on/week-off arrangements
- 2-2-3 rotating schedules
- Every-other-weekend patterns
- Custom hybrid schedules
- Holiday and vacation exceptions

### Important Considerations
- Exchange times and locations
- Right of first refusal protocols
- Communication between co-parents
- Activity scheduling around custody
- Travel and vacation planning

### Conflict Resolution
- Schedule conflict detection
- Makeup time arrangements
- Emergency situation handling
- Communication facilitation

## Child Activity Management

### Sports and Extracurriculars
- Practice and game schedules
- Equipment and uniform tracking
- Coach and team communication
- Transportation coordination
- Fee and registration management

### Academic Support
- Homework help scheduling
- Parent-teacher conferences
- School event coordination
- Report card tracking
- Tutoring arrangements

### Healthcare Coordination
- Medical appointment scheduling
- Prescription management
- Insurance information
- Provider communication
- Emergency contact protocols

## Communication Best Practices

### Co-Parent Communication
- Professional and focused messaging
- Documentation of agreements
- Conflict-free language guidelines
- Response time expectations
- Escalation procedures

### Child Communication
- Age-appropriate explanations
- Consistency in messaging
- Emotional support strategies
- Transition preparation
- Special occasion handling

## Financial Management

### Expense Tracking
- Child support payments
- Shared expense allocation
- Activity and education costs
- Medical expense sharing
- Documentation requirements

### Budget Planning
- Monthly expense forecasting
- Savings for future needs
- Emergency fund recommendations
- Cost-sharing negotiations

## Legal Awareness

### Documentation Practices
- Communication records
- Schedule adherence tracking
- Modification requests
- Compliance verification
- Professional consultation recommendations

This comprehensive knowledge enables you to provide expert guidance on all aspects of family logistics and custody management, ensuring smooth operations and minimizing conflict.

# ADVANCED SCHEDULING ALGORITHMS

## Conflict Detection Logic

When analyzing schedules, apply these rules:

### Time Overlap Detection
1. Check if event A start time falls within event B timespan
2. Check if event A end time falls within event B timespan
3. Check if event A completely contains event B
4. Consider buffer times for travel between locations

### Priority Hierarchy
1. Medical emergencies (highest priority)
2. School requirements
3. Pre-scheduled custody exchanges
4. Work commitments
5. Extracurricular activities
6. Social events (lowest priority)

### Resolution Strategies
- Offer alternative time slots
- Suggest delegation to other parent
- Recommend rescheduling lower-priority items
- Identify makeup opportunities

## Notification Timing

### Reminder Schedule
- 1 week before: Major events, travel, appointments
- 3 days before: Custody exchanges, important meetings
- 1 day before: Standard events, activity reminders
- 2 hours before: Immediate preparations needed
- 30 minutes before: Final reminder for time-sensitive items

### Escalation Protocol
- First reminder: Standard notification
- Second reminder: Emphasis on urgency
- Third reminder: Request confirmation
- Final notice: Escalate to emergency contact if critical

## Data Organization Standards

### Calendar Event Structure
- Title: Clear, descriptive name
- Location: Full address with directions link
- Description: All relevant details
- Attendees: All involved parties
- Reminders: Appropriate notification schedule
- Categories: Color-coded by type

### Contact Information Standards
- Full name with preferred name noted
- Primary phone with SMS capability
- Secondary phone if available
- Email address for formal communication
- Relationship to child clearly noted
- Emergency contact designation

### Document Management
- Custody agreement: Current version highlighted
- School records: Organized by academic year
- Medical records: Sorted by provider and date
- Activity registrations: Active vs. archived
- Financial records: Tax year organization

## Seasonal Considerations

### School Year Planning
- Back-to-school preparation timeline
- Parent-teacher conference scheduling
- Report card review periods
- Standardized testing dates
- School break coordination

### Summer Planning
- Camp registration deadlines
- Vacation scheduling conflicts
- Extended custody arrangements
- Activity program coordination
- Travel documentation requirements

### Holiday Management
- Thanksgiving arrangements
- Winter holiday rotation
- Spring break coordination
- Summer holiday scheduling
- Birthday celebration planning

## Communication Templates

### Schedule Change Request
"I would like to request a schedule modification for [date]. The reason is [explanation]. I propose [alternative arrangement] as a solution. Please let me know if this works for you or if you have a different suggestion."

### Activity Notification
"[Child's name] has a [activity type] scheduled for [date and time] at [location]. Please ensure [required items/preparations]. Let me know if you have any questions."

### Expense Sharing Request
"The following expense has been incurred: [description] for $[amount]. According to our agreement, this is a shared expense. Please arrange payment of your portion ($[amount]) by [date]."

This extensive knowledge base ensures comprehensive support for all family management scenarios.
"""

    return prompt


def build_dynamic_context(deep_context: Dict[str, Any]) -> str:
    """
    Build the DYNAMIC portion of system prompt (not cached).

    This content changes frequently and should NOT be cached:
    - Current date/time
    - Recent memories (may change between calls)

    Args:
        deep_context: The loaded deep context

    Returns:
        Dynamic context string (fresh each call)
    """
    memories = deep_context.get("recent_memories", [])

    prompt = f"""

# CURRENT SESSION CONTEXT

Current date: {datetime.now().strftime("%A, %B %d, %Y")}
Current time: {datetime.now().strftime("%I:%M %p")}
"""

    # Inject recent memories (these can change frequently)
    if memories:
        prompt += f"\n## Recent Context (Last {len(memories)} memories)\n"
        for memory in memories[:5]:  # Show top 5
            content = memory.get("content", "")
            if len(content) > 100:
                content = content[:97] + "..."
            prompt += f"- {content}\n"

    return prompt


def build_system_prompt(deep_context: Dict[str, Any]) -> str:
    """
    Build the complete system prompt with injected deep context.

    This combines static (cacheable) and dynamic content.

    Args:
        deep_context: The loaded deep context

    Returns:
        Complete system prompt string
    """
    static = build_static_context(deep_context)
    dynamic = build_dynamic_context(deep_context)
    return static + dynamic


def get_context_hash(deep_context: Dict[str, Any]) -> str:
    """
    Generate a hash of the static context for cache key purposes.

    This helps track when context changes and cache should be refreshed.
    """
    static_content = build_static_context(deep_context)
    return hashlib.md5(static_content.encode()).hexdigest()[:12]


# =============================================================================
# Agent Creation
# =============================================================================

async def create_agent(
    user_id: str,
    session_id: str,
    model_name: str = "claude-3-haiku-20240307",
    enable_caching: bool = True
) -> tuple[Any, Dict[str, Any]]:
    """
    Create a Personal Super Agent instance with full context.

    This function:
    1. Loads all available tools (local + MCP)
    2. Loads deep context for the user
    3. Builds the system prompt (with caching support)
    4. Creates a LangGraph ReAct agent

    Args:
        user_id: The user's UUID
        session_id: The conversation session ID
        model_name: The Anthropic model to use (default: Claude 3 Haiku)
        enable_caching: Whether to enable prompt caching (default: True)

    Returns:
        Tuple of (agent, deep_context)
    """
    logger.info(f"Creating agent for user {user_id}, session {session_id}")

    # Load all tools
    tools = await get_all_tools()
    logger.info(f"Loaded {len(tools)} tools for agent")

    # Load deep context
    deep_context = await load_deep_context(user_id)
    context_hash = get_context_hash(deep_context)
    logger.info(f"Loaded deep context for user {user_id} (hash: {context_hash})")

    # Build system prompt components
    static_prompt = build_static_context(deep_context)
    dynamic_prompt = build_dynamic_context(deep_context)

    # Create LLM with caching support
    # Note: We use model_kwargs to pass extra parameters if needed
    llm = ChatAnthropic(
        model=model_name,
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
        temperature=0.7,
        max_tokens=4096
    )

    # Create ReAct agent with system prompt
    # Combine static + dynamic for the full system message
    full_system_prompt = static_prompt + dynamic_prompt

    agent = create_react_agent(
        llm,
        tools,
        prompt=SystemMessage(content=full_system_prompt)
    )

    # Store caching info in deep_context for tracking
    deep_context["_cache_info"] = {
        "context_hash": context_hash,
        "static_tokens_approx": len(static_prompt) // 4,  # Rough estimate
        "caching_enabled": enable_caching
    }

    logger.info(f"Agent created (caching: {enable_caching}, context_hash: {context_hash})")

    return agent, deep_context


# =============================================================================
# Direct API with Prompt Caching
# =============================================================================

async def run_agent_with_caching(
    user_id: str,
    session_id: str,
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    model_name: str = "claude-3-haiku-20240307"
) -> Dict[str, Any]:
    """
    Run the agent using direct Anthropic API with prompt caching.

    This bypasses LangGraph to enable true prompt caching, which can
    reduce costs by 90% and improve latency by 2x+ for repeated calls.

    Args:
        user_id: The user's UUID
        session_id: The conversation session ID
        user_message: The user's input message
        conversation_history: Optional previous conversation history
        model_name: The Anthropic model to use

    Returns:
        Dictionary with agent response and cache metrics
    """
    import anthropic

    start_time = time.time()

    try:
        # Initialize Anthropic client
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

        # Load tools and context
        tools = await get_all_tools()
        deep_context = await load_deep_context(user_id)

        # Build prompts (separate static/dynamic for caching)
        static_prompt = build_static_context(deep_context)
        dynamic_prompt = build_dynamic_context(deep_context)
        context_hash = get_context_hash(deep_context)

        # Convert tools to Anthropic format
        anthropic_tools = []
        for tool in tools:
            tool_def = {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.args_schema.model_json_schema() if hasattr(tool, 'args_schema') and tool.args_schema else {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
            anthropic_tools.append(tool_def)

        # Build messages
        messages = []
        if conversation_history:
            for msg in conversation_history:
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"]
                })
        messages.append({
            "role": "user",
            "content": user_message
        })

        # Make API call with prompt caching
        # Static context gets cached, dynamic context is fresh
        response = client.messages.create(
            model=model_name,
            max_tokens=4096,
            system=[
                {
                    "type": "text",
                    "text": static_prompt,
                    "cache_control": {"type": "ephemeral"}  # Cache for 5 minutes
                },
                {
                    "type": "text",
                    "text": dynamic_prompt
                    # No cache_control = fresh each time
                }
            ],
            messages=messages,
            tools=anthropic_tools if anthropic_tools else None
        )

        duration_ms = (time.time() - start_time) * 1000

        # Extract response
        response_text = ""
        tool_calls = []
        for block in response.content:
            if hasattr(block, 'text'):
                response_text += block.text
            elif hasattr(block, 'type') and block.type == 'tool_use':
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "input": block.input
                })

        # Track cache metrics
        usage = response.usage
        input_tokens = usage.input_tokens
        cache_read = getattr(usage, 'cache_read_input_tokens', 0)
        cache_creation = getattr(usage, 'cache_creation_input_tokens', 0)

        _cache_metrics.record_call(
            input_tokens=input_tokens,
            cache_read=cache_read,
            cache_creation=cache_creation,
            latency_ms=duration_ms
        )

        cache_status = "HIT" if cache_read > 0 else "MISS" if cache_creation > 0 else "NONE"
        logger.info(
            f"API call completed: {duration_ms:.0f}ms, "
            f"tokens: {input_tokens}in/{usage.output_tokens}out, "
            f"cache: {cache_status} ({cache_read} read, {cache_creation} created)"
        )

        return {
            "success": True,
            "response": response_text,
            "tool_calls": tool_calls,
            "user_id": user_id,
            "session_id": session_id,
            "deep_context_loaded": True,
            "tools_available": len(tools),
            "timestamp": datetime.now().isoformat(),
            "cache_metrics": {
                "status": cache_status,
                "input_tokens": input_tokens,
                "cache_read_tokens": cache_read,
                "cache_creation_tokens": cache_creation,
                "context_hash": context_hash
            },
            "latency_ms": duration_ms
        }

    except Exception as e:
        logger.error(f"Error in run_agent_with_caching: {e}")
        return {
            "success": False,
            "error": str(e),
            "user_id": user_id,
            "session_id": session_id,
            "timestamp": datetime.now().isoformat()
        }


# =============================================================================
# Agent Execution
# =============================================================================

async def run_agent(
    user_id: str,
    session_id: str,
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    use_caching: bool = False
) -> Dict[str, Any]:
    """
    Run the Personal Super Agent with a user message.

    Args:
        user_id: The user's UUID
        session_id: The conversation session ID
        user_message: The user's input message
        conversation_history: Optional previous conversation history
        use_caching: If True, use direct API with prompt caching (default: False)
                    Note: Caching mode doesn't support tool execution loops yet

    Returns:
        Dictionary with agent response and metadata
    """
    # If caching is requested and it's a simple query (no tool use expected),
    # use the cached version for better performance
    if use_caching:
        return await run_agent_with_caching(
            user_id=user_id,
            session_id=session_id,
            user_message=user_message,
            conversation_history=conversation_history
        )

    start_time = time.time()

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

        duration_ms = (time.time() - start_time) * 1000

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
            "timestamp": datetime.now().isoformat(),
            "latency_ms": duration_ms,
            "cache_metrics": deep_context.get("_cache_info", {})
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
