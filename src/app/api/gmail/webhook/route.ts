/**
 * Gmail Webhook Route
 *
 * Receives Gmail push notifications via Google Cloud Pub/Sub.
 * Triggers the Python agent to handle new emails using MCP tools.
 */

import { NextRequest, NextResponse } from 'next/server';
import {
  parsePubSubNotification,
  verifyPubSubToken,
  type PubSubMessage,
} from '@/lib/gmail/parser';

// Get environment variables
const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://127.0.0.1:8001';
const AGENT_API_KEY = process.env.AGENT_API_KEY || '';
const DEFAULT_USER_ID = process.env.DEFAULT_USER_ID || '00000000-0000-0000-0000-000000000000';
const GMAIL_AUTHORIZED_EMAILS = (process.env.GMAIL_AUTHORIZED_EMAILS || '').split(',').map(e => e.trim());

export async function POST(request: NextRequest) {
  try {
    // Parse Pub/Sub push notification
    const body: PubSubMessage = await request.json();

    // Verify Pub/Sub authenticity
    if (!body.message || !verifyPubSubToken(body.message)) {
      console.error('Invalid Pub/Sub message');
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    // Decode notification
    const notification = parsePubSubNotification(body);
    const { emailAddress, historyId } = notification;

    console.log(`[Gmail Webhook] Notification received for ${emailAddress}, historyId: ${historyId}`);

    // Check if this email address is authorized
    if (!GMAIL_AUTHORIZED_EMAILS.includes(emailAddress.toLowerCase())) {
      console.log(`[Gmail Webhook] Email address ${emailAddress} not in authorized list, ignoring`);
      return NextResponse.json({ success: true, ignored: true });
    }

    // Forward to Python agent with special instruction
    // Agent will use MCP tools to:
    //   - Fetch new emails from history (gmail_get_history or search_gmail_messages)
    //   - Read email content (get_gmail_message_content)
    //   - Extract sender and body
    //   - Generate response
    //   - Send reply (send_gmail_message)
    const agentPayload = {
      message: `New email notification received for ${emailAddress} (historyId: ${historyId}). Please check for new emails since this history ID and respond if from an authorized sender.`,
      user_id: DEFAULT_USER_ID,
      session_id: `gmail-notification-${historyId}-${Date.now()}`,
      conversation_history: null,
      metadata: {
        trigger: 'gmail_webhook',
        emailAddress,
        historyId,
        authorizedEmails: GMAIL_AUTHORIZED_EMAILS,
      },
    };

    console.log(`[Gmail Webhook] Calling simple Gmail handler: ${PYTHON_API_URL}/gmail/handle`);

    // Call the simple Gmail handler (bypasses complex agent)
    try {
      const response = await fetch(`${PYTHON_API_URL}/gmail/handle`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': AGENT_API_KEY,
        },
        body: JSON.stringify({ historyId }),
      });

      console.log('[Gmail Webhook] Railway Response Status:', response.status);
      const responseText = await response.text();
      console.log('[Gmail Webhook] Railway Response Text:', responseText);

      if (!response.ok) {
        console.error(`[Gmail Webhook] Railway returned non-2xx status: ${response.status}`, responseText);
      }
    } catch (error) {
      console.error('[Gmail Webhook] Error calling handler:', error);
    }

    // Acknowledge receipt to Pub/Sub immediately
    return NextResponse.json({ success: true });
  } catch (error) {
    console.error('[Gmail Webhook] Error processing webhook:', error);

    // Still return 200 to avoid Pub/Sub retries for invalid messages
    return NextResponse.json({
      success: false,
      error: error instanceof Error ? error.message : 'Unknown error',
    });
  }
}

// Health check endpoint
export async function GET() {
  return NextResponse.json({
    status: 'ok',
    endpoint: 'gmail-webhook',
    authorized_emails: GMAIL_AUTHORIZED_EMAILS,
  });
}
