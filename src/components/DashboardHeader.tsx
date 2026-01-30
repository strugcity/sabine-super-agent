'use client'

import { useState } from 'react'
import { NewEntityModal } from './NewEntityModal'

interface DashboardHeaderProps {
  totalEntities: number
  totalMemories: number
}

export function DashboardHeader({
  totalEntities,
  totalMemories,
}: DashboardHeaderProps) {
  const [isModalOpen, setIsModalOpen] = useState(false)

  return (
    <>
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold text-gray-900">
                Memory Dashboard
              </h1>
              <p className="mt-2 text-sm text-gray-600">
                Context Engine - Entities & Memories
              </p>
            </div>
            <div className="flex items-center gap-6">
              <div className="flex gap-4">
                <div className="text-center">
                  <div className="text-2xl font-bold text-gray-900">
                    {totalEntities}
                  </div>
                  <div className="text-xs text-gray-600">Entities</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-gray-900">
                    {totalMemories}
                  </div>
                  <div className="text-xs text-gray-600">Memories</div>
                </div>
              </div>
              <button
                onClick={() => setIsModalOpen(true)}
                className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors font-medium"
              >
                <svg
                  className="w-5 h-5"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M12 4v16m8-8H4"
                  />
                </svg>
                New Entity
              </button>
            </div>
          </div>
        </div>
      </header>

      <NewEntityModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
      />
    </>
  )
}
