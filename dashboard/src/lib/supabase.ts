import { createClient } from '@supabase/supabase-js'

// These will be set via environment variables
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || ''
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || ''

export const supabase = createClient(supabaseUrl, supabaseAnonKey)

// Types for our database tables
export interface AgentEvent {
  id: string
  task_id: string | null
  role: string | null
  event_type: string
  content: string
  metadata: Record<string, any>
  slack_thread_ts: string | null
  slack_channel: string | null
  created_at: string
}

export interface Task {
  id: string
  role: string
  status: 'queued' | 'in_progress' | 'completed' | 'failed' | 'awaiting_approval'
  priority: number
  payload: Record<string, any>
  depends_on: string[]
  result: Record<string, any> | null
  error: string | null
  created_at: string
  updated_at: string
  created_by: string | null
  session_id: string | null
}

export interface OrchestrationStatus {
  task_counts: Record<string, number>
  unblocked_count: number
  total_tasks: number
  timestamp: string
}

// Role color mapping
export const roleColors: Record<string, string> = {
  'SABINE_ARCHITECT': 'role-architect',
  'backend-architect-sabine': 'role-backend',
  'frontend-ops-sabine': 'role-frontend',
  'data-ai-engineer-sabine': 'role-data',
  'product-manager-sabine': 'role-pm',
  'qa-security-sabine': 'role-qa',
}

export const roleDisplayNames: Record<string, string> = {
  'SABINE_ARCHITECT': 'Architect',
  'backend-architect-sabine': 'Backend',
  'frontend-ops-sabine': 'Frontend',
  'data-ai-engineer-sabine': 'Data/AI',
  'product-manager-sabine': 'PM',
  'qa-security-sabine': 'QA',
}

// Event type emoji mapping
export const eventEmojis: Record<string, string> = {
  'task_started': '🚀',
  'task_completed': '✅',
  'task_failed': '❌',
  'agent_thought': '💭',
  'tool_call': '🔧',
  'tool_result': '📤',
  'system_startup': '🏗️',
  'system_shutdown': '🔌',
  'handshake': '🤝',
  'error': '⚠️',
  'info': 'ℹ️',
}
