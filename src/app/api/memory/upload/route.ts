import { NextRequest, NextResponse } from 'next/server'

/**
 * POST /api/memory/upload
 *
 * Proxy endpoint for file uploads to the Python API.
 * This keeps the AGENT_API_KEY secure on the server side.
 */
export async function POST(request: NextRequest) {
  try {
    // Get the form data from the request
    const formData = await request.formData()

    // Get API configuration from server-side env vars (not exposed to browser)
    const apiUrl = process.env.PYTHON_API_URL || 'http://127.0.0.1:8001'
    const apiKey = process.env.AGENT_API_KEY

    if (!apiKey) {
      return NextResponse.json(
        { success: false, error: 'Server misconfiguration: API key not set' },
        { status: 500 }
      )
    }

    // Forward the request to the Python API
    const response = await fetch(`${apiUrl}/memory/upload`, {
      method: 'POST',
      headers: {
        'X-API-Key': apiKey,
      },
      body: formData,
    })

    // Get the response data
    const data = await response.json()

    // Return the response with the same status
    return NextResponse.json(data, { status: response.status })

  } catch (error) {
    console.error('Upload proxy error:', error)
    return NextResponse.json(
      {
        success: false,
        error: error instanceof Error ? error.message : 'Upload failed'
      },
      { status: 500 }
    )
  }
}

// Configure for large file uploads (50MB max)
export const config = {
  api: {
    bodyParser: false,
  },
}
