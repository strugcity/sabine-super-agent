'use client'

import { useState } from 'react'
import { Entity } from '@/lib/types/database'
import { updateEntity, deleteEntity } from '@/app/dashboard/memory/actions'
import { CommentSection } from './CommentSection'

interface EntityCardProps {
  entity: Entity
}

const domainColors = {
  work: 'bg-blue-50 border-blue-200 text-blue-700',
  family: 'bg-pink-50 border-pink-200 text-pink-700',
  personal: 'bg-purple-50 border-purple-200 text-purple-700',
  logistics: 'bg-green-50 border-green-200 text-green-700',
}

const domainBadgeColors = {
  work: 'bg-blue-100 text-blue-800',
  family: 'bg-pink-100 text-pink-800',
  personal: 'bg-purple-100 text-purple-800',
  logistics: 'bg-green-100 text-green-800',
}

export function EntityCard({ entity }: EntityCardProps) {
  const [isEditing, setIsEditing] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [showComments, setShowComments] = useState(false)
  const [editedAttributes, setEditedAttributes] = useState(
    JSON.stringify(entity.attributes, null, 2)
  )
  const [error, setError] = useState<string | null>(null)

  // Format attributes for display (show first 3 keys or truncate if large)
  const attributesPreview = (() => {
    const keys = Object.keys(entity.attributes)
    if (keys.length === 0) return 'No attributes'

    const preview = keys.slice(0, 3).map((key) => {
      const value = entity.attributes[key]
      const displayValue =
        typeof value === 'string' && value.length > 50
          ? `${value.substring(0, 50)}...`
          : String(value)
      return `${key}: ${displayValue}`
    })

    if (keys.length > 3) {
      preview.push(`... +${keys.length - 3} more`)
    }

    return preview.join(', ')
  })()

  const handleSave = async () => {
    setError(null)
    setIsSaving(true)

    try {
      const parsedAttributes = JSON.parse(editedAttributes)
      const result = await updateEntity(entity.id, {
        attributes: parsedAttributes,
      })

      if (result.success) {
        setIsEditing(false)
      } else {
        setError(result.error || 'Failed to save')
      }
    } catch {
      setError('Invalid JSON format')
    } finally {
      setIsSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!confirm(`Delete "${entity.name}"? This action can be undone by an admin.`)) {
      return
    }

    setIsDeleting(true)
    const result = await deleteEntity(entity.id)

    if (!result.success) {
      setError(result.error || 'Failed to delete')
      setIsDeleting(false)
    }
    // If successful, the component will unmount due to revalidation
  }

  return (
    <div
      className={`border-2 rounded-lg p-4 transition-all hover:shadow-md ${domainColors[entity.domain]}`}
    >
      <div className="flex items-start justify-between mb-2">
        <div className="flex-1">
          <h3 className="text-lg font-semibold text-gray-900 mb-1">
            {entity.name}
          </h3>
          <div className="flex items-center gap-2 mb-2">
            <span
              className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${domainBadgeColors[entity.domain]}`}
            >
              {entity.domain}
            </span>
            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800">
              {entity.type}
            </span>
            {entity.status !== 'active' && (
              <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-200 text-gray-600">
                {entity.status}
              </span>
            )}
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex gap-1">
          <button
            onClick={() => setIsEditing(!isEditing)}
            className="p-1.5 text-gray-500 hover:text-blue-600 hover:bg-blue-100 rounded transition-colors"
            title="Edit attributes"
          >
            <svg
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"
              />
            </svg>
          </button>
          <button
            onClick={handleDelete}
            disabled={isDeleting}
            className="p-1.5 text-gray-500 hover:text-red-600 hover:bg-red-100 rounded transition-colors disabled:opacity-50"
            title="Delete entity"
          >
            {isDeleting ? (
              <svg
                className="w-4 h-4 animate-spin"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                />
              </svg>
            ) : (
              <svg
                className="w-4 h-4"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                />
              </svg>
            )}
          </button>
        </div>
      </div>

      {/* Attributes Section */}
      <div className="text-sm text-gray-600 mb-2">
        <span className="font-medium">Attributes:</span>
        {isEditing ? (
          <div className="mt-2">
            <textarea
              value={editedAttributes}
              onChange={(e) => setEditedAttributes(e.target.value)}
              className="w-full h-32 text-xs font-mono bg-white border border-gray-300 rounded p-2 focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              placeholder='{"key": "value"}'
            />
            {error && <p className="text-red-500 text-xs mt-1">{error}</p>}
            <div className="flex gap-2 mt-2">
              <button
                onClick={handleSave}
                disabled={isSaving}
                className="px-3 py-1 text-xs bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                {isSaving ? 'Saving...' : 'Save'}
              </button>
              <button
                onClick={() => {
                  setIsEditing(false)
                  setEditedAttributes(JSON.stringify(entity.attributes, null, 2))
                  setError(null)
                }}
                className="px-3 py-1 text-xs bg-gray-200 text-gray-700 rounded hover:bg-gray-300 transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="mt-1 text-xs font-mono bg-white/50 rounded p-2 break-words">
            {attributesPreview}
          </div>
        )}
      </div>

      <div className="text-xs text-gray-500 mt-3">
        Created: {new Date(entity.created_at).toLocaleDateString()}
      </div>

      {/* Toggle Comments Button */}
      <div className="mt-3 pt-3 border-t border-gray-200">
        <button
          onClick={() => setShowComments(!showComments)}
          className="text-sm text-blue-600 hover:text-blue-800 font-medium transition-colors flex items-center gap-1"
        >
          <svg
            className={`w-4 h-4 transition-transform ${showComments ? 'rotate-90' : ''}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M9 5l7 7-7 7"
            />
          </svg>
          {showComments ? 'Hide Comments' : 'Show Comments'}
        </button>
      </div>

      {/* Comments Section */}
      {showComments && <CommentSection entityId={entity.id} />}
    </div>
  )
}
