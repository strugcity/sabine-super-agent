'use client'

import { useEffect, useState, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Activity, MessageSquare, Wrench, CheckCircle, XCircle, AlertTriangle, Info, Zap, Power, Link2 } from 'lucide-react'
import { supabase, AgentEvent, roleColors, roleDisplayNames, eventEmojis } from '@/lib/supabase'

// Event type to icon mapping
const eventIcons: Record<string, React.ReactNode> = {
  'task_started': <Zap className="w-4 h-4" />,
  'task_completed': <CheckCircle className="w-4 h-4" />,
  'task_failed': <XCircle className="w-4 h-4" />,
  'agent_thought': <MessageSquare className="w-4 h-4" />,
  'tool_call': <Wrench className="w-4 h-4" />,
  'tool_result': <Activity className="w-4 h-4" />,
  'system_startup': <Power className="w-4 h-4" />,
  'system_shutdown': <Power className="w-4 h-4" />,
  'handshake': <Link2 className="w-4 h-4" />,
  'error': <AlertTriangle className="w-4 h-4" />,
  'info': <Info className="w-4 h-4" />,
}

// Event type to color class mapping
const eventColors: Record<string, string> = {
  'task_started': 'text-blue-400 bg-blue-400/10 border-blue-400/30',
  'task_completed': 'text-green-400 bg-green-400/10 border-green-400/30',
  'task_failed': 'text-red-400 bg-red-400/10 border-red-400/30',
  'agent_thought': 'text-purple-400 bg-purple-400/10 border-purple-400/30',
  'tool_call': 'text-amber-400 bg-amber-400/10 border-amber-400/30',
  'tool_result': 'text-cyan-400 bg-cyan-400/10 border-cyan-400/30',
  'system_startup': 'text-emerald-400 bg-emerald-400/10 border-emerald-400/30',
  'system_shutdown': 'text-slate-400 bg-slate-400/10 border-slate-400/30',
  'handshake': 'text-pink-400 bg-pink-400/10 border-pink-400/30',
  'error': 'text-red-500 bg-red-500/10 border-red-500/30',
  'info': 'text-blue-300 bg-blue-300/10 border-blue-300/30',
}

interface LiveLogProps {
  maxEvents?: number
  autoScroll?: boolean
}

