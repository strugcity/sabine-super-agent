'use client'

import { useState, useEffect } from 'react'
import { createClient } from '@supabase/supabase-js'

// Create supabase client directly to avoid any import issues
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
const supabaseKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ''
const supabase = createClient(supabaseUrl, supabaseKey)

interface AgentEvent {
  id: string
  task_id: string | null
  role: string | null
  event_type: string
  content: string
  created_at: string
}

interface Task {
  id: string
  role: string
  status: string
  priority: number
  payload: Record<string, unknown>
  created_at: string
}

export default function GodViewDashboard() {
  const [events, setEvents] = useState<AgentEvent[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const [activeTab, setActiveTab] = useState<'events' | 'tasks'>('events')

  // Fetch initial data
  useEffect(() => {
    const fetchData = async () => {
      // Fetch events
      const { data: eventsData } = await supabase
        .from('agent_events')
        .select('*')
        .order('created_at', { ascending: false })
        .limit(50)

      if (eventsData) {
        setEvents(eventsData.reverse())
      }

      // Fetch tasks
      const { data: tasksData } = await supabase
        .from('task_queue')
        .select('*')
        .order('created_at', { ascending: false })

      if (tasksData) {
        setTasks(tasksData)
      }
    }

    fetchData()
  }, [])

  // Subscribe to realtime events
  useEffect(() => {
    const channel = supabase
      .channel('realtime_events')
      .on(
        'postgres_changes',
        { event: 'INSERT', schema: 'public', table: 'agent_events' },
        (payload) => {
          setEvents((prev) => [...prev, payload.new as AgentEvent].slice(-50))
        }
      )
      .on(
        'postgres_changes',
        { event: '*', schema: 'public', table: 'task_queue' },
        (payload) => {
          if (payload.eventType === 'INSERT') {
            setTasks((prev) => [payload.new as Task, ...prev])
          } else if (payload.eventType === 'UPDATE') {
            setTasks((prev) =>
              prev.map((t) => (t.id === payload.new.id ? (payload.new as Task) : t))
            )
          }
        }
      )
      .subscribe((status) => {
        setIsConnected(status === 'SUBSCRIBED')
      })

    return () => {
      supabase.removeChannel(channel)
    }
  }, [])

  const formatTime = (ts: string) => {
    return new Date(ts).toLocaleTimeString()
  }

  const getRoleBadge = (role: string | null) => {
    const colors: Record<string, string> = {
      'SABINE_ARCHITECT': 'bg-violet-500/20 text-violet-300',
      'backend-architect-sabine': 'bg-blue-500/20 text-blue-300',
      'qa-security-sabine': 'bg-red-500/20 text-red-300',
    }
    return colors[role || ''] || 'bg-gray-500/20 text-gray-300'
  }

  const getStatusBadge = (status: string) => {
    const colors: Record<string, string> = {
      'completed': 'bg-green-500/20 text-green-300',
      'in_progress': 'bg-blue-500/20 text-blue-300',
      'queued': 'bg-gray-500/20 text-gray-300',
      'failed': 'bg-red-500/20 text-red-300',
    }
    return colors[status] || 'bg-gray-500/20 text-gray-300'
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white p-6">
      {/* Header */}
      <header className="mb-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">SABINE Control</h1>
            <p className="text-gray-400">God View Dashboard</p>
          </div>
          <div className="flex items-center gap-2">
            <div className={`w-3 h-3 rounded-full ${isConnected ? 'bg-green-400' : 'bg-red-400'}`} />
            <span className="text-sm text-gray-400">
              {isConnected ? 'Connected' : 'Disconnected'}
            </span>
          </div>
        </div>
      </header>

      {/* Tabs */}
      <div className="flex gap-2 mb-6">
        <button
          onClick={() => setActiveTab('events')}
          className={`px-4 py-2 rounded-lg ${
            activeTab === 'events' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400'
          }`}
        >
          Events ({events.length})
        </button>
        <button
          onClick={() => setActiveTab('tasks')}
          className={`px-4 py-2 rounded-lg ${
            activeTab === 'tasks' ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400'
          }`}
        >
          Tasks ({tasks.length})
        </button>
      </div>

      {/* Content */}
      {activeTab === 'events' && (
        <div className="space-y-3">
          <h2 className="text-lg font-semibold">Live Event Stream</h2>
          <div className="bg-gray-900 rounded-lg border border-gray-800 max-h-[600px] overflow-y-auto">
            {events.length === 0 ? (
              <p className="p-4 text-gray-500">No events yet...</p>
            ) : (
              events.map((event) => (
                <div
                  key={event.id}
                  className="p-4 border-b border-gray-800 last:border-b-0"
                >
                  <div className="flex items-center gap-2 mb-2">
                    <span className={`px-2 py-0.5 text-xs rounded-full ${getRoleBadge(event.role)}`}>
                      {event.role || 'System'}
                    </span>
                    <span className="text-xs text-gray-500">{event.event_type}</span>
                    <span className="text-xs text-gray-600 ml-auto">
                      {formatTime(event.created_at)}
                    </span>
                  </div>
                  <p className="text-sm text-gray-300">{event.content}</p>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {activeTab === 'tasks' && (
        <div className="space-y-3">
          <h2 className="text-lg font-semibold">Task Queue</h2>
          <div className="grid gap-4">
            {tasks.length === 0 ? (
              <p className="text-gray-500">No tasks yet...</p>
            ) : (
              tasks.map((task) => (
                <div
                  key={task.id}
                  className="p-4 bg-gray-900 rounded-lg border border-gray-800"
                >
                  <div className="flex items-center gap-2 mb-2">
                    <span className={`px-2 py-0.5 text-xs rounded-full ${getRoleBadge(task.role)}`}>
                      {task.role}
                    </span>
                    <span className={`px-2 py-0.5 text-xs rounded-full ${getStatusBadge(task.status)}`}>
                      {task.status}
                    </span>
                    <span className="text-xs text-gray-500 ml-auto">
                      P{task.priority}
                    </span>
                  </div>
                  <p className="text-sm font-medium text-white">
                    {(task.payload as Record<string, unknown>)?.title as string || 'Untitled Task'}
                  </p>
                  <p className="text-xs text-gray-500 mt-1">
                    {task.id.slice(0, 8)}... • {formatTime(task.created_at)}
                  </p>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* Footer */}
      <footer className="mt-8 pt-4 border-t border-gray-800 text-center text-sm text-gray-500">
        SABINE Super Agent • Strug City • Project Dream Team
      </footer>
    </div>
  )
}
