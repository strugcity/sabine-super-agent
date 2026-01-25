// Gmail Watch Renewal Cron Job
// Called by Vercel Cron every 6 days to renew Gmail push notification watch.
// Gmail watches expire after 7 days, so we renew with a 1-day buffer.
// See vercel.json for cron schedule configuration.

import { NextRequest, NextResponse } from 'next/server';

// Verify cron secret to prevent unauthorized calls
const CRON_SECRET = process.env.CRON_SECRET || '';
const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://127.0.0.1:8001';
const AGENT_API_KEY = process.env.AGENT_API_KEY || '';

export async function GET(request: NextRequest) {
  // Verify authorization
  const authHeader = request.headers.get('authorization');
  if (authHeader !== `Bearer ${CRON_SECRET}`) {
    console.error('[Gmail Watch Cron] Unauthorized request');
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
  }

  console.log('[Gmail Watch Cron] Starting Gmail watch renewal...');

  try {
    // Call the Python API to renew Gmail watch
    const response = await fetch(`${PYTHON_API_URL}/gmail/renew-watch`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': AGENT_API_KEY,
      },
      body: JSON.stringify({
        webhookUrl: process.env.GMAIL_WEBHOOK_URL || `${process.env.VERCEL_URL}/api/gmail/webhook`,
      }),
    });

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
    console.error('[Gmail Watch Cron] Error:', error);
    return NextResponse.json(
      { error: 'Internal error', details: String(error) },
      { status: 500 }
    );
  }
}
