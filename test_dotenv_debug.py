"""Debug dotenv loading"""
import os
from pathlib import Path
from dotenv import load_dotenv, dotenv_values

project_root = Path(__file__).parent
env_path = project_root / ".env"

print(f"Testing dotenv loading...\n")

# Method 1: load_dotenv
print("Method 1: load_dotenv()")
load_dotenv(dotenv_path=env_path, override=True)
key1 = os.getenv("ANTHROPIC_API_KEY")
print(f"  Result: {repr(key1)}")
print(f"  Length: {len(key1) if key1 else 0}\n")

# Method 2: dotenv_values (returns dict without modifying os.environ)
print("Method 2: dotenv_values()")
config = dotenv_values(env_path)
key2 = config.get("ANTHROPIC_API_KEY")
print(f"  Result: {repr(key2)}")
print(f"  Length: {len(key2) if key2 else 0}\n")

# Method 3: Read directly
print("Method 3: Read file directly")
with open(env_path, 'r') as f:
    for line in f:
        if line.startswith("ANTHROPIC_API_KEY="):
            direct_key = line.strip().split("=", 1)[1]
            print(f"  Result: {repr(direct_key)}")
            print(f"  Length: {len(direct_key)}\n")
            break

# Check if there's a .env.local
env_local = project_root / ".env.local"
print(f".env.local exists: {env_local.exists()}")
