// Gmail Watch Renewal Cron Job
// Called by Vercel Cron every 6 days to renew Gmail push notification watch.
// Gmail watches expire after 7 days, so we renew with a 1-day buffer.
// See vercel.json for cron schedule configuration.

import { NextRequest, NextResponse } from 'next/server';

// Configuration - validated at request time
const CRON_SECRET = process.env.CRON_SECRET;
const PYTHON_API_URL = process.env.PYTHON_API_URL;
const AGENT_API_KEY = process.env.AGENT_API_KEY;

// Timeout for Python API calls (30 seconds)
const FETCH_TIMEOUT_MS = 30000;

export async function GET(request: NextRequest) {
  // Validate required environment variables
  if (!CRON_SECRET) {
    console.error('[Gmail Watch Cron] CRON_SECRET not configured');
    return NextResponse.json(
      { error: 'Server misconfiguration: CRON_SECRET not set' },
      { status: 500 }
    );
  }

  if (!PYTHON_API_URL) {
    console.error('[Gmail Watch Cron] PYTHON_API_URL not configured');
    return NextResponse.json(
      { error: 'Server misconfiguration: PYTHON_API_URL not set' },
      { status: 500 }
    );
  }

  if (!AGENT_API_KEY) {
    console.error('[Gmail Watch Cron] AGENT_API_KEY not configured');
    return NextResponse.json(
      { error: 'Server misconfiguration: AGENT_API_KEY not set' },
      { status: 500 }
    );
  }

  // Verify authorization
  const authHeader = request.headers.get('authorization');
  if (authHeader !== `Bearer ${CRON_SECRET}`) {
    console.error('[Gmail Watch Cron] Unauthorized request');
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  console.log('[Gmail Watch Cron] Starting Gmail watch renewal...');

  // Create AbortController for timeout
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);

  try {
    // Call the Python API to renew Gmail watch
    const response = await fetch(`${PYTHON_API_URL}/gmail/renew-watch`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': AGENT_API_KEY,
      },
      body: JSON.stringify({
        webhookUrl: process.env.GMAIL_WEBHOOK_URL || `https://${process.env.VERCEL_URL}/api/gmail/webhook`,
      }),
      signal: controller.signal,
      cache: 'no-store',
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      const errorText = await response.text();
      console.error('[Gmail Watch Cron] Failed to renew watch:', errorText);
      return NextResponse.json(
        { error: 'Failed to renew Gmail watch', details: errorText },
        { status: 500 }
      );
    }

    const result = await response.json();
    console.log('[Gmail Watch Cron] Watch renewed successfully:', result);

    return NextResponse.json({
      success: true,
      message: 'Gmail watch renewed',
      result,
    });
  } catch (error) {
    clearTimeout(timeoutId);

    // Check if it was a timeout
    if (error instanceof Error && error.name === 'AbortError') {
      console.error('[Gmail Watch Cron] Request timed out after', FETCH_TIMEOUT_MS, 'ms');
      return NextResponse.json(
        { error: 'Gateway timeout', details: 'Python API did not respond in time' },
        { status: 504 }
      );
    }

    console.error('[Gmail Watch Cron] Error:', error);
    return NextResponse.json(
      { error: 'Internal error', details: String(error) },
      { status: 500 }
    );
  }
}
