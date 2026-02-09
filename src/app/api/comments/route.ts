import { NextRequest, NextResponse } from 'next/server';

const PYTHON_API_URL = process.env.PYTHON_API_URL || 'http://127.0.0.1:8000';
const API_KEY = process.env.SABINE_API_KEY || 'dev-key-12345';

/**
 * GET /api/comments?entity_id=<uuid>
 * Fetch all comments for an entity
 */
export async function GET(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const entityId = searchParams.get('entity_id');

  if (!entityId) {
    return NextResponse.json(
      { error: 'entity_id is required' },
      { status: 400 }
    );
  }

  try {
    const response = await fetch(
      `${PYTHON_API_URL}/comments/entity/${entityId}`,
      {
        method: 'GET',
        headers: {
          'X-API-Key': API_KEY,
          'Content-Type': 'application/json',
        },
      }
    );

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      return NextResponse.json(
        { error: errorData.detail || 'Failed to fetch comments' },
        { status: response.status }
      );
    }

    const comments = await response.json();
    return NextResponse.json(comments);
  } catch (error) {
    console.error('Error fetching comments:', error);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}

/**
 * POST /api/comments
 * Create a new comment
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    if (!body.entity_id || !body.content) {
      return NextResponse.json(
        { error: 'entity_id and content are required' },
        { status: 400 }
      );
    }

    const response = await fetch(`${PYTHON_API_URL}/comments`, {
      method: 'POST',
      headers: {
        'X-API-Key': API_KEY,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      return NextResponse.json(
        { error: errorData.detail || 'Failed to create comment' },
        { status: response.status }
      );
    }

    const comment = await response.json();
    return NextResponse.json(comment);
  } catch (error) {
    console.error('Error creating comment:', error);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}

/**
 * PUT /api/comments?comment_id=<uuid>
 * Update a comment
 */
export async function PUT(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const commentId = searchParams.get('comment_id');

  if (!commentId) {
    return NextResponse.json(
      { error: 'comment_id is required' },
      { status: 400 }
    );
  }

  try {
    const body = await request.json();

    if (!body.content) {
      return NextResponse.json(
        { error: 'content is required' },
        { status: 400 }
      );
    }

    const response = await fetch(`${PYTHON_API_URL}/comments/${commentId}`, {
      method: 'PUT',
      headers: {
        'X-API-Key': API_KEY,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      return NextResponse.json(
        { error: errorData.detail || 'Failed to update comment' },
        { status: response.status }
      );
    }

    const comment = await response.json();
    return NextResponse.json(comment);
  } catch (error) {
    console.error('Error updating comment:', error);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}

/**
 * DELETE /api/comments?comment_id=<uuid>
 * Delete a comment
 */
export async function DELETE(request: NextRequest) {
  const searchParams = request.nextUrl.searchParams;
  const commentId = searchParams.get('comment_id');

  if (!commentId) {
    return NextResponse.json(
      { error: 'comment_id is required' },
      { status: 400 }
    );
  }

  try {
    const response = await fetch(`${PYTHON_API_URL}/comments/${commentId}`, {
      method: 'DELETE',
      headers: {
        'X-API-Key': API_KEY,
        'Content-Type': 'application/json',
      },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      return NextResponse.json(
        { error: errorData.detail || 'Failed to delete comment' },
        { status: response.status }
      );
    }

    const result = await response.json();
    return NextResponse.json(result);
  } catch (error) {
    console.error('Error deleting comment:', error);
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    );
  }
}
