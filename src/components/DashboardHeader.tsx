/**
 * DashboardHeader - Memory Dashboard Header for Project Sabine
 *
 * GOVERNANCE: This component is UI-only (Project Sabine frontend).
 * Compliant with Strug City Constitution Section II.
 */
'use client'

import { useState } from 'react'
import { NewEntityModal } from './NewEntityModal'
import { ModeToggle } from './ui/ModeToggle'

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
      <header className="bg-white dark:bg-gray-900 border-b border-gray-200 dark:border-gray-800 transition-colors">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex items-center justify-between">
            <div>
              <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
                Memory Dashboard
              </h1>
              <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
                Context Engine - Entities & Memories
              </p>
            </div>
            <div className="flex items-center gap-6">
              <div className="flex gap-4">
                <div className="text-center">
                  <div className="text-2xl font-bold text-gray-900 dark:text-white">
                    {totalEntities}
                  </div>
                  <div className="text-xs text-gray-600 dark:text-gray-400">Entities</div>
                </div>
                <div className="text-center">
                  <div className="text-2xl font-bold text-gray-900 dark:text-white">
                    {totalMemories}
                  </div>
                  <div className="text-xs text-gray-600 dark:text-gray-400">Memories</div>
                </div>
              </div>
              <ModeToggle />
              <button
                onClick={() => setIsModalOpen(true)}
                className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 dark:bg-blue-500 dark:hover:bg-blue-600 transition-colors font-medium"
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
