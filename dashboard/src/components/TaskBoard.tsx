'use client'

import { useEffect, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import {
  Clock,
  Play,
  CheckCircle,
  XCircle,
  Pause,
  RefreshCw,
  ChevronDown,
  ChevronUp,
  Loader2,
  AlertCircle
} from 'lucide-react'
import { supabase, Task, roleDisplayNames } from '@/lib/supabase'
import { useTaskActions } from '@/hooks/useTaskActions'

// Status configuration
const statusConfig = {
  queued: {
    label: 'Queued',
    icon: Clock,
    color: 'text-gray-400',
    bgColor: 'bg-gray-800',
    borderColor: 'border-gray-700',
  },
  in_progress: {
    label: 'In Progress',
    icon: Play,
    color: 'text-blue-400',
    bgColor: 'bg-blue-900/20',
    borderColor: 'border-blue-500/50',
  },
  completed: {
    label: 'Completed',
    icon: CheckCircle,
    color: 'text-green-400',
    bgColor: 'bg-green-900/20',
    borderColor: 'border-green-500/50',
  },
  failed: {
    label: 'Failed',
    icon: XCircle,
    color: 'text-red-400',
    bgColor: 'bg-red-900/20',
    borderColor: 'border-red-500/50',
  },
  awaiting_approval: {
    label: 'Awaiting Approval',
    icon: Pause,
    color: 'text-amber-400',
    bgColor: 'bg-amber-900/20',
    borderColor: 'border-amber-500/50',
  },
}

interface TaskCardProps {
  task: Task
  onApprove?: (taskId: string) => void
  onDispatch?: () => void
  isLoading?: boolean
}

function TaskCard({ task, onApprove, onDispatch, isLoading }: TaskCardProps) {
  const [isExpanded, setIsExpanded] = useState(false)
  const config = statusConfig[task.status]
  const StatusIcon = config.icon

  const getRoleBadgeColor = (role: string) => {
    const colors: Record<string, string> = {
      'SABINE_ARCHITECT': 'bg-violet-500/20 text-violet-300 border-violet-500/30',
      'backend-architect-sabine': 'bg-blue-500/20 text-blue-300 border-blue-500/30',
      'frontend-ops-sabine': 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
      'data-ai-engineer-sabine': 'bg-amber-500/20 text-amber-300 border-amber-500/30',
      'product-manager-sabine': 'bg-pink-500/20 text-pink-300 border-pink-500/30',
      'qa-security-sabine': 'bg-red-500/20 text-red-300 border-red-500/30',
    }
    return colors[role] || 'bg-gray-500/20 text-gray-300 border-gray-500/30'
  }

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr)
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className={`p-4 rounded-lg border ${config.bgColor} ${config.borderColor} transition-all hover:border-opacity-100`}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <StatusIcon className={`w-4 h-4 flex-shrink-0 ${config.color}`} />
          <span className={`px-2 py-0.5 text-xs font-medium rounded border ${getRoleBadgeColor(task.role)}`}>
            {roleDisplayNames[task.role] || task.role.split('-')[0]}
          </span>
        </div>
        <span className="text-xs text-gray-500 flex-shrink-0">
          #{task.id.slice(0, 8)}
        </span>
      </div>

      {/* Task Info */}
      <div className="mt-3">
        {task.payload?.title && (
          <h4 className="text-sm font-medium text-white mb-1">
            {task.payload.title}
          </h4>
        )}
        {task.payload?.description && (
          <p className="text-xs text-gray-400 line-clamp-2">
            {task.payload.description}
          </p>
        )}
      </div>

      {/* Priority & Dependencies */}
      <div className="flex items-center gap-2 mt-3">
        <span className={`px-2 py-0.5 text-xs rounded ${
          task.priority >= 8 ? 'bg-red-500/20 text-red-300' :
          task.priority >= 5 ? 'bg-amber-500/20 text-amber-300' :
          'bg-gray-500/20 text-gray-300'
        }`}>
          P{task.priority}
        </span>
        {task.depends_on && task.depends_on.length > 0 && (
          <span className="text-xs text-gray-500">
            {task.depends_on.length} dep{task.depends_on.length > 1 ? 's' : ''}
          </span>
        )}
      </div>

      {/* Actions */}
      {task.status === 'awaiting_approval' && onApprove && (
        <button
          onClick={() => onApprove(task.id)}
          disabled={isLoading}
          className="mt-3 w-full px-3 py-2 text-sm font-medium rounded-lg bg-green-600 hover:bg-green-500 text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
        >
          {isLoading ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <CheckCircle className="w-4 h-4" />
          )}
          Approve
        </button>
      )}

      {/* Expandable Details */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="mt-3 flex items-center gap-1 text-xs text-gray-500 hover:text-gray-300 transition-colors"
      >
        {isExpanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        {isExpanded ? 'Less' : 'More'}
      </button>

      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="pt-3 mt-3 border-t border-gray-700 space-y-2 text-xs">
              <div className="flex justify-between">
                <span className="text-gray-500">Created</span>
                <span className="text-gray-300">{formatDate(task.created_at)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Updated</span>
                <span className="text-gray-300">{formatDate(task.updated_at)}</span>
              </div>
              {task.created_by && (
                <div className="flex justify-between">
                  <span className="text-gray-500">Created by</span>
                  <span className="text-gray-300">{task.created_by}</span>
                </div>
              )}
              {task.session_id && (
                <div className="flex justify-between">
                  <span className="text-gray-500">Session</span>
                  <code className="text-cyan-400">{task.session_id.slice(0, 8)}...</code>
                </div>
              )}
              {task.error && (
                <div className="mt-2 p-2 bg-red-900/30 rounded border border-red-500/30">
                  <p className="text-red-300 flex items-center gap-1">
                    <AlertCircle className="w-3 h-3" />
                    Error
                  </p>
                  <p className="mt-1 text-gray-300">{task.error}</p>
                </div>
              )}
              {task.result && (
                <details className="mt-2">
                  <summary className="text-gray-500 cursor-pointer hover:text-gray-400">
                    View result
                  </summary>
                  <pre className="mt-1 p-2 text-xs bg-black/30 rounded overflow-x-auto max-h-32">
                    {JSON.stringify(task.result, null, 2)}
                  </pre>
                </details>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}

interface TaskColumnProps {
  status: Task['status']
  tasks: Task[]
  onApprove?: (taskId: string) => void
  onDispatch?: () => void
  loadingTaskId?: string | null
}

function TaskColumn({ status, tasks, onApprove, onDispatch, loadingTaskId }: TaskColumnProps) {
  const config = statusConfig[status]
  const StatusIcon = config.icon

  return (
    <div className="flex flex-col min-w-[280px] max-w-[320px] flex-1">
      {/* Column Header */}
      <div className={`flex items-center gap-2 px-4 py-3 rounded-t-lg ${config.bgColor} border ${config.borderColor} border-b-0`}>
        <StatusIcon className={`w-5 h-5 ${config.color}`} />
        <h3 className={`font-medium ${config.color}`}>{config.label}</h3>
        <span className="ml-auto px-2 py-0.5 text-xs rounded-full bg-gray-700 text-gray-300">
          {tasks.length}
        </span>
      </div>

      {/* Task List */}
      <div className={`flex-1 p-3 space-y-3 rounded-b-lg border ${config.borderColor} border-t-0 bg-gray-900/50 overflow-y-auto max-h-[600px]`}>
        <AnimatePresence mode="popLayout">
          {tasks.map((task) => (
            <TaskCard
              key={task.id}
              task={task}
              onApprove={onApprove}
              onDispatch={onDispatch}
              isLoading={loadingTaskId === task.id}
            />
          ))}
        </AnimatePresence>

        {tasks.length === 0 && (
          <div className="flex flex-col items-center justify-center py-8 text-gray-500">
            <StatusIcon className="w-8 h-8 mb-2 opacity-30" />
            <p className="text-sm">No tasks</p>
          </div>
        )}
      </div>
    </div>
  )
}

export default function TaskBoard() {
  const [tasks, setTasks] = useState<Task[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const { approveTask, dispatchNext, loadingTaskId } = useTaskActions()

  // Fetch initial tasks
  useEffect(() => {
    const fetchTasks = async () => {
      setIsLoading(true)
      try {
        const { data, error } = await supabase
          .from('task_queue')
          .select('*')
          .order('created_at', { ascending: false })

        if (error) throw error
        setTasks(data || [])
      } catch (err) {
        console.error('Error fetching tasks:', err)
        setError('Failed to load tasks')
      } finally {
        setIsLoading(false)
      }
    }

    fetchTasks()
  }, [])

  // Subscribe to realtime updates
  useEffect(() => {
    const channel = supabase
      .channel('task_queue_realtime')
      .on(
        'postgres_changes',
        {
          event: '*',
          schema: 'public',
          table: 'task_queue',
        },
        (payload) => {
          if (payload.eventType === 'INSERT') {
            setTasks((prev) => [payload.new as Task, ...prev])
          } else if (payload.eventType === 'UPDATE') {
            setTasks((prev) =>
              prev.map((t) => (t.id === payload.new.id ? (payload.new as Task) : t))
            )
          } else if (payload.eventType === 'DELETE') {
            setTasks((prev) => prev.filter((t) => t.id !== payload.old.id))
          }
        }
      )
      .subscribe()

    return () => {
      supabase.removeChannel(channel)
    }
  }, [])

  const handleApprove = async (taskId: string) => {
    const result = await approveTask(taskId)
    if (result.success) {
      // Task will be updated via realtime subscription
    }
  }

  const handleDispatch = async () => {
    await dispatchNext()
  }

  // Group tasks by status
  const tasksByStatus = {
    queued: tasks.filter((t) => t.status === 'queued'),
    awaiting_approval: tasks.filter((t) => t.status === 'awaiting_approval'),
    in_progress: tasks.filter((t) => t.status === 'in_progress'),
    completed: tasks.filter((t) => t.status === 'completed'),
    failed: tasks.filter((t) => t.status === 'failed'),
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 text-blue-400 animate-spin" />
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-64 text-red-400">
        <AlertCircle className="w-8 h-8 mb-2" />
        <p>{error}</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {/* Header with Dispatch Button */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <Clock className="w-5 h-5 text-blue-400" />
          Task Queue
        </h2>
        <button
          onClick={handleDispatch}
          className="px-4 py-2 text-sm font-medium rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition-colors flex items-center gap-2"
        >
          <RefreshCw className="w-4 h-4" />
          Dispatch Next
        </button>
      </div>

      {/* Task Columns */}
      <div className="flex gap-4 overflow-x-auto pb-4">
        <TaskColumn
          status="queued"
          tasks={tasksByStatus.queued}
          onApprove={handleApprove}
          loadingTaskId={loadingTaskId}
        />
        <TaskColumn
          status="awaiting_approval"
          tasks={tasksByStatus.awaiting_approval}
          onApprove={handleApprove}
          loadingTaskId={loadingTaskId}
        />
        <TaskColumn
          status="in_progress"
          tasks={tasksByStatus.in_progress}
          loadingTaskId={loadingTaskId}
        />
        <TaskColumn
          status="completed"
          tasks={tasksByStatus.completed}
          loadingTaskId={loadingTaskId}
        />
        <TaskColumn
          status="failed"
          tasks={tasksByStatus.failed}
          loadingTaskId={loadingTaskId}
        />
      </div>
    </div>
  )
}
