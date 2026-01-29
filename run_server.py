#!/usr/bin/env python3
"""
Start the FastAPI server with correct Python path.

This ensures lib module can be imported correctly.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Now we can import and run the server
if __name__ == "__main__":
    import uvicorn

    # Load environment variables
    from dotenv import load_dotenv
    import os

    env_path = project_root / ".env"
    load_dotenv(dotenv_path=env_path, override=True)

    # Get configuration
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("PORT") or os.getenv("API_PORT", "8001"))
    reload = os.getenv("UVICORN_RELOAD", "false").lower() == "true"

    print(f"Starting server on {host}:{port}")
    print(f"Project root: {project_root}")

    # Run server
    uvicorn.run(
        "lib.agent.server:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info"
    )
