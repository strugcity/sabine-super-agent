/**
 * Twilio SMS Webhook Handler
 *
 * This Next.js API route receives SMS messages from Twilio and forwards them
 * to the Python FastAPI server (LangGraph agent). It then returns TwiML responses.
 *
 * Flow:
 * 1. Twilio sends SMS → This endpoint (Next.js on Vercel)
 * 2. This endpoint → Python FastAPI server (localhost:8000 or deployed URL)
 * 3. Python returns agent response
 * 4. This endpoint → TwiML XML response back to Twilio
 * 5. Twilio sends SMS to user
 */

import { NextRequest, NextResponse } from 'next/server';

// =============================================================================
// Configuration
// =============================================================================

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://127.0.0.1:8000';
const ADMIN_PHONE = process.env.ADMIN_PHONE || '';

// Default user ID (in production, you'd look this up from the phone number)
const DEFAULT_USER_ID = process.env.DEFAULT_USER_ID || '00000000-0000-0000-0000-000000000000';

// =============================================================================
// Types
// =============================================================================

interface TwilioWebhookBody {
  From: string;
  To: string;
  Body: string;
  MessageSid: string;
  AccountSid: string;
  [key: string]: string;
}

interface AgentResponse {
  success: boolean;
  response: string;
  user_id: string;
  session_id: string;
  timestamp: string;
  error?: string;
}

// =============================================================================
// TwiML Utilities
// =============================================================================

/**
 * Generate TwiML XML response for Twilio
 */
function generateTwiML(message: string | null): string {
  if (!message || message.toLowerCase() === 'done') {
    // Empty TwiML - no SMS will be sent back
    return '<?xml version="1.0" encoding="UTF-8"?><Response></Response>';
  }

  // TwiML with message
  return `<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Message>${escapeXml(message)}</Message>
</Response>`;
}

/**
 * Escape XML special characters
 */
function escapeXml(unsafe: string): string {
  return unsafe
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

// =============================================================================
// User ID Lookup (Placeholder)
// =============================================================================

/**
 * Look up user ID from phone number
 *
 * In production, this should query the user_identities table in Supabase
 * to find the user_id associated with this phone number.
 */
async function getUserIdFromPhone(phoneNumber: string): Promise<string> {
  // TODO: Implement Supabase lookup
  // const supabase = createClient(...)
  // const { data } = await supabase
  //   .from('user_identities')
  //   .select('user_id')
  //   .eq('provider', 'twilio')
  //   .eq('identifier', phoneNumber)
  //   .single()
  //
  // return data?.user_id || DEFAULT_USER_ID

  // For now, return default user ID
  return DEFAULT_USER_ID;
}

// =============================================================================
// Main Handler
// =============================================================================

export async function POST(request: NextRequest) {
  console.log('📱 Twilio webhook received');

  try {
    // Parse form data from Twilio
    const formData = await request.formData();
    const body: TwilioWebhookBody = Object.fromEntries(formData) as any;

    const fromPhone = body.From;
    const message = body.Body;
    const messageSid = body.MessageSid;

    console.log(`From: ${fromPhone}`);
    console.log(`Message: ${message}`);
    console.log(`MessageSid: ${messageSid}`);

    // ==========================================================================
    // Validation: Check if sender is authorized
    // ==========================================================================

    if (ADMIN_PHONE && fromPhone !== ADMIN_PHONE) {
      console.warn(`⚠️  Unauthorized phone number: ${fromPhone}`);

      return new NextResponse(
        generateTwiML('Sorry, this service is not available for your number.'),
        {
          status: 200,
          headers: { 'Content-Type': 'text/xml' },
        }
      );
    }

    // ==========================================================================
    // Get User ID from Phone Number
    // ==========================================================================

    const userId = await getUserIdFromPhone(fromPhone);
    const sessionId = `twilio-${messageSid}`;

    console.log(`User ID: ${userId}`);
    console.log(`Session ID: ${sessionId}`);

    // ==========================================================================
    // Forward to Python Agent
    // ==========================================================================

    console.log(`🔄 Forwarding to Python API: ${PYTHON_API_URL}/invoke`);

    const agentResponse = await fetch(`${PYTHON_API_URL}/invoke`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        message: message,
        user_id: userId,
        session_id: sessionId,
        conversation_history: null, // TODO: Load from database if needed
      }),
    });

    if (!agentResponse.ok) {
      console.error(`❌ Python API error: ${agentResponse.status}`);
      throw new Error(`Python API returned ${agentResponse.status}`);
    }

    const agentData: AgentResponse = await agentResponse.json();

    console.log(`✅ Agent response received: ${agentData.response.substring(0, 100)}...`);

    // ==========================================================================
    // Generate TwiML Response
    // ==========================================================================

    const twiml = generateTwiML(agentData.response);

    console.log('📤 Sending TwiML response to Twilio');

    return new NextResponse(twiml, {
      status: 200,
      headers: {
        'Content-Type': 'text/xml',
      },
    });

  } catch (error) {
    console.error('❌ Error processing webhook:', error);

    // Return error message via TwiML
    const errorTwiML = generateTwiML(
      'Sorry, I encountered an error processing your message. Please try again later.'
    );

    return new NextResponse(errorTwiML, {
      status: 200,
      headers: {
        'Content-Type': 'text/xml',
      },
    });
  }
}

// =============================================================================
// GET Handler (for testing)
// =============================================================================

export async function GET(request: NextRequest) {
  return NextResponse.json({
    name: 'Personal Super Agent - Twilio Webhook',
    status: 'running',
    description: 'This endpoint receives SMS messages from Twilio',
    endpoints: {
      'POST /api/chat': 'Process incoming SMS from Twilio',
    },
    configuration: {
      pythonApiUrl: PYTHON_API_URL,
      adminPhoneConfigured: !!ADMIN_PHONE,
      defaultUserId: DEFAULT_USER_ID,
    },
  });
}
