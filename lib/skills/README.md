# Skill Registry

The Skill Registry is a core architectural pattern for the Personal Super Agent.
It enables dynamic tool loading without hardcoding capabilities into the agent.

## How It Works

1. Each skill lives in its own subdirectory (e.g., `/weather`, `/custody`)
2. Each skill requires two files:
   - `manifest.json` - Skill metadata and configuration
   - `handler.py` - Skill implementation

3. The agent scans this directory at startup to discover available skills
4. Skills are registered dynamically and made available to the LLM

## Skill Structure

```
/lib/skills/
├── __init__.py          # Skill registry loader
├── weather/             # Example skill
│   ├── manifest.json    # Skill metadata
│   └── handler.py       # Skill implementation
└── custody/             # Example skill
    ├── manifest.json    # Skill metadata
    └── handler.py       # Skill implementation
```

## manifest.json Schema

```json
{
  "name": "skill_name",
  "description": "What this skill does",
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

## handler.py Interface

```python
async def execute(params: dict) -> dict:
    """
    Execute the skill with the given parameters.

    Args:
        params: Dictionary matching the manifest.json schema

    Returns:
        Dictionary with the skill execution results
    """
    pass
```
