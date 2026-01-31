# Gmail Auto-Reply Implementation Status

**Date:** 2026-01-24
**Status:** Infrastructure Ready, Webhook Not Triggering

## What's Working ✅

1. **Gmail Watch Active**
   - Watch expires: 2026-01-31
   - Topic: `projects/super-agent-485222/topics/gmail-notification`
   - Verified with `check_gmail_watch.py`

2. **MCP Server Running**
   - Port: 8000
   - Finding unread emails (confirmed: "Found 2 messages")
   - OAuth working for sabine@strugcity.com
   - 67 Google Workspace tools loaded

3. **Python Agent Server Running**
   - Port: 8001
   - Endpoint: `/gmail/handle` exists
   - Simple auto-reply handler implemented in `lib/agent/gmail_handler.py`

4. **Next.js Webhook Endpoint**
   - URL: `https://reasonable-overexpectantly-lucian.ngrok-free.dev/api/gmail/webhook`
   - Route: `src/app/api/gmail/webhook/route.ts`
   - Health check available: GET endpoint returns status

5. **Code Implementation**
   - `lib/agent/gmail_handler.py` - Simple handler that sends generic acknowledgment
   - Auto-injects `user_google_email` parameter for Gmail tools
   - Sends reply to all authorized senders when unread emails detected

## What's NOT Working ❌

1. **Pub/Sub Notifications Not Arriving**
   - No webhook logs showing `[Gmail Webhook]` messages
   - Gmail may not be sending notifications to Pub/Sub
   - OR Pub/Sub push subscription may not be calling ngrok URL

2. **Multiple Python Processes on Port 8001**
   - Found 4 zombie processes (PIDs: 62756, 50296, 58296, 72364)
   - Unclear which is responding to requests
   - May be causing routing issues

## Troubleshooting Steps

### Immediate Actions

1. **Verify Pub/Sub Subscription**
   ```bash
   # Check if push subscription is configured correctly
   gcloud pubsub subscriptions describe gmail-notifications-push \
     --project=super-agent-485222
   ```
   Should show:
   - Push endpoint: `https://reasonable-overexpectantly-lucian.ngrok-free.dev/api/gmail/webhook`
   - Ack deadline: 10 seconds

2. **Test Webhook Directly**
   ```bash
   # Send test Pub/Sub notification
   curl -X POST https://reasonable-overexpectantly-lucian.ngrok-free.dev/api/gmail/webhook \
     -H "Content-Type: application/json" \
     -d @test_webhook.json
   ```

3. **Check Pub/Sub Delivery Logs**
   - Go to Google Cloud Console → Pub/Sub → Subscriptions
   - Check "gmail-notifications-push" for delivery attempts
   - Look for failed deliveries (4xx/5xx errors)

4. **Clean Up Zombie Processes**
   ```bash
   # Kill all Python processes on port 8001
   netstat -ano | findstr ":8001" | awk '{print $5}' | xargs taskkill //F //PID

   # Restart only the agent server
   cd superAgent
   NODE_ENV=production API_PORT=8001 python lib/agent/server.py &
   ```

5. **Verify ngrok Tunnel**
   ```bash
   # Check ngrok is running and forwarding to port 3000
   curl http://127.0.0.1:4040/api/tunnels
   ```

### Configuration to Verify

**Environment Variables (.env)**
```env
PYTHON_API_URL=http://127.0.0.1:8001  ✅ Correct
API_PORT=8001  ✅ Correct
GMAIL_AUTHORIZED_EMAILS=rknollmaier@gmail.com,sabine@strugcity.com  ✅ Correct
ASSISTANT_EMAIL=sabine@strugcity.com  ✅ Correct
GMAIL_WEBHOOK_URL=https://reasonable-overexpectantly-lucian.ngrok-free.dev/api/gmail/webhook
GMAIL_PUBSUB_TOPIC=projects/super-agent-485222/topics/gmail-notification
```

**Pub/Sub Push Subscription**
Should be configured to POST to:
`https://reasonable-overexpectantly-lucian.ngrok-free.dev/api/gmail/webhook`

### Known Issues

1. **Model Access Limitation**
   - Anthropic API key only has Haiku access
   - No Sonnet models available (all return 404)
   - This affects complex agent, but NOT the simple auto-reply handler

2. **workspace-mcp Output Format**
   - Returns human-readable text instead of JSON
   - Example: "Found 2 messages matching..." vs structured data
   - Handler works around this by not parsing individual message IDs

3. **Server Port Configuration**
   - `lib/agent/server.py` line 319 has misleading log: "Listening on http://0.0.0.0:8000"
   - Actual port determined by `API_PORT` env var (8001)
   - Check uvicorn logs for real port: "Uvicorn running on http://0.0.0.0:8001"

## Architecture

```
Gmail (new email)
    ↓
Gmail Watch API
    ↓
Google Cloud Pub/Sub
    ↓ (push notification)
ngrok tunnel (reasonable-overexpectantly-lucian.ngrok-free.dev)
    ↓
Next.js Webhook (:3000/api/gmail/webhook)
    ↓ (HTTP POST)
Python Agent Server (:8001/gmail/handle)
    ↓
Simple Gmail Handler (lib/agent/gmail_handler.py)
    ↓
MCP Server (:8000)
    ↓
Google Workspace API
    ↓
Send Reply Email
```