export default function LiveLog({ maxEvents = 100, autoScroll = true }: LiveLogProps) {
  const [events, setEvents] = useState<AgentEvent[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const [isPaused, setIsPaused] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Fetch initial events
  useEffect(() => {
    const fetchEvents = async () => {
      const { data, error } = await supabase
        .from('agent_events')
        .select('*')
        .order('created_at', { ascending: false })
        .limit(maxEvents)

      if (error) {
        console.error('Error fetching events:', error)
        return
      }

      // Reverse to show oldest first, newest at bottom
      setEvents((data || []).reverse())
    }

    fetchEvents()
  }, [maxEvents])

  // Subscribe to realtime updates
  useEffect(() => {
    const channel = supabase
      .channel('agent_events_realtime')
      .on(
        'postgres_changes',
        {
          event: 'INSERT',
          schema: 'public',
          table: 'agent_events',
        },
        (payload) => {
          if (isPaused) return

          const newEvent = payload.new as AgentEvent
          setEvents((prev) => {
            const updated = [...prev, newEvent]
            // Keep only the last maxEvents
            if (updated.length > maxEvents) {
              return updated.slice(-maxEvents)
            }
            return updated
          })
        }
      )
      .subscribe((status) => {
        setIsConnected(status === 'SUBSCRIBED')
      })

    return () => {
      supabase.removeChannel(channel)
    }
  }, [isPaused, maxEvents])

  // Auto-scroll to bottom on new events
  useEffect(() => {
    if (autoScroll && scrollRef.current && !isPaused) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [events, autoScroll, isPaused])

  const formatTime = (timestamp: string) => {
    const date = new Date(timestamp)
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
  }

  const getRoleColor = (role: string | null) => {
    if (!role) return 'bg-gray-600'
    return roleColors[role] ? `bg-${roleColors[role]}` : 'bg-gray-600'
  }

  const getRoleDisplay = (role: string | null) => {
    if (!role) return 'System'
    return roleDisplayNames[role] || role.split('-')[0]
  }

  return (
    <div className="flex flex-col h-full bg-gray-900 rounded-lg border border-gray-800">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <div className="flex items-center gap-2">
          <Activity className="w-5 h-5 text-blue-400" />
          <h2 className="text-lg font-semibold text-white">Live Event Stream</h2>
          <div className={`w-2 h-2 rounded-full ${isConnected ? 'bg-green-400 animate-pulse' : 'bg-red-400'}`} />
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500">{events.length} events</span>
          <button
            onClick={() => setIsPaused(!isPaused)}
            className={`px-3 py-1 text-xs rounded-full transition-colors ${
              isPaused
                ? 'bg-amber-500/20 text-amber-400 hover:bg-amber-500/30'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            {isPaused ? 'Paused' : 'Live'}
          </button>
        </div>
      </div>

      {/* Event List */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto p-4 space-y-2 scrollbar-thin scrollbar-thumb-gray-700 scrollbar-track-transparent"
      >
        <AnimatePresence initial={false}>
          {events.map((event) => (
            <motion.div
              key={event.id}
              initial={{ opacity: 0, y: 20, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, scale: 0.95 }}
              transition={{ duration: 0.2 }}
              className={`flex items-start gap-3 p-3 rounded-lg border ${eventColors[event.event_type] || eventColors['info']}`}
            >
              {/* Event Icon */}
              <div className="flex-shrink-0 mt-0.5">
                {eventIcons[event.event_type] || eventIcons['info']}
              </div>

              {/* Content */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  {/* Role Badge */}
                  <span className={`px-2 py-0.5 text-xs font-medium rounded-full ${
                    event.role === 'SABINE_ARCHITECT' ? 'bg-violet-500/20 text-violet-300' :
                    event.role === 'backend-architect-sabine' ? 'bg-blue-500/20 text-blue-300' :
                    event.role === 'frontend-ops-sabine' ? 'bg-emerald-500/20 text-emerald-300' :
                    event.role === 'data-ai-engineer-sabine' ? 'bg-amber-500/20 text-amber-300' :
                    event.role === 'product-manager-sabine' ? 'bg-pink-500/20 text-pink-300' :
                    event.role === 'qa-security-sabine' ? 'bg-red-500/20 text-red-300' :
                    'bg-gray-500/20 text-gray-300'
                  }`}>
                    {getRoleDisplay(event.role)}
                  </span>

                  {/* Event Type */}
                  <span className="text-xs text-gray-400">
                    {event.event_type.replace(/_/g, ' ')}
                  </span>

                  {/* Timestamp */}
                  <span className="text-xs text-gray-500 ml-auto">
                    {formatTime(event.created_at)}
                  </span>
                </div>

                {/* Message */}
                <p className="text-sm text-gray-200 break-words">
                  {event.content}
                </p>

                {/* Metadata (if present) */}
                {event.metadata && Object.keys(event.metadata).length > 0 && (
                  <details className="mt-2">
                    <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-400">
                      View metadata
                    </summary>
                    <pre className="mt-1 p-2 text-xs bg-black/30 rounded overflow-x-auto">
                      {JSON.stringify(event.metadata, null, 2)}
                    </pre>
                  </details>
                )}

                {/* Task ID Link */}
                {event.task_id && (
                  <div className="mt-1">
                    <span className="text-xs text-gray-500">
                      Task: <code className="text-cyan-400">{event.task_id.slice(0, 8)}...</code>
                    </span>
                  </div>
                )}
              </div>
            </motion.div>
          ))}
        </AnimatePresence>

        {events.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-gray-500">
            <Activity className="w-8 h-8 mb-2 opacity-50" />
            <p>Waiting for events...</p>
          </div>
        )}
      </div>
    </div>
  )
}
