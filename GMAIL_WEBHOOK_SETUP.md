# Gmail Webhook Setup Guide

This guide walks you through setting up real-time Gmail notifications via Google Cloud Pub/Sub.

## Overview

The Gmail webhook enables instant email notifications without polling:
1. Gmail sends notification to Pub/Sub when new email arrives
2. Pub/Sub pushes notification to your webhook endpoint
3. Webhook triggers Python agent to handle email using MCP tools
4. Agent reads email and sends response via sabine@strugcity.com

## Prerequisites

- ✅ Google Workspace account (sabine@strugcity.com) with OAuth configured
- ✅ workspace-mcp server running with valid credentials
- ✅ Python agent server running on port 8001
- ⏳ Google Cloud project (will create if needed)

---

## Step 1: Create Google Cloud Project (if needed)

1. Go to https://console.cloud.google.com/
2. Click "Select a project" → "NEW PROJECT"
3. Name: `personal-super-agent` (or similar)
4. Click "CREATE"
5. Note your **Project ID** (e.g., `personal-super-agent-12345`)

---

## Step 2: Enable Required APIs

1. Go to https://console.cloud.google.com/apis/library
2. Search and enable these APIs:
   - **Gmail API** (should already be enabled from OAuth setup)
   - **Cloud Pub/Sub API**

---

## Step 3: Create Pub/Sub Topic

1. Go to https://console.cloud.google.com/cloudpubsub/topic/list
2. Click **"CREATE TOPIC"**
3. Topic ID: `gmail-notifications`
4. Leave other settings as default
5. Click **"CREATE"**

**Note the full topic name:** `projects/YOUR-PROJECT-ID/topics/gmail-notifications`

---

## Step 4: Create Service Account (for Pub/Sub verification)

1. Go to https://console.cloud.google.com/iam-admin/serviceaccounts
2. Click **"CREATE SERVICE ACCOUNT"**
3. Name: `gmail-webhook-verifier`
4. Description: `Service account for verifying Gmail webhook Pub/Sub messages`
5. Click **"CREATE AND CONTINUE"**
6. Skip role assignment (click **"CONTINUE"**)
7. Click **"DONE"**

8. Click on the newly created service account
9. Go to **"KEYS"** tab
10. Click **"ADD KEY"** → **"Create new key"**
11. Select **JSON** format
12. Click **"CREATE"**
13. Save the downloaded JSON file securely

---

## Step 5: Setup Ngrok for Local Testing

Since we're testing locally, we need a public URL for Pub/Sub to reach our webhook:

1. Install ngrok: https://ngrok.com/download
2. Run ngrok:
   ```bash
   ngrok http 3000
   ```
3. Note the **HTTPS URL** (e.g., `https://abc123.ngrok.io`)
4. Keep ngrok running in a separate terminal

---

## Step 6: Create Pub/Sub Push Subscription

1. Go back to https://console.cloud.google.com/cloudpubsub/topic/list
2. Click on your `gmail-notifications` topic
3. Click **"CREATE SUBSCRIPTION"**
4. Configure:
   - **Subscription ID:** `gmail-notifications-push`
   - **Delivery type:** Push
   - **Endpoint URL:** `https://YOUR-NGROK-URL.ngrok.io/api/gmail/webhook`
     (Replace with your ngrok URL from Step 5)
   - **Expiration:** Never expire
   - Leave other settings as default
5. Click **"CREATE"**

---

## Step 7: Configure Gmail Push Notifications

You need to tell Gmail to send notifications to your Pub/Sub topic. This requires using the Gmail API:

### Option A: Using `gcloud` CLI (Recommended)

1. Install Google Cloud SDK: https://cloud.google.com/sdk/docs/install
2. Authenticate:
   ```bash
   gcloud auth login
   gcloud config set project YOUR-PROJECT-ID
   ```
3. Enable watch for sabine@strugcity.com:
   ```bash
   gcloud alpha gmail watch sabine@strugcity.com \
     --topic=projects/YOUR-PROJECT-ID/topics/gmail-notifications
   ```

### Option B: Using REST API

Make a POST request to Gmail API:

```bash
curl -X POST \
  https://gmail.googleapis.com/gmail/v1/users/sabine@strugcity.com/watch \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "topicName": "projects/YOUR-PROJECT-ID/topics/gmail-notifications",
    "labelIds": ["INBOX"]
  }'
```

You can get an access token from: https://developers.google.com/oauthplayground

Select scopes:
- `https://www.googleapis.com/auth/gmail.modify`

---

## Step 8: Add Environment Variables

Add these to your `.env` file:

