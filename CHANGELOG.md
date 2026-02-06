# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Task cancellation states (`cancelled_failed`, `cancelled_in_progress`, `cancelled_other`) and approval metadata fields for the task queue.
- Manual requeue operation that resets tasks to `queued` across statuses.
- Tests for task approval metadata parsing and status handling.
- Migrations to extend task status constraints and add approval fields.

### Changed
- Cancel endpoint now accepts a JSON payload with `cancel_status` and `previous_status` metadata.
- Dependency validation treats cancelled tasks as failed dependencies.

## [0.2.0] - 2026-01-27

### Added
- Complete product documentation for Sabine personal assistant agent
  - `docs/product-vision-sabine.md` - Vision statement and philosophy
  - `docs/prd-sabine.md` - Complete product requirements
  - System role definitions for all team members (`docs/roles/`)
- MCP client testing and audit scripts
  - `test_mcp_connection.py` - Connection validation script
  - `test_uat_simulation.py` - UAT test simulation
  - `audit_mcp_client.py` - Automated security audit
- Comprehensive documentation
  - `MCP_FIX_SUMMARY.md` - Technical migration details
  - `IMPLEMENTATION_COMPLETE.md` - Deployment guide
  - `QA_SECURITY_AUDIT_REPORT.md` - Full audit report (16/16 passes)

### Changed
- **BREAKING**: MCP_SERVERS environment variable format changed
  - Old: `MCP_SERVERS="http://localhost:8000 http://localhost:8001"`
  - New: `MCP_SERVERS="workspace-mcp workspace-calendar:--config=/path"`
- **Backend**: Migrated MCP client transport from HTTP (SSE) to Stdio (stdin/stdout pipes)
  - Replaced `httpx.AsyncClient` with `mcp.client.stdio.StdioServerParameters` + `stdio_client`
  - Updated `lib/agent/mcp_client.py` (complete rewrite - 239 lines)
  - Updated `lib/agent/registry.py` (config format update)
- **API**: Function signatures for MCP client functions
  - `get_mcp_tools(command: str, args: List[str])` instead of `get_mcp_tools(url: str)`
  - `test_mcp_connection(command: str, args: List[str])` instead of `test_mcp_connection(url: str)`
- **Documentation**: System roles and responsibilities clarified for all team members

### Removed
- Removed deprecated `get_mcp_server_info()` function
- Removed `_parse_sse_response()` helper (not needed for Stdio protocol)
- Removed HTTP POST-based MCP communication

### Fixed
- **Critical**: MCP server connection timeout issues
  - Root cause: Python client was using HTTP POST + SSE while `workspace-mcp` server only provides Stdio transport
  - Solution: Switched to native Stdio transport using official MCP library
  - Result: Synchronous communication, zero latency added, proper error handling
- No hardcoded credentials in source code (all from environment variables)
- Proper error handling with 3-attempt retry logic and exponential backoff

### Security
- ✅ Security audit passed (16/16 checks)
- ✅ All credentials loaded via `os.getenv()` (no hardcoding)
- ✅ Proper exception handling and logging
- ✅ No sensitive data in log messages

## [0.1.0] - 2026-01-15

### Initial Release
- NextJS frontend with Twilio SMS webhook support
- Python FastAPI backend with LangGraph agent orchestration
- Supabase PostgreSQL + pgvector integration
- Google Workspace integration (Gmail, Calendar) via MCP
- Initial implementation of Sabine personal assistant agent

---

## Migration Guide (v0.1.0 → v0.2.0)

### Environment Variables
Update your MCP_SERVERS configuration:

```bash
# Before (HTTP-based - will NOT work)
export MCP_SERVERS="http://localhost:8000,http://localhost:8001"

# After (Stdio-based - correct)
export MCP_SERVERS="workspace-mcp workspace-calendar:--config=/etc/mcp/calendar.conf"
```

### Configuration Format
The new format supports command specifications with optional arguments:
- `workspace-mcp` - Simple command
- `workspace-mcp:--port:9000` - Command with arguments (colon-separated)
- `workspace-mcp:--transport:stdio:--config:/path/to/config` - Multiple arguments

### Testing the Migration
```bash
# Test MCP connection
python test_mcp_connection.py

# Run full UAT simulation
python test_uat_simulation.py

# Audit security
python audit_mcp_client.py
```

### Deployment
When deploying to production:

1. **Pre-flight checks** ✅ (completed)
   - TypeScript type checking: ✅ PASSED
   - ESLint: ✅ PASSED
   - Python imports: ✅ PASSED

2. **Environment variables** (must be set)
   ```bash
   export MCP_SERVERS="workspace-mcp"
   export USER_GOOGLE_EMAIL="your-email@company.com"
   export GOOGLE_REFRESH_TOKEN="<oauth-refresh-token>"
   export ANTHROPIC_API_KEY="<your-api-key>"
   ```

3. **Verification**
   ```bash
   # Monitor startup logs
   tail -f /var/log/sabine-agent.log | grep -i mcp
   
   # Should show:
   # "Connecting to MCP server: workspace-mcp"
   # "✓ Successfully loaded N tools from workspace-mcp"
   ```

---

## Known Issues

None at this time. For bug reports, see the repository's issue tracker.

## Contributing

See CONTRIBUTING.md for guidelines.
