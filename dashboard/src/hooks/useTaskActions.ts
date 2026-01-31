'use client'

import { useState, useCallback } from 'react'

// Configuration from environment
const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const API_KEY = process.env.NEXT_PUBLIC_API_KEY || ''

interface ApiResponse<T = unknown> {
  success: boolean
  data?: T
  error?: string
}

interface TaskResult {
  task_id: string
  status: string
  message?: string
}

interface DispatchResult {
  dispatched: boolean
  task_id?: string
  role?: string
  message?: string
}

interface OrchestrationStatus {
  task_counts: Record<string, number>
  unblocked_count: number
  total_tasks: number
  timestamp: string
}

/**
 * Hook for interacting with the SABINE task orchestration API
 */
export function useTaskActions() {
  const [loadingTaskId, setLoadingTaskId] = useState<string | null>(null)
  const [isDispatchLoading, setIsDispatchLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  /**
   * Make an authenticated API request
   */
  const apiRequest = useCallback(async <T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<ApiResponse<T>> => {
    try {
      const headers: HeadersInit = {
        'Content-Type': 'application/json',
        ...(API_KEY && { 'X-API-Key': API_KEY }),
        ...options.headers,
      }

      const response = await fetch(`${API_BASE_URL}${endpoint}`, {
        ...options,
        headers,
      })

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        throw new Error(errorData.detail || `HTTP ${response.status}`)
      }

      const data = await response.json()
      return { success: true, data }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error'
      console.error(`API Error: ${endpoint}`, message)
      setError(message)
      return { success: false, error: message }
    }
  }, [])

  /**
   * Approve a task that is awaiting approval
   */
  const approveTask = useCallback(async (taskId: string): Promise<ApiResponse<TaskResult>> => {
    setLoadingTaskId(taskId)
    setError(null)

    try {
      const result = await apiRequest<TaskResult>(`/tasks/${taskId}/approve`, {
        method: 'POST',
      })
      return result
    } finally {
      setLoadingTaskId(null)
    }
  }, [apiRequest])

  /**
   * Complete a task with optional result data
   */
  const completeTask = useCallback(async (
    taskId: string,
    result?: Record<string, unknown>
  ): Promise<ApiResponse<TaskResult>> => {
    setLoadingTaskId(taskId)
    setError(null)

    try {
      const response = await apiRequest<TaskResult>(`/tasks/${taskId}/complete`, {
        method: 'POST',
        body: JSON.stringify({ result }),
      })
      return response
    } finally {
      setLoadingTaskId(null)
    }
  }, [apiRequest])

  /**
   * Fail a task with an error message
   */
  const failTask = useCallback(async (
    taskId: string,
    errorMessage: string
  ): Promise<ApiResponse<TaskResult>> => {
    setLoadingTaskId(taskId)
    setError(null)

    try {
      const response = await apiRequest<TaskResult>(`/tasks/${taskId}/fail`, {
        method: 'POST',
        body: JSON.stringify({ error: errorMessage }),
      })
      return response
    } finally {
      setLoadingTaskId(null)
    }
  }, [apiRequest])

  /**
   * Dispatch the next available task to an agent
   */
  const dispatchNext = useCallback(async (
    role?: string
  ): Promise<ApiResponse<DispatchResult>> => {
    setIsDispatchLoading(true)
    setError(null)

    try {
      const endpoint = role
        ? `/tasks/dispatch?role=${encodeURIComponent(role)}`
        : '/tasks/dispatch'

      const result = await apiRequest<DispatchResult>(endpoint, {
        method: 'POST',
      })
      return result
    } finally {
      setIsDispatchLoading(false)
    }
  }, [apiRequest])

  /**
   * Get orchestration status (task counts by status, unblocked count)
   */
  const getStatus = useCallback(async (): Promise<ApiResponse<OrchestrationStatus>> => {
    return apiRequest<OrchestrationStatus>('/orchestration/status')
  }, [apiRequest])

  /**
   * Create a new task
   */
  const createTask = useCallback(async (task: {
    role: string
    payload: Record<string, unknown>
    priority?: number
    depends_on?: string[]
    created_by?: string
    session_id?: string
  }): Promise<ApiResponse<{ task_id: string }>> => {
    setError(null)
    return apiRequest<{ task_id: string }>('/tasks', {
      method: 'POST',
      body: JSON.stringify(task),
    })
  }, [apiRequest])

  /**
   * Get a specific task by ID
   */
  const getTask = useCallback(async (taskId: string): Promise<ApiResponse<Record<string, unknown>>> => {
    return apiRequest<Record<string, unknown>>(`/tasks/${taskId}`)
  }, [apiRequest])

  /**
   * Clear the error state
   */
  const clearError = useCallback(() => {
    setError(null)
  }, [])

  return {
    // Actions
    approveTask,
    completeTask,
    failTask,
    dispatchNext,
    getStatus,
    createTask,
    getTask,

    // State
    loadingTaskId,
    isDispatchLoading,
    error,
    clearError,
  }
}

export type { ApiResponse, TaskResult, DispatchResult, OrchestrationStatus }
