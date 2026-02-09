'use client'

import { useState, useEffect, useCallback } from 'react'
import { EntityComment } from '@/lib/types/database'

interface CommentSectionProps {
  entityId: string
}

export function CommentSection({ entityId }: CommentSectionProps) {
  const [comments, setComments] = useState<EntityComment[]>([])
  const [newComment, setNewComment] = useState('')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editContent, setEditContent] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchComments = useCallback(async () => {
    setIsLoading(true)
    setError(null)

    try {
      const response = await fetch(`/api/comments?entity_id=${entityId}`)

      if (!response.ok) {
        throw new Error('Failed to fetch comments')
      }

      const data = await response.json()
      setComments(data)
    } catch (err) {
      setError('Failed to load comments')
      console.error('Error fetching comments:', err)
    } finally {
      setIsLoading(false)
    }
  }, [entityId])

  // Fetch comments on mount
  useEffect(() => {
    fetchComments()
  }, [fetchComments])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (!newComment.trim()) {
      return
    }

    setIsSubmitting(true)
    setError(null)

    try {
      const response = await fetch('/api/comments', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          entity_id: entityId,
          content: newComment.trim(),
        }),
      })

      if (!response.ok) {
        throw new Error('Failed to create comment')
      }

      const comment = await response.json()
      setComments([comment, ...comments])
      setNewComment('')
    } catch (err) {
      setError('Failed to add comment')
      console.error('Error creating comment:', err)
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleEdit = async (commentId: string) => {
    if (!editContent.trim()) {
      return
    }

    setIsSubmitting(true)
    setError(null)

    try {
      const response = await fetch(`/api/comments?comment_id=${commentId}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editContent.trim(),
        }),
      })

      if (!response.ok) {
        throw new Error('Failed to update comment')
      }

      const updatedComment = await response.json()
      setComments(
        comments.map((c) => (c.id === commentId ? updatedComment : c))
      )
      setEditingId(null)
      setEditContent('')
    } catch (err) {
      setError('Failed to update comment')
      console.error('Error updating comment:', err)
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleDelete = async (commentId: string) => {
    if (!confirm('Delete this comment?')) {
      return
    }

    setError(null)

    try {
      const response = await fetch(`/api/comments?comment_id=${commentId}`, {
        method: 'DELETE',
      })

      if (!response.ok) {
        throw new Error('Failed to delete comment')
      }

      setComments(comments.filter((c) => c.id !== commentId))
    } catch (err) {
      setError('Failed to delete comment')
      console.error('Error deleting comment:', err)
    }
  }

  const startEditing = (comment: EntityComment) => {
    setEditingId(comment.id)
    setEditContent(comment.content)
  }

  const cancelEditing = () => {
    setEditingId(null)
    setEditContent('')
  }

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr)
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)

    if (diffMins < 1) return 'just now'
    if (diffMins < 60) return `${diffMins}m ago`
    if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`
    if (diffMins < 10080) return `${Math.floor(diffMins / 1440)}d ago`

    return date.toLocaleDateString()
  }

  return (
    <div className="mt-4 pt-4 border-t border-gray-200">
      <h4 className="text-sm font-semibold text-gray-900 mb-3">Comments</h4>

      {error && (
        <div className="mb-3 p-2 bg-red-50 border border-red-200 rounded text-sm text-red-700">
          {error}
        </div>
      )}

      {/* New comment form */}
      <form onSubmit={handleSubmit} className="mb-4">
        <textarea
          value={newComment}
          onChange={(e) => setNewComment(e.target.value)}
          placeholder="Add a comment..."
          className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
          rows={2}
          disabled={isSubmitting}
        />
        <div className="mt-2 flex justify-end">
          <button
            type="submit"
            disabled={isSubmitting || !newComment.trim()}
            className="px-3 py-1 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
          >
            {isSubmitting ? 'Adding...' : 'Add Comment'}
          </button>
        </div>
      </form>

      {/* Comments list */}
      {isLoading ? (
        <div className="text-sm text-gray-500 text-center py-4">
          Loading comments...
        </div>
      ) : comments.length === 0 ? (
        <div className="text-sm text-gray-500 text-center py-4">
          No comments yet. Be the first to comment!
        </div>
      ) : (
        <div className="space-y-3">
          {comments.map((comment) => (
            <div
              key={comment.id}
              className="p-3 bg-gray-50 rounded-md border border-gray-200"
            >
              {editingId === comment.id ? (
                <div>
                  <textarea
                    value={editContent}
                    onChange={(e) => setEditContent(e.target.value)}
                    className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
                    rows={2}
                    disabled={isSubmitting}
                  />
                  <div className="mt-2 flex justify-end space-x-2">
                    <button
                      onClick={cancelEditing}
                      disabled={isSubmitting}
                      className="px-2 py-1 text-xs text-gray-700 hover:bg-gray-200 rounded transition-colors disabled:cursor-not-allowed"
                    >
                      Cancel
                    </button>
                    <button
                      onClick={() => handleEdit(comment.id)}
                      disabled={isSubmitting || !editContent.trim()}
                      className="px-2 py-1 text-xs bg-blue-600 text-white rounded hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
                    >
                      {isSubmitting ? 'Saving...' : 'Save'}
                    </button>
                  </div>
                </div>
              ) : (
                <div>
                  <p className="text-sm text-gray-800 whitespace-pre-wrap">
                    {comment.content}
                  </p>
                  <div className="mt-2 flex items-center justify-between">
                    <span className="text-xs text-gray-500">
                      {formatDate(comment.created_at)}
                    </span>
                    <div className="flex space-x-2">
                      <button
                        onClick={() => startEditing(comment)}
                        className="text-xs text-blue-600 hover:text-blue-800 transition-colors"
                      >
                        Edit
                      </button>
                      <button
                        onClick={() => handleDelete(comment.id)}
                        className="text-xs text-red-600 hover:text-red-800 transition-colors"
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
