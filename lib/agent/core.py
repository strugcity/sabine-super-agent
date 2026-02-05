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

import pytz

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.prebuilt import create_react_agent
from supabase import create_client, Client

from .registry import get_all_tools
from .models import RoleManifest
from .model_router import get_model_router, RoutingDecision
from .llm_config import ModelProvider
from .providers import get_provider

logger = logging.getLogger(__name__)

# =============================================================================
# Timezone Configuration
# =============================================================================

# User's timezone - US Central (consistent with other components)
SCHEDULER_TIMEZONE = os.getenv("SCHEDULER_TIMEZONE", "America/Chicago")
USER_TIMEZONE = pytz.timezone(SCHEDULER_TIMEZONE)


# =============================================================================
# Role-Based Persona Loading
# =============================================================================

# Cache for loaded role manifests (avoid re-reading files)
_role_manifest_cache: Dict[str, RoleManifest] = {}

# Path to role definition files
ROLES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "docs", "roles")


def load_role_manifest(role_id: str) -> Optional[RoleManifest]:
    """
    Load a role manifest from docs/roles/{role_id}.md.

    Role manifests define specialized agent personas with specific skills,
    responsibilities, and instructions. The markdown file content becomes
    the agent's system prompt prefix.

    Args:
        role_id: The role identifier (e.g., "backend-architect-sabine", "SABINE_ARCHITECT")

    Returns:
        RoleManifest if found, None otherwise

    Example:
        manifest = load_role_manifest("backend-architect-sabine")
        # Returns RoleManifest with title="Lead Python & Systems Engineer"
    """
    # Check cache first
    if role_id in _role_manifest_cache:
        logger.debug(f"Role manifest cache hit: {role_id}")
        return _role_manifest_cache[role_id]

    # Build file path
    role_file = os.path.join(ROLES_DIR, f"{role_id}.md")

    if not os.path.exists(role_file):
        logger.warning(f"Role file not found: {role_file}")
        return None

    try:
        with open(role_file, "r", encoding="utf-8") as f:
            content = f.read()

        # Extract title from first lines
        # Format 1: "# SYSTEM ROLE: backend-architect-sabine" + "**Identity:** You are the Lead..."
        # Format 2: "# ROLE: Senior Agentic Architect (Sabine 2.0)"
        title = role_id  # Default to role_id if we can't extract
        lines = content.split("\n")

        for line in lines:
            # Check for Identity line (Format 1)
            if line.startswith("**Identity:**"):
                # Extract role title from "**Identity:** You are the Lead Python & Systems Engineer..."
                identity_text = line.replace("**Identity:**", "").strip()
                # Try to extract the title part before "for Project"
                if " for " in identity_text:
                    title = identity_text.split(" for ")[0].replace("You are the ", "").strip()
                else:
                    title = identity_text.replace("You are the ", "").strip()
                break
            # Check for Role header (Format 2)
            elif line.startswith("# ROLE:"):
                title = line.replace("# ROLE:", "").strip()
                break
            elif line.startswith("# SYSTEM ROLE:"):
                # Continue looking for Identity line
                continue

        manifest = RoleManifest(
            role_id=role_id,
            title=title,
            instructions=content,
            allowed_tools=[],  # Future: parse from file or config
            model_preference=None  # Future: parse from file or config
        )

        # Cache the manifest
        _role_manifest_cache[role_id] = manifest
        logger.info(f"Loaded role manifest: {role_id} ({title})")

        return manifest

    except Exception as e:
        logger.error(f"Error loading role manifest {role_id}: {e}")
        return None


def get_available_roles() -> List[str]:
    """
    List all available role IDs from docs/roles/*.md files.

    Returns:
        List of role IDs (without .md extension)
    """
    if not os.path.exists(ROLES_DIR):
        logger.warning(f"Roles directory not found: {ROLES_DIR}")
        return []

    roles = []
    for filename in os.listdir(ROLES_DIR):
        if filename.endswith(".md"):
            role_id = filename[:-3]  # Remove .md extension
            roles.append(role_id)

    return sorted(roles)


def clear_role_manifest_cache():
    """Clear the role manifest cache (useful for development/testing)."""
    global _role_manifest_cache
    _role_manifest_cache = {}


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