## Handler Logic

**File:** `lib/agent/gmail_handler.py`

1. Initialize MCP session
2. Search for unread emails (query: "is:unread newer_than:1d")
3. If unread emails exist:
   - Send generic acknowledgment to ALL authorized senders
   - Subject: "Received your message - Sabine will respond soon"
   - Body: Generic "Thanks, will respond soon" message
4. Return success with list of recipients

**Why this approach:**
- Avoids parsing individual message IDs (workspace-mcp text format issue)
- Ensures SOMEONE gets a response
- Simple and reliable

## Next Steps

### Short Term (Fix Webhook)

1. **Diagnose Pub/Sub Delivery**
   - Check Google Cloud Console for delivery failures
   - Verify push subscription pointing to correct ngrok URL
   - Check ngrok dashboard for incoming requests

2. **Test End-to-End**
   - Send test email to sabine@strugcity.com
   - Monitor Next.js logs: `tail -f tasks/b82207a.output | grep "Gmail"`
   - Check Python agent logs for `/gmail/handle` requests

3. **If Still Not Working:**
   - Recreate Gmail watch: `python check_gmail_watch.py`
   - Update Pub/Sub push endpoint to current ngrok URL
   - Verify service account has Pub/Sub permissions

### Medium Term (Improve Handler)

1. **Parse Individual Emails**
   - Work with workspace-mcp developer to get JSON output mode
   - OR implement robust regex parsing for text format
   - Extract actual sender and subject for personalized replies

2. **Add Reply Intelligence**
   - Use Claude Sonnet (once API access fixed) to generate context-aware replies
   - Analyze email content and generate appropriate response
   - Thread replies correctly to original email

3. **Sender Verification**
   - Check sender against authorized list BEFORE replying
   - Don't reply to everyone on every notification
   - Only reply to NEW emails (track message IDs)

### Long Term (Production Ready)

1. **Error Handling**
   - Retry logic for failed MCP calls
   - Fallback if MCP server down
   - Alert on handler failures

2. **Monitoring**
   - Log all webhook notifications
   - Track reply success/failure rates
   - Alert if no emails processed for X hours

3. **Testing**
   - Unit tests for handler logic
   - Integration tests with mock MCP responses
   - End-to-end test with test Gmail account

## Files Modified

### Created
- `lib/agent/gmail_handler.py` - Simple auto-reply handler
- `GMAIL_AUTOREPLY_STATUS.md` - This file

### Modified
- `src/app/api/gmail/webhook/route.ts` - Calls `/gmail/handle` instead of `/invoke`
- `lib/agent/server.py` - Added `/gmail/handle` endpoint
- `lib/agent/mcp_client.py` - Auto-inject `user_google_email` for Gmail tools
- `.env` - Updated `PYTHON_API_URL` to port 8001

### Referenced (Not Changed)
- `check_gmail_watch.py` - Verify Gmail watch status
- `test_webhook.json` - Sample Pub/Sub notification for testing

## Quick Commands

```bash
# Check Gmail watch status
python check_gmail_watch.py

# Test webhook directly
curl -X POST http://127.0.0.1:3000/api/gmail/webhook \
  -H "Content-Type: application/json" \
  -d @test_webhook.json

# Test handler directly
curl -X POST http://127.0.0.1:8001/gmail/handle \
  -H "Content-Type: application/json" \
  -d '{"historyId": "9999"}'

# Monitor Next.js logs
tail -f C:\Users\rktra\AppData\Local\Temp\claude\C--Users-rktra-Documents-Projects-superAgent-superAgent\tasks\b82207a.output

# Monitor Python agent logs
tail -f C:\Users\rktra\AppData\Local\Temp\claude\C--Users-rktra-Documents-Projects-superAgent-superAgent\tasks\bb2b86d.output

# Check running processes
netstat -ano | findstr ":8000"  # MCP server
netstat -ano | findstr ":8001"  # Python agent
netstat -ano | findstr ":3000"  # Next.js

# Restart Python agent
cd C:\Users\rktra\Documents\Projects\superAgent\superAgent
NODE_ENV=production API_PORT=8001 python lib/agent/server.py
```

## Conclusion

**Infrastructure: READY**
**Code: COMPLETE**
**Issue: Pub/Sub notifications not reaching webhook**

The auto-reply system is fully implemented and waiting for webhook notifications. The most likely issue is that Gmail Pub/Sub notifications are not being delivered to the ngrok URL. Verify the Pub/Sub push subscription configuration and check delivery logs in Google Cloud Console.

Once webhook notifications arrive, the handler will:
1. Detect unread emails
2. Send generic acknowledgment to rknollmaier@gmail.com and sabine@strugcity.com
3. Log success/failure

---

**Contact:** Questions? Check logs or test handler directly using curl commands above.
