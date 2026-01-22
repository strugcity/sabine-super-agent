# Agent Core (Python + LangGraph + MCP)

This directory contains the core agent orchestration system powered by LangGraph and enhanced with Model Context Protocol (MCP) support.

## Architecture Overview

The Personal Super Agent implements a hybrid architecture that combines:

1. **Local Skills** - Python modules in `/lib/skills`
2. **MCP Integrations** - External services via Model Context Protocol
3. **Deep Context Injection** - User-specific rules, schedules, and memories
4. **LangGraph State Machine** - Conversation flow management
5. **Dual-Brain Memory** - Vector store + Knowledge graph

## Files

### Core Modules

- **`core.py`** - Main orchestrator
  - Creates agent instances
  - Injects deep context
  - Manages conversation state
  - Runs LangGraph ReAct agent

- **`registry.py`** - Unified tool registry
  - Loads local Python skills from `/lib/skills`
  - Loads MCP tools from configured servers
  - Merges into unified tool list via `get_all_tools()`

- **`mcp_client.py`** - MCP integration client
  - Connects to MCP servers via SSE
  - Fetches remote tool definitions
  - Converts to LangChain StructuredTools
  - Handles connection errors gracefully

- **`__init__.py`** - Package exports
- **`example_usage.py`** - Example usage and testing

## Key Concepts

### 1. Deep Context Injection

Before processing any user query, the agent loads:
- **Active Rules**: Trigger conditions and actions from the database
- **Custody Schedule**: Current and upcoming custody periods
- **User Config**: Preferences and settings
- **Recent Memories**: Last 10 important memories

This context is injected into the system prompt, giving the agent full awareness of the user's situation.

### 2. Unified Tool Registry

The registry seamlessly merges tools from two sources:

```python
from lib.agent import get_all_tools

# This returns: [Local Skills] + [MCP Tools]
tools = await get_all_tools()
```

The agent doesn't know or care where tools come from - it just uses them.

### 3. Model Context Protocol (MCP)

MCP allows the agent to integrate with external services:
- Google Drive
- Calendar
- Slack
- GitHub
- Custom MCP servers

Configure MCP servers via environment variable:
```bash
MCP_SERVERS=https://gdrive-mcp.example.com/sse,https://calendar-mcp.example.com/sse
```

### 4. Dual-Brain Memory

- **Vector Store**: Fuzzy semantic search (Supabase pgvector)
  - Stores observations, notes, conversation snippets
  - Used for similarity search when context is needed

- **Knowledge Graph**: Strict relational logic (SQL tables)
  - Stores rules, custody schedules, user config
  - Used for deterministic lookups and triggers

## Usage

### Basic Agent Usage

```python
import asyncio
from lib.agent import run_agent

async def main():
    result = await run_agent(
        user_id="user-uuid-here",
        session_id="session-123",
        user_message="What's on my custody schedule this week?"
    )

    print(result["response"])

asyncio.run(main())
```

### With Conversation History

```python
conversation_history = [
    {"role": "user", "content": "Hello!"},
    {"role": "assistant", "content": "Hi! How can I help?"}
]

result = await run_agent(
    user_id="user-uuid",
    session_id="session-123",
    user_message="What did we just talk about?",
    conversation_history=conversation_history
)
```

### Loading Tools

```python
from lib.agent import get_all_tools, get_mcp_servers

# Get all available tools
tools = await get_all_tools()

print(f"Loaded {len(tools)} tools:")
for tool in tools:
    print(f"  - {tool.name}: {tool.description}")

# Check configured MCP servers
servers = get_mcp_servers()
print(f"\nMCP servers: {servers}")
```

### Loading Deep Context

```python
from lib.agent import load_deep_context

context = await load_deep_context("user-uuid")

print(f"Rules: {len(context['rules'])}")
print(f"Config: {context['user_config']}")
print(f"Custody: {context['custody_state']}")
```

## Environment Variables

Required:
- `ANTHROPIC_API_KEY` - Anthropic API key for Claude
- `SUPABASE_URL` - Supabase project URL
- `SUPABASE_SERVICE_ROLE_KEY` - Supabase service role key

Optional:
- `MCP_SERVERS` - Comma-separated list of MCP server URLs
- `OPENAI_API_KEY` - For embeddings and routing (if needed)

## Testing

Run the example usage script:

```bash
# Make sure you have a .env file with credentials
python lib/agent/example_usage.py
```

This will demonstrate:
1. Loading tools from local skills and MCP servers
2. Loading deep context for a user
3. Creating an agent instance
4. Running a conversation (optional)

## Adding Local Skills

Create a new skill in `/lib/skills/your_skill/`:

1. **manifest.json**
```json
{
  "name": "your_skill",
  "description": "What your skill does",
  "version": "1.0.0",
  "parameters": {
    "type": "object",
    "properties": {
      "param1": {
        "type": "string",
        "description": "Parameter description"
      }
    },
    "required": ["param1"]
  }
}
```

2. **handler.py**
```python
async def execute(params: dict) -> dict:
    """Execute the skill."""
    result = do_something(params)

    return {
        'status': 'success',
        'data': result
    }
```

The registry will automatically discover and load it.

## Adding MCP Servers

1. Set up an MCP server (or use an existing one)
2. Add the URL to your `.env`:
   ```bash
   MCP_SERVERS=https://your-mcp-server.com/sse
   ```
3. Restart the agent - tools will be automatically loaded

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     Personal Super Agent                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐         ┌──────────────┐                 │
│  │   core.py    │◄────────┤  registry.py │                 │
│  │              │         │              │                 │
│  │ - Creates    │         │ - Loads      │                 │
│  │   agent      │         │   local      │                 │
│  │ - Injects    │         │   skills     │                 │
│  │   context    │         │ - Loads MCP  │                 │
│  │ - Runs       │         │   tools      │                 │
│  │   LangGraph  │         │ - Merges all │                 │
│  └──────┬───────┘         └──────┬───────┘                 │
│         │                        │                          │
│         │                        │                          │
│         ▼                        ▼                          │
│  ┌──────────────────────────────────────┐                  │
│  │        Deep Context Loader           │                  │
│  │  - Rules, Custody, Config, Memories  │                  │
│  └──────────────┬───────────────────────┘                  │
│                 │                                           │
│                 ▼                                           │
│  ┌──────────────────────────────────────┐                  │
│  │         Supabase Database            │                  │
│  │  - Vector Store (pgvector)           │                  │
│  │  - Knowledge Graph (SQL)             │                  │
│  └──────────────────────────────────────┘                  │
│                                                              │
└─────────────────────────────────────────────────────────────┘
                         │
                         │
                         ▼
              ┌──────────────────┐
              │  Claude 3.5      │
              │  Sonnet          │
              │  (Anthropic)     │
              └──────────────────┘
```

## Next Steps

1. ✅ Agent core implemented
2. ✅ MCP integration ready
3. ✅ Deep context injection working
4. 🔄 Add Twilio webhooks (Next.js API routes)
5. 🔄 Implement memory storage
6. 🔄 Add voice transcription (Whisper)
7. 🔄 Deploy to Vercel
