# Railway Deployment Troubleshooting Guide

This guide helps diagnose and fix common Railway deployment issues for sabine_v1.

## Quick Health Check

Run the verification script to check deployment status:

```bash
python scripts/verify_railway_deployment.py
```

Or test a specific URL:

```bash
python scripts/verify_railway_deployment.py https://your-app.up.railway.app
```

## Common Issues & Solutions

### 1. Deployment Not Found / 404 Errors

**Symptoms:**
- URLs return 404
- Can't find deployment at expected URLs

**Solutions:**
1. **Check Railway Dashboard:**
   - Go to [railway.app](https://railway.app)
   - Find the `sabine-super-agent` project
   - Check deployment status in the dashboard

2. **Get Actual URL:**
   - In Railway project settings, go to "Domains"
   - Copy the actual public URL (may be different than expected)

3. **Verify Service is Running:**
   - Check the "Deployments" tab for build/runtime status
   - Look for any failed deployments

### 2. Connection Timeouts

**Symptoms:**
- Requests timeout after 30+ seconds
- Server seems to be starting but not responding

**Likely Causes:**
- Supervisor not starting services properly
- Port binding issues
- Environment variables missing

**Solutions:**

1. **Check Build Logs:**
   ```
   Railway Dashboard → Project → Deployments → View Logs
   ```
   Look for:
   - Python/Node.js installation errors
   - Missing dependencies
   - Environment variable errors

2. **Verify Environment Variables:**
   Required variables in Railway settings:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   SUPABASE_URL=https://...
   SUPABASE_SERVICE_ROLE_KEY=eyJhbGc...
   AGENT_API_KEY=your-secret-key
   GOOGLE_CLIENT_ID=...
   GOOGLE_CLIENT_SECRET=...
   USER_REFRESH_TOKEN=...
   AGENT_REFRESH_TOKEN=...
   ```

3. **Check Start Command:**
   Should be in `railway.json`:
   ```json
   {
     "deploy": {
       "startCommand": "/bin/bash -c '/app/setup-mcp-credentials.sh && /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf'"
     }
   }
   ```

### 3. Health Check Fails

**Symptoms:**
- Server responds but `/health` returns errors
- Tools not loading properly

**Solutions:**

1. **Check MCP Server Status:**
   - Test `/tools/diagnostics` endpoint
   - Verify MCP servers are starting

2. **Database Connection:**
   - Verify Supabase credentials
   - Check network connectivity to Supabase

3. **Tool Loading Issues:**
   - Check if Node.js dependencies installed
   - Verify MCP server scripts are executable

### 4. Build Failures

**Symptoms:**
- Deployment fails during build phase
- Docker build errors

**Solutions:**

1. **Check Dockerfile:**
   - Verify multi-stage build is working
   - Check Node.js installation step
   - Ensure all COPY commands have valid sources

2. **Dependencies:**
   - Check `requirements.txt` for Python deps
   - Verify npm packages install correctly
   - Look for version conflicts

3. **Local Testing:**
   ```bash
   # Test Docker build locally
   docker build -t sabine-test .
   docker run -p 8080:8080 sabine-test
   ```

### 5. Runtime Errors

**Symptoms:**
- Build succeeds but runtime fails
- Supervisor process issues

**Solutions:**

1. **Check Supervisor Config:**
   Verify `/deploy/supervisord.conf`:
   ```ini
   [program:python-api]
   command=python /app/run_server.py
   autostart=true
   autorestart=true
   ```

2. **Port Binding:**
   Railway sets `PORT` env var - ensure `run_server.py` uses it:
   ```python
   port = int(os.getenv("PORT", os.getenv("API_PORT", "8080")))
   ```

3. **Process Management:**
   - Check if supervisor starts both Python API and MCP servers
   - Verify process doesn't exit immediately

## Manual Recovery Steps

### Step 1: Force Redeploy
1. Go to Railway dashboard
2. Find latest deployment
3. Click "Redeploy" or trigger new deployment

### Step 2: Check Resource Usage
- Verify memory/CPU limits not exceeded
- Railway free tier has resource limits

### Step 3: Environment Reset
1. Double-check all environment variables
2. Regenerate API keys if needed
3. Test credentials locally first

### Step 4: Rollback if Needed
- If recent changes broke deployment
- Rollback to last known working commit
- Deploy from stable branch

## Monitoring & Maintenance

### Health Monitoring
Set up periodic health checks:
```bash
# Add to cron or Railway cron jobs
curl -f https://your-app.up.railway.app/health || echo "Health check failed"
```

### Log Monitoring
Check Railway logs regularly for:
- Memory usage warnings
- API errors
- MCP server connection issues

### Uptime Monitoring
Consider external monitoring services:
- UptimeRobot
- Pingdom  
- Railway built-in monitoring

## Getting Help

### Railway Support
- Railway Discord community
- Railway documentation
- Railway status page

### Debug Information to Collect
When asking for help, include:
1. Railway deployment URL
2. Build logs (if build failing)
3. Runtime logs (if runtime failing)
4. Environment variable checklist
5. Output from verification script

### Emergency Contacts
- Check Railway status page first
- Railway Discord for community help
- GitHub issues for code-related problems

## Prevention

### Best Practices
1. **Always test locally first**
2. **Use environment variable templates**
3. **Monitor deployment health regularly**
4. **Keep dependencies updated**
5. **Use Railway CLI for easier debugging**

### Automated Checks
Set up automated health checks in CI/CD:
```yaml
# In GitHub Actions
- name: Verify Railway Deployment
  run: python scripts/verify_railway_deployment.py ${{ secrets.RAILWAY_URL }}
```

This ensures deployments are verified automatically after each change.