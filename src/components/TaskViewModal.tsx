/**
 * TaskViewModal - Kanban Task View Modal for Project Sabine
 *
 * GOVERNANCE: This component is UI-only (Project Sabine frontend).
 * Compliant with Strug City Constitution Section II.
 *
 * Features:
 * - Slider positioned at TOP of modal for easy access
 * - Kanban board layout with drag-and-drop (future)
 * - Responsive design for mobile/desktop
 */
'use client'

import { useState } from 'react'

interface TaskViewModalProps {
  isOpen: boolean
  onClose: () => void
}

interface Task {
  id: string
  title: string
  description: string
  status: 'pending' | 'in-progress' | 'review' | 'completed'
  assignee?: string
  priority: 'low' | 'medium' | 'high'
  dueDate?: string
}

// Mock task data - replace with actual data from backend
const mockTasks: Task[] = [
  {
    id: '1',
    title: 'Implement Phase 3 Task Queue',
    description: 'Create the task_queue table in Supabase with columns for role assignment',
    status: 'in-progress',
    assignee: 'backend-architect-sabine',
    priority: 'high',
    dueDate: '2026-02-10'
  },
  {
    id: '2',
    title: 'Add LangSmith Tracing',
    description: 'Integrate LangSmith for observability and debugging',
    status: 'pending',
    assignee: 'data-ai-engineer-sabine',
    priority: 'medium',
    dueDate: '2026-02-12'
  },
  {
    id: '3',
    title: 'Create God View Dashboard',
    description: 'Build GET /orchestration/status endpoint',
    status: 'review',
    assignee: 'frontend-ops-sabine',
    priority: 'medium',
    dueDate: '2026-02-08'
  },
  {
    id: '4',
    title: 'Memory Consolidation Service',
    description: 'Implement nightly memory consolidation',
    status: 'completed',
    priority: 'high',
    dueDate: '2026-02-05'
  }
]

const viewTypes = [
  { id: 'kanban', label: 'Kanban Board', icon: '📋' },
  { id: 'list', label: 'List View', icon: '📝' },
  { id: 'timeline', label: 'Timeline', icon: '📅' },
  { id: 'calendar', label: 'Calendar', icon: '🗓️' }
]

const statusColumns = [
  { id: 'pending', label: 'Pending', color: 'bg-yellow-100 border-yellow-300' },
  { id: 'in-progress', label: 'In Progress', color: 'bg-blue-100 border-blue-300' },
  { id: 'review', label: 'Review', color: 'bg-purple-100 border-purple-300' },
  { id: 'completed', label: 'Completed', color: 'bg-green-100 border-green-300' }
]

const priorityColors = {
  low: 'bg-gray-100 text-gray-700',
  medium: 'bg-yellow-100 text-yellow-700',
  high: 'bg-red-100 text-red-700'
}