```env
# Google Cloud Pub/Sub Configuration
GOOGLE_CLOUD_PROJECT_ID=your-project-id
GMAIL_PUBSUB_TOPIC=projects/your-project-id/topics/gmail-notifications
GMAIL_WEBHOOK_URL=https://your-ngrok-url.ngrok.io/api/gmail/webhook

# Service account key (copy from downloaded JSON file)
GOOGLE_SERVICE_ACCOUNT_KEY={"type":"service_account","project_id":"..."}
```

---

## Step 9: Test the Webhook

1. Verify Next.js is running:
   ```bash
   npm run dev
   ```

2. Check webhook health:
   ```bash
   curl http://localhost:3000/api/gmail/webhook
   ```

   Expected response:
   ```json
   {
     "status": "ok",
     "endpoint": "gmail-webhook",
     "authorized_emails": ["rknollmaier@gmail.com", "sabine@strugcity.com"]
   }
   ```

3. Send a test email to sabine@strugcity.com from rknollmaier@gmail.com

4. Watch the logs:
   - **Next.js logs:** Should show "[Gmail Webhook] Notification received..."
   - **Python agent logs:** Should show agent processing the email
   - **workspace-mcp logs:** Should show Gmail API calls

---

## Step 10: Verify End-to-End Flow

Send an email from your personal account (rknollmaier@gmail.com) to sabine@strugcity.com:

**Subject:** Test Gmail Webhook
**Body:** Hi Sabine, please respond to this email to confirm the webhook is working.

Expected behavior:
1. Gmail sends notification to Pub/Sub (within seconds)
2. Pub/Sub pushes to your webhook endpoint
3. Webhook triggers Python agent
4. Agent uses MCP tools to:
   - Search for new emails
   - Read the email content
   - Generate a response
   - Send reply from sabine@strugcity.com
5. You receive response email from sabine@strugcity.com

---

## Troubleshooting

### Webhook not receiving notifications

1. **Check ngrok is running** and URL matches subscription endpoint
2. **Check Pub/Sub subscription** has correct endpoint URL
3. **Check Gmail watch is active:**
   ```bash
   curl https://gmail.googleapis.com/gmail/v1/users/sabine@strugcity.com/profile \
     -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
   ```

### Agent not processing emails

1. **Check Python agent is running:** `curl http://localhost:8001/health`
2. **Check workspace-mcp is running:** `curl http://localhost:8000/mcp`
3. **Check environment variables** are loaded correctly
4. **Check agent logs** for errors

### Pub/Sub authentication errors

1. **Verify service account key** is in `.env`
2. **Check subscription permissions** in Google Cloud Console
3. **Ensure Pub/Sub API is enabled**

---

## Production Deployment

For production:

1. **Deploy Next.js to Vercel:**
   ```bash
   vercel deploy
   ```

2. **Update Pub/Sub subscription endpoint** to production URL:
   ```
   https://your-project.vercel.app/api/gmail/webhook
   ```

3. **Re-enable Gmail watch** with production topic

4. **Setup monitoring:**
   - Cloud Monitoring for Pub/Sub metrics
   - Vercel logs for webhook requests
   - Sentry for error tracking

---

## Watch Renewal

Gmail watch expires after **7 days**. You need to renew it:

### Manual Renewal
Run the watch command again (same as Step 7)

### Automatic Renewal (Recommended)
Create a cron job in `vercel.json`:

```json
{
  "crons": [
    {
      "path": "/api/gmail/renew-watch",
      "schedule": "0 0 * * 0"
    }
  ]
}
```

Create renewal endpoint at `src/app/api/gmail/renew-watch/route.ts`:

```typescript
import { NextResponse } from 'next/server';

export async function GET() {
  // Call Gmail API to renew watch
  // (Implementation left as exercise)
  return NextResponse.json({ renewed: true });
}
```

---

## Security Considerations

1. **Verify Pub/Sub messages:** Validate JWT tokens in production
2. **Rate limiting:** Add rate limiting to webhook endpoint
3. **Authorized senders:** Agent checks sender before responding
4. **Service account permissions:** Minimal permissions only
5. **Environment variables:** Never commit to git

---

## Next Steps

After webhook is working:

1. ✅ Test with multiple emails
2. ✅ Add more sophisticated email parsing
3. ✅ Implement email classification (urgent, spam, etc.)
4. ✅ Add email templates for common responses
5. ✅ Implement conversation threading
6. ✅ Add Calendar integration (schedule meetings from email)
7. ✅ Add Drive integration (save attachments automatically)

---

## Resources

- [Gmail Push Notifications](https://developers.google.com/gmail/api/guides/push)
- [Cloud Pub/Sub Documentation](https://cloud.google.com/pubsub/docs)
- [MCP Workspace Integration](https://github.com/TWilson023/workspace-mcp)

---

**Status:** Ready to configure!

Follow Steps 1-9 above to complete the setup. Let me know when you're ready to test!
