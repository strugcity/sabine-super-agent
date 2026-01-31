"""Test if .env loads correctly"""
import os
from pathlib import Path
from dotenv import load_dotenv

project_root = Path(__file__).parent
env_path = project_root / ".env"

print(f"Project root: {project_root}")
print(f"Env path: {env_path}")
print(f"Env exists: {env_path.exists()}")

# Load env
load_dotenv(dotenv_path=env_path)

# Check key
api_key = os.getenv("ANTHROPIC_API_KEY")
print(f"\nANTHROPIC_API_KEY value: {repr(api_key)}")
print(f"API key type: {type(api_key)}")
print(f"API key is not None: {api_key is not None}")
print(f"API key truthy: {bool(api_key)}")
if api_key:
    print(f"Key starts with: {api_key[:20]}...")
    print(f"Key length: {len(api_key)}")
else:
    print("ANTHROPIC_API_KEY is None or empty")

# Check other vars
print(f"\nAPI_PORT: {os.getenv('API_PORT')}")
print(f"MCP_SERVERS: {os.getenv('MCP_SERVERS')}")