export function TaskViewModal({ isOpen, onClose }: TaskViewModalProps) {
  const [currentView, setCurrentView] = useState(0)
  
  if (!isOpen) return null

  const currentViewType = viewTypes[currentView]

  const renderKanbanView = () => (
    <div className="grid grid-cols-1 md:grid-cols-4 gap-4 h-full">
      {statusColumns.map((column) => {
        const columnTasks = mockTasks.filter(task => task.status === column.id)
        
        return (
          <div key={column.id} className={`rounded-lg border-2 ${column.color} p-4`}>
            <h3 className="font-semibold text-gray-800 mb-3 flex items-center justify-between">
              {column.label}
              <span className="text-sm bg-white rounded-full px-2 py-1">
                {columnTasks.length}
              </span>
            </h3>
            
            <div className="space-y-3">
              {columnTasks.map((task) => (
                <div
                  key={task.id}
                  className="bg-white rounded-lg border border-gray-200 p-3 shadow-sm hover:shadow-md transition-shadow cursor-pointer"
                >
                  <h4 className="font-medium text-gray-900 text-sm mb-2">
                    {task.title}
                  </h4>
                  <p className="text-xs text-gray-600 mb-3 line-clamp-2">
                    {task.description}
                  </p>
                  
                  <div className="flex items-center justify-between">
                    <span className={`text-xs px-2 py-1 rounded-full ${priorityColors[task.priority]}`}>
                      {task.priority}
                    </span>
                    {task.dueDate && (
                      <span className="text-xs text-gray-500">
                        {new Date(task.dueDate).toLocaleDateString()}
                      </span>
                    )}
                  </div>
                  
                  {task.assignee && (
                    <div className="mt-2 text-xs text-gray-500">
                      👤 {task.assignee}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )

  const renderListView = () => (
    <div className="space-y-3">
      {mockTasks.map((task) => (
        <div
          key={task.id}
          className="bg-white rounded-lg border border-gray-200 p-4 hover:shadow-md transition-shadow"
        >
          <div className="flex items-start justify-between">
            <div className="flex-1">
              <h4 className="font-medium text-gray-900 mb-1">{task.title}</h4>
              <p className="text-sm text-gray-600 mb-2">{task.description}</p>
              
              <div className="flex items-center gap-3">
                <span className={`text-xs px-2 py-1 rounded-full ${priorityColors[task.priority]}`}>
                  {task.priority}
                </span>
                <span className="text-xs px-2 py-1 rounded-full bg-gray-100 text-gray-700">
                  {task.status}
                </span>
                {task.dueDate && (
                  <span className="text-xs text-gray-500">
                    Due: {new Date(task.dueDate).toLocaleDateString()}
                  </span>
                )}
              </div>
            </div>
            
            {task.assignee && (
              <div className="text-xs text-gray-500 ml-4">
                👤 {task.assignee}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  )

  const renderCurrentView = () => {
    switch (currentViewType.id) {
      case 'kanban':
        return renderKanbanView()
      case 'list':
        return renderListView()
      case 'timeline':
        return (
          <div className="flex items-center justify-center h-64 text-gray-500">
            Timeline view coming soon...
          </div>
        )
      case 'calendar':
        return (
          <div className="flex items-center justify-center h-64 text-gray-500">
            Calendar view coming soon...
          </div>
        )
      default:
        return renderKanbanView()
    }
  }

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-black bg-opacity-50 transition-opacity"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="flex min-h-full items-center justify-center p-4">
        <div className="relative bg-white rounded-lg shadow-xl max-w-7xl w-full max-h-[90vh] flex flex-col">
          {/* Header with Slider - POSITIONED AT TOP */}
          <div className="flex items-center justify-between p-6 border-b border-gray-200">
            <h2 className="text-xl font-semibold text-gray-900">
              Task View - {currentViewType.label}
            </h2>
            
            {/* VIEW SLIDER - POSITIONED AT TOP FOR EASY ACCESS */}
            <div className="flex items-center gap-4">
              <div className="flex items-center bg-gray-100 rounded-lg p-1">
                <button
                  onClick={() => setCurrentView(Math.max(0, currentView - 1))}
                  disabled={currentView === 0}
                  className="p-2 text-gray-600 hover:text-gray-900 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  title="Previous view"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                  </svg>
                </button>
                
                <div className="flex items-center gap-2 px-3 py-1 bg-white rounded-md shadow-sm min-w-[120px] justify-center">
                  <span>{currentViewType.icon}</span>
                  <span className="text-sm font-medium">{currentViewType.label}</span>
                </div>
                
                <button
                  onClick={() => setCurrentView(Math.min(viewTypes.length - 1, currentView + 1))}
                  disabled={currentView === viewTypes.length - 1}
                  className="p-2 text-gray-600 hover:text-gray-900 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                  title="Next view"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                  </svg>
                </button>
              </div>
              
              {/* View indicator dots */}
              <div className="flex gap-1">
                {viewTypes.map((_, index) => (
                  <button
                    key={index}
                    onClick={() => setCurrentView(index)}
                    className={`w-2 h-2 rounded-full transition-colors ${
                      index === currentView ? 'bg-blue-600' : 'bg-gray-300 hover:bg-gray-400'
                    }`}
                    title={viewTypes[index].label}
                  />
                ))}
              </div>
            </div>

            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-600 transition-colors"
            >
              <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* Content Area */}
          <div className="flex-1 p-6 overflow-auto">
            {renderCurrentView()}
          </div>
        </div>
      </div>
    </div>
  )
}