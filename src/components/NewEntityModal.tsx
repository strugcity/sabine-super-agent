'use client'

import { useState } from 'react'
import { DomainEnum } from '@/lib/types/database'
import { createEntity } from '@/app/dashboard/memory/actions'

interface NewEntityModalProps {
  isOpen: boolean
  onClose: () => void
}

const domainOptions: { value: DomainEnum; label: string; emoji: string }[] = [
  { value: 'work', label: 'Work', emoji: '💼' },
  { value: 'family', label: 'Family', emoji: '👨‍👩‍👧‍👦' },
  { value: 'personal', label: 'Personal', emoji: '🧘' },
  { value: 'logistics', label: 'Logistics', emoji: '📦' },
]

const typeOptions = [
  'project',
  'person',
  'event',
  'document',
  'location',
  'task',
  'other',
]

export function NewEntityModal({ isOpen, onClose }: NewEntityModalProps) {
  const [name, setName] = useState('')
  const [type, setType] = useState('project')
  const [domain, setDomain] = useState<DomainEnum>('work')
  const [attributes, setAttributes] = useState('{}')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setIsSubmitting(true)

    try {
      // Validate JSON
      const parsedAttributes = JSON.parse(attributes)

      const result = await createEntity({
        name,
        type,
        domain,
        attributes: parsedAttributes,
      })

      if (result.success) {
        // Reset form and close
        setName('')
        setType('project')
        setDomain('work')
        setAttributes('{}')
        onClose()
      } else {
        setError(result.error || 'Failed to create entity')
      }
    } catch {
      setError('Invalid JSON in attributes')
    } finally {
      setIsSubmitting(false)
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black bg-opacity-50 transition-opacity"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="flex min-h-full items-center justify-center p-4">
        <div className="relative bg-white rounded-lg shadow-xl max-w-md w-full p-6">
          {/* Header */}
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xl font-semibold text-gray-900">
              Create New Entity
            </h2>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-600 transition-colors"
            >
              <svg
                className="w-6 h-6"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M6 18L18 6M6 6l12 12"
                />
              </svg>
            </button>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Name */}
            <div>
              <label
                htmlFor="name"
                className="block text-sm font-medium text-gray-700 mb-1"
              >
                Name *
              </label>
              <input
                type="text"
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                placeholder="e.g., Project Phoenix"
              />
            </div>

            {/* Domain */}
            <div>
              <label
                htmlFor="domain"
                className="block text-sm font-medium text-gray-700 mb-1"
              >
                Domain *
              </label>
              <select
                id="domain"
                value={domain}
                onChange={(e) => setDomain(e.target.value as DomainEnum)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              >
                {domainOptions.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.emoji} {opt.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Type */}
            <div>
              <label
                htmlFor="type"
                className="block text-sm font-medium text-gray-700 mb-1"
              >
                Type *
              </label>
              <select
                id="type"
                value={type}
                onChange={(e) => setType(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              >
                {typeOptions.map((t) => (
                  <option key={t} value={t}>
                    {t.charAt(0).toUpperCase() + t.slice(1)}
                  </option>
                ))}
              </select>
            </div>

            {/* Attributes */}
            <div>
              <label
                htmlFor="attributes"
                className="block text-sm font-medium text-gray-700 mb-1"
              >
                Attributes (JSON)
              </label>
              <textarea
                id="attributes"
                value={attributes}
                onChange={(e) => setAttributes(e.target.value)}
                rows={4}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-blue-500 font-mono text-sm"
                placeholder='{"deadline": "2026-03-01", "priority": "high"}'
              />
              <p className="mt-1 text-xs text-gray-500">
                Optional. Add custom key-value pairs as JSON.
              </p>
            </div>

            {/* Error */}
            {error && (
              <div className="p-3 bg-red-50 border border-red-200 rounded-md text-sm text-red-700">
                {error}
              </div>
            )}

            {/* Actions */}
            <div className="flex gap-3 pt-2">
              <button
                type="button"
                onClick={onClose}
                className="flex-1 px-4 py-2 border border-gray-300 rounded-md text-gray-700 hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isSubmitting || !name.trim()}
                className="flex-1 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {isSubmitting ? 'Creating...' : 'Create Entity'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}