def build_static_context(deep_context: Dict[str, Any], role: Optional[str] = None) -> str:
    """
    Build the STATIC portion of system prompt (cacheable).

    This content changes infrequently and benefits from prompt caching:
    - Role-specific identity (if role provided)
    - Agent identity and capabilities
    - User rules and triggers
    - Custody schedule
    - User preferences
    - Tool usage instructions

    Args:
        deep_context: The loaded deep context
        role: Optional role ID to load specific persona (e.g., "backend-architect-sabine")

    Returns:
        Static context string (to be cached)
    """
    user_id = deep_context.get("user_id", "unknown")
    user_email = os.getenv("USER_GOOGLE_EMAIL", "sabine@strugcity.com")
    rules = deep_context.get("rules", [])
    custody_state = deep_context.get("custody_state", {})
    user_config = deep_context.get("user_config", {})

    # Start with role-specific instructions if a role is provided
    prompt = ""
    role_manifest = None
    if role:
        role_manifest = load_role_manifest(role)
        if role_manifest:
            prompt += f"""# ROLE-SPECIFIC INSTRUCTIONS

{role_manifest.instructions}

---
# SABINE CORE CAPABILITIES (Available to all roles)
---

"""
            logger.info(f"Injected role instructions for: {role} ({role_manifest.title})")
        else:
            logger.warning(f"Role '{role}' not found, using default identity")

    prompt += f"""You are the Personal Super Agent, an AI assistant specialized in managing family logistics, complex tasks, and deep contextual information.

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
- **get_calendar_events**: CRITICAL - Use this for ALL calendar/schedule questions!
  - Parameters for time_range:
    * "today", "tomorrow" - single day queries
    * "this_weekend", "next_weekend" - returns ONLY Saturday and Sunday
    * "this_week", "next_week" - full week
    * "custom" - for SPECIFIC DATES (e.g., "weekend of 2/13", "February 13-15")
  - For SPECIFIC DATE queries, use time_range="custom" with start_date and end_date in YYYY-MM-DD format
    Example: time_range="custom", start_date="2026-02-13", end_date="2026-02-15"
  - Optional: family_member ("Jack", "Anna") to filter by person
  - Optional: group_by ("day", "member") for different views
  - This tool knows: custody schedule (Mom/Dad days), all sports calendars (GameChanger, SportsEngine, TeamSnap), family events
  - ALWAYS use this tool - NEVER make up calendar data!
- **get_weather**: Get weather forecasts and conditions
- **Memory Management**: Store and retrieve important information

## Reminder System

You have a complete reminder system to help users stay on top of tasks and appointments:

### SMS/Email Reminders (Standalone)
Use these for quick personal reminders that don't need a calendar event:
- **create_reminder**: Create a scheduled reminder
  - Required: title, scheduled_time (ISO format: YYYY-MM-DDTHH:MM:SS)
  - Optional: description, reminder_type (sms/email/slack), repeat_pattern (daily/weekly/monthly/yearly)
  - Example: "Remind me at 10 AM tomorrow to pick up glasses"
  - Example: "Remind me every Sunday at 4 PM to post the baseball video" (weekly recurring)

- **list_reminders**: Show active reminders
  - Parameters: include_completed (bool), limit (int)
  - Always use this when user asks "what reminders do I have?" or similar

- **cancel_reminder**: Cancel a reminder by ID or search term
  - Can cancel by exact reminder_id OR by searching title with search_term
  - Example: "Cancel the glasses reminder" → uses search_term="glasses"

### Calendar Events (Google Calendar)
Use these when the user wants an appointment/event on their calendar:
- **create_calendar_event**: Create a Google Calendar event with reminders
  - Required: title, start_time
  - Optional: end_time, description, location, reminder_minutes (default 15)
  - Optional: also_sms_reminder (bool) - ALSO sends SMS before the event
  - Example: "Add a dentist appointment tomorrow at 2 PM"
  - Example: "Add my flight at 6 AM and text me 2 hours before" (hybrid mode)

### When to Use Which:

**Use create_reminder (SMS/Email) for:**
- Quick personal reminders: "remind me to call mom"
- Tasks without a specific duration: "remind me about the dry cleaning"
- Recurring personal tasks: "remind me every week to water the plants"
- Things that don't belong on a calendar

**Use create_calendar_event for:**
- Appointments with time blocks: "dentist at 2pm for 1 hour"
- Meetings with specific durations
- Events others might need to see
- Things that should appear on Google Calendar
- When user explicitly says "add to calendar" or "schedule"

**Use BOTH (hybrid) for:**
- Critical appointments: "add my flight and text me 2 hours before"
- Important meetings you can't miss
- Set also_sms_reminder=true with create_calendar_event

### Example Conversations:

User: "Remind me at 3pm to take my medicine"
→ Use create_reminder (simple personal reminder, no calendar needed)

User: "Add a meeting with John tomorrow at 10am"
→ Use create_calendar_event (it's an appointment for the calendar)

User: "What reminders do I have?"
→ Use list_reminders

User: "Cancel my reminder about the glasses"
→ Use cancel_reminder with search_term="glasses"

User: "Schedule my dentist for Tuesday at 2pm and make sure to remind me"
→ Use create_calendar_event with reminder_minutes=60

User: "I have a flight at 6am, put it on my calendar and text me 2 hours before"
→ Use create_calendar_event with also_sms_reminder=true, sms_reminder_minutes=120

**MANDATORY RULE:** For ANY question about schedules, events, calendars, custody, "what's on", "who has what", or time-related queries, you MUST call `get_calendar_events` first. Never guess or fabricate calendar information.

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
    - Current date/time (in user's timezone)
    - Recent memories (may change between calls)

    Args:
        deep_context: The loaded deep context

    Returns:
        Dynamic context string (fresh each call)
    """
    memories = deep_context.get("recent_memories", [])

    # Get current time in user's timezone (US Central)
    now_utc = datetime.now(pytz.UTC)
    now_local = now_utc.astimezone(USER_TIMEZONE)

    prompt = f"""

# CURRENT SESSION CONTEXT

**Timezone: US Central ({SCHEDULER_TIMEZONE})**
Current date: {now_local.strftime("%A, %B %d, %Y")}
Current time: {now_local.strftime("%I:%M %p %Z")}
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
    model_name: str = None,  # Now optional - router decides if not specified
    enable_caching: bool = True,
    role: Optional[str] = None,
    use_hybrid_routing: bool = True,  # Enable hybrid LLM routing
    task_payload: Optional[Dict[str, Any]] = None,  # For complexity analysis
) -> tuple[Any, Dict[str, Any]]:
    """
    Create a Personal Super Agent instance with intelligent model routing.

    This function:
    1. Loads all available tools (local + MCP)
    2. Loads deep context for the user
    3. Loads role-specific persona if provided
    4. Routes to appropriate model tier (if hybrid routing enabled)
    5. Builds the system prompt (with caching support for Anthropic)
    6. Creates a LangGraph ReAct agent

    Args:
        user_id: The user's UUID
        session_id: The conversation session ID
        model_name: Override model (default: None, let router decide)
        enable_caching: Whether to enable prompt caching (default: True)
        role: Optional role ID for specialized persona (e.g., "backend-architect-sabine")
        use_hybrid_routing: Whether to use hybrid LLM routing (default: True)
        task_payload: Optional task payload for complexity analysis

    Returns:
        Tuple of (agent, deep_context)
    """
    role_info = f", role={role}" if role else ""
    logger.info(f"Creating agent for user {user_id}, session {session_id}{role_info}")

    # Load all tools
    tools = await get_all_tools()
    logger.info(f"Loaded {len(tools)} tools for agent")
    # Log tool names for debugging
    tool_names = [t.name for t in tools]
    logger.info(f"Tool names: {tool_names}")

    # Determine tool requirements
    requires_tools = len(tools) > 0

    # Load deep context
    deep_context = await load_deep_context(user_id)
    context_hash = get_context_hash(deep_context)
    logger.info(f"Loaded deep context for user {user_id} (hash: {context_hash})")

    # Store role in deep_context for tracking
    role_manifest = None
    if role:
        deep_context["_role"] = role
        role_manifest = load_role_manifest(role)
        if role_manifest:
            deep_context["_role_title"] = role_manifest.title

    # =========================================================================
    # Model Routing
    # =========================================================================
    if use_hybrid_routing and model_name is None:
        # Use intelligent model routing based on role and task
        router = get_model_router()
        routing_decision = router.route(
            role=role,
            role_manifest=role_manifest,
            task_payload=task_payload,
            requires_tools=requires_tools,
        )

        model_config = routing_decision.model_config
        selected_model = model_config.model_id
        selected_provider = model_config.provider

        logger.info(
            f"Model routing: {model_config.display_name} "
            f"(tier={routing_decision.tier.value}, reason={routing_decision.reason})"
        )

        # Store routing info in deep_context
        deep_context["_routing"] = {
            "model": selected_model,
            "model_key": next(
                (k for k, v in __import__('lib.agent.llm_config', fromlist=['MODEL_REGISTRY']).MODEL_REGISTRY.items()
                 if v.model_id == selected_model),
                None
            ),
            "provider": selected_provider.value,
            "tier": routing_decision.tier.value,
            "reason": routing_decision.reason,
            "fallback_chain": routing_decision.fallback_chain,
        }

        # Create LLM using provider adapter
        provider = get_provider(selected_provider)
        max_tokens = model_config.max_tokens

        llm = provider.create_llm(
            config=model_config,
            temperature=0.7,
            max_tokens=max_tokens,
        )

        # Prompt caching only works with Anthropic
        caching_enabled = enable_caching and selected_provider == ModelProvider.ANTHROPIC

    else:
        # Use legacy behavior: explicit model_name or default to Claude Sonnet
        if model_name is None:
            model_name = "claude-sonnet-4-20250514"

        selected_provider = ModelProvider.ANTHROPIC
        logger.info(f"Using explicit model: {model_name} (hybrid routing disabled)")

        deep_context["_routing"] = {
            "model": model_name,
            "provider": "anthropic",
            "tier": "premium",
            "reason": "Explicit model_name or hybrid routing disabled",
            "fallback_chain": ["claude-sonnet"],
        }

        llm = ChatAnthropic(
            model=model_name,
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            temperature=0.7,
            max_tokens=4096
        )

        caching_enabled = enable_caching

    # Build system prompt components (with role injection if provided)
    static_prompt = build_static_context(deep_context, role=role)
    dynamic_prompt = build_dynamic_context(deep_context)

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
        "caching_enabled": caching_enabled,
        "caching_note": "Prompt caching only available with Anthropic provider" if not caching_enabled and enable_caching else None,
    }

    provider_info = deep_context.get("_routing", {}).get("provider", "anthropic")
    tier_info = deep_context.get("_routing", {}).get("tier", "premium")
    logger.info(
        f"Agent created (provider: {provider_info}, tier: {tier_info}, "
        f"caching: {caching_enabled}, context_hash: {context_hash})"
    )

    return agent, deep_context


# =============================================================================
# Direct API with Prompt Caching
# =============================================================================

async def run_agent_with_caching(
    user_id: str,
    session_id: str,
    user_message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    model_name: str = "claude-sonnet-4-20250514"
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
        logger.error(f"Error in run_agent_with_caching: {e}", exc_info=True)

        # Classify the error for better handling
        error_type = "unknown"
        error_category = "internal"
        http_status = None

        error_str = str(e).lower()
        error_class = type(e).__name__

        # Check for API-related errors (LLM, external services)
        if "rate" in error_str and "limit" in error_str:
            error_type = "rate_limited"
            error_category = "external_service"
            http_status = 429
        elif "401" in error_str or "unauthorized" in error_str or "authentication" in error_str:
            error_type = "auth_failed"
            error_category = "authentication"
            http_status = 401
        elif "403" in error_str or "forbidden" in error_str or "permission" in error_str:
            error_type = "permission_denied"
            error_category = "authorization"
            http_status = 403
        elif "404" in error_str or "not found" in error_str:
            error_type = "not_found"
            error_category = "validation"
            http_status = 404
        elif "timeout" in error_str or "timed out" in error_str:
            error_type = "timeout"
            error_category = "external_service"
            http_status = 504
        elif "connection" in error_str or "network" in error_str:
            error_type = "network_error"
            error_category = "external_service"
            http_status = 502
        elif "validation" in error_str or "invalid" in error_str:
            error_type = "validation_error"
            error_category = "validation"
            http_status = 400

        return {
            "success": False,
            "error": str(e),
            "error_type": error_type,
            "error_category": error_category,
            "error_class": error_class,
            "http_status": http_status,
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
    use_caching: bool = False,
    role: Optional[str] = None
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
        role: Optional role ID for specialized persona (e.g., "backend-architect-sabine")

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
        # Create agent (with optional role for specialized persona)
        agent, deep_context = await create_agent(user_id, session_id, role=role)

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

        # Extract tool execution details from agent messages
        agent_messages = result.get("messages", [])
        logger.info(f"Agent returned {len(agent_messages)} messages")

        # Track all tool calls and their results
        tool_executions = []
        tool_calls_detected = 0
        tool_successes = 0
        tool_failures = 0

        for i, msg in enumerate(agent_messages):
            msg_type = type(msg).__name__
            content_preview = ""

            # Check for ToolMessage (tool results)
            if msg_type == "ToolMessage":
                tool_name = getattr(msg, 'name', 'unknown')
                tool_content = msg.content if hasattr(msg, 'content') else None

                # Parse tool result to determine success/failure
                tool_status = "unknown"
                tool_error = None
                artifact_created = None

                if tool_content:
                    # Try to parse as JSON to extract status
                    try:
                        import json
                        if isinstance(tool_content, str):
                            result_data = json.loads(tool_content)
                        elif isinstance(tool_content, dict):
                            result_data = tool_content
                        else:
                            result_data = {}

                        # Check for status field (github_issues, run_python_sandbox, etc.)
                        if "status" in result_data:
                            tool_status = result_data["status"]
                            if tool_status == "success":
                                tool_successes += 1
                                # Extract artifact info if available
                                if "file" in result_data:
                                    artifact_created = result_data["file"].get("path") or result_data["file"].get("url")
                                elif "issue" in result_data:
                                    artifact_created = f"Issue #{result_data['issue'].get('number')}"
                                elif "commit" in result_data:
                                    artifact_created = f"Commit {result_data['commit'].get('sha', '')[:7]}"
                            elif tool_status == "error":
                                tool_failures += 1
                                tool_error = result_data.get("error", "Unknown error")

                        # Check for error field without status (some tools)
                        elif "error" in result_data:
                            tool_status = "error"
                            tool_failures += 1
                            tool_error = result_data["error"]

                        # Check for success indicators
                        elif "success" in result_data:
                            tool_status = "success" if result_data["success"] else "error"
                            if tool_status == "success":
                                tool_successes += 1
                            else:
                                tool_failures += 1
                                tool_error = result_data.get("error", "Operation failed")

                        else:
                            # Assume success if no error indicators
                            tool_status = "success"
                            tool_successes += 1

                    except (json.JSONDecodeError, TypeError):
                        # If not JSON, check for error patterns in string
                        content_str = str(tool_content).lower()
                        if "error" in content_str or "failed" in content_str or "exception" in content_str:
                            tool_status = "error"
                            tool_failures += 1
                            tool_error = str(tool_content)[:200]
                        else:
                            tool_status = "success"
                            tool_successes += 1

                tool_executions.append({
                    "type": "tool_result",
                    "tool_name": tool_name,
                    "tool_call_id": getattr(msg, 'tool_call_id', None),
                    "status": tool_status,
                    "error": tool_error,
                    "artifact_created": artifact_created,
                    "content_preview": str(tool_content)[:500] if tool_content else None
                })
                status_indicator = "OK" if tool_status == "success" else "FAIL"
                content_preview = f"[TOOL_RESULT: {tool_name} - {status_indicator}]"

            elif hasattr(msg, 'content'):
                if isinstance(msg.content, str):
                    content_preview = msg.content[:100]
                elif isinstance(msg.content, list):
                    # Check for tool_use blocks in AIMessage
                    for block in msg.content:
                        if isinstance(block, dict) and block.get('type') == 'tool_use':
                            tool_calls_detected += 1
                            tool_name = block.get('name', 'unknown')
                            tool_executions.append({
                                "type": "tool_call",
                                "tool_name": tool_name,
                                "tool_call_id": block.get('id'),
                                "input_preview": str(block.get('input', {}))[:200]
                            })
                            content_preview = f"[TOOL_USE: {tool_name}]"
                    if not content_preview:
                        content_preview = f"[list with {len(msg.content)} items]"
                else:
                    content_preview = str(msg.content)[:100]

            logger.info(f"  Message {i}: [{msg_type}] {content_preview}")

        # Summarize tool executions
        tool_names_used = list(set(t['tool_name'] for t in tool_executions if t['type'] == 'tool_call'))
        artifacts_created = [t['artifact_created'] for t in tool_executions if t.get('artifact_created')]
        failed_tools = [t for t in tool_executions if t.get('status') == 'error']

        logger.info(f"Tool calls detected: {tool_calls_detected}, Tools used: {tool_names_used}")
        logger.info(f"Tool results: {tool_successes} succeeded, {tool_failures} failed")
        if artifacts_created:
            logger.info(f"Artifacts created: {artifacts_created}")
        if failed_tools:
            logger.warning(f"Failed tool calls: {[(t['tool_name'], t.get('error')) for t in failed_tools]}")

        # === PERSISTENT AUDIT LOGGING ===
        # Log all tool executions to database for debugging and compliance
        if tool_executions:
            try:
                from backend.services.audit_logging import log_tool_executions_batch
                logged_count = await log_tool_executions_batch(
                    executions=tool_executions,
                    user_id=user_id,
                    agent_role=role,
                )
                logger.info(f"Audit logging: {logged_count} tool executions logged to database")
            except ImportError:
                logger.debug("Audit logging service not available - skipping persistent logging")
            except Exception as e:
                # Don't let audit logging failures break the main flow
                logger.warning(f"Audit logging failed (non-fatal): {e}")

        # Extract response
        if agent_messages:
            last_message = agent_messages[-1]
            response_text = last_message.content if hasattr(last_message, "content") else str(last_message)
        else:
            response_text = "I apologize, but I couldn't generate a response."

        response_data = {
            "success": True,
            "response": response_text,
            "user_id": user_id,
            "session_id": session_id,
            "deep_context_loaded": True,
            "tools_available": len(await get_all_tools()),
            "timestamp": datetime.now().isoformat(),
            "latency_ms": duration_ms,
            "cache_metrics": deep_context.get("_cache_info", {}),
            # Tool execution tracking for verification
            "tool_execution": {
                "tools_called": tool_names_used,
                "call_count": tool_calls_detected,
                "success_count": tool_successes,
                "failure_count": tool_failures,
                "artifacts_created": artifacts_created,
                "all_succeeded": tool_failures == 0 and tool_successes > 0,
                "executions": tool_executions
            }
        }

        # Include role info in response if a role was used
        if role:
            response_data["role"] = deep_context.get("_role")
            response_data["role_title"] = deep_context.get("_role_title")

        return response_data

    except Exception as e:
        logger.error(f"Error running agent: {e}", exc_info=True)

        # Classify the error for better handling
        error_type = "unknown"
        error_category = "internal"
        http_status = None

        error_str = str(e).lower()
        error_class = type(e).__name__

        # Check for API-related errors (LLM, external services)
        if "rate" in error_str and "limit" in error_str:
            error_type = "rate_limited"
            error_category = "external_service"
            http_status = 429
        elif "401" in error_str or "unauthorized" in error_str or "authentication" in error_str:
            error_type = "auth_failed"
            error_category = "authentication"
            http_status = 401
        elif "403" in error_str or "forbidden" in error_str or "permission" in error_str:
            error_type = "permission_denied"
            error_category = "authorization"
            http_status = 403
        elif "404" in error_str or "not found" in error_str:
            error_type = "not_found"
            error_category = "validation"
            http_status = 404
        elif "timeout" in error_str or "timed out" in error_str:
            error_type = "timeout"
            error_category = "external_service"
            http_status = 504
        elif "connection" in error_str or "network" in error_str:
            error_type = "network_error"
            error_category = "external_service"
            http_status = 502
        elif "validation" in error_str or "invalid" in error_str:
            error_type = "validation_error"
            error_category = "validation"
            http_status = 400

        return {
            "success": False,
            "error": str(e),
            "error_type": error_type,
            "error_category": error_category,
            "error_class": error_class,
            "http_status": http_status,
            "user_id": user_id,
            "session_id": session_id,
            "role": role,
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
