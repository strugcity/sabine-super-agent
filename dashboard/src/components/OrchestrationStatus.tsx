'use client'

import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { Activity, Users, CheckCircle, Clock, AlertCircle, RefreshCw } from 'lucide-react'
import { useTaskActions, OrchestrationStatus as StatusType } from '@/hooks/useTaskActions'

interface StatCardProps {
  label: string
  value: number | string
  icon: React.ReactNode
  color: string
  subtext?: string
}

function StatCard({ label, value, icon, color, subtext }: StatCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className={`p-4 rounded-lg bg-gray-900 border border-gray-800 flex items-center gap-4`}
    >
      <div className={`p-3 rounded-lg ${color}`}>
        {icon}
      </div>
      <div>
        <p className="text-2xl font-bold text-white">{value}</p>
        <p className="text-sm text-gray-400">{label}</p>
        {subtext && <p className="text-xs text-gray-500 mt-1">{subtext}</p>}
      </div>
    </motion.div>
  )
}

export default function OrchestrationStatus() {
  const [status, setStatus] = useState<StatusType | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null)
  const { getStatus } = useTaskActions()

  const fetchStatus = async () => {
    setIsLoading(true)
    const result = await getStatus()
    if (result.success && result.data) {
      setStatus(result.data)
      setLastUpdate(new Date())
    }
    setIsLoading(false)
  }

  useEffect(() => {
    fetchStatus()
    // Refresh every 30 seconds
    const interval = setInterval(fetchStatus, 30000)
    return () => clearInterval(interval)
  }, [])

  if (!status) {
    return (
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="p-4 rounded-lg bg-gray-900 border border-gray-800 animate-pulse h-24" />
        ))}
      </div>
    )
  }

  const { task_counts, unblocked_count, total_tasks } = status

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <Activity className="w-5 h-5 text-blue-400" />
          Orchestration Status
        </h2>
        <div className="flex items-center gap-2">
          {lastUpdate && (
            <span className="text-xs text-gray-500">
              Updated {lastUpdate.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={fetchStatus}
            disabled={isLoading}
            className="p-2 rounded-lg bg-gray-800 hover:bg-gray-700 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-4 h-4 text-gray-400 ${isLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-4">
        <StatCard
          label="Total Tasks"
          value={total_tasks}
          icon={<Users className="w-5 h-5 text-white" />}
          color="bg-blue-500/20"
        />
        <StatCard
          label="Ready to Run"
          value={unblocked_count}
          icon={<Clock className="w-5 h-5 text-white" />}
          color="bg-amber-500/20"
          subtext="Dependencies met"
        />
        <StatCard
          label="In Progress"
          value={task_counts['in_progress'] || 0}
          icon={<Activity className="w-5 h-5 text-white" />}
          color="bg-cyan-500/20"
        />
        <StatCard
          label="Completed"
          value={task_counts['completed'] || 0}
          icon={<CheckCircle className="w-5 h-5 text-white" />}
          color="bg-green-500/20"
        />
        <StatCard
          label="Failed"
          value={task_counts['failed'] || 0}
          icon={<AlertCircle className="w-5 h-5 text-white" />}
          color="bg-red-500/20"
        />
      </div>

      {/* Status Breakdown */}
      <div className="p-4 rounded-lg bg-gray-900 border border-gray-800">
        <h3 className="text-sm font-medium text-gray-400 mb-3">Status Breakdown</h3>
        <div className="flex gap-2 flex-wrap">
          {Object.entries(task_counts).map(([status, count]) => (
            <div
              key={status}
              className={`px-3 py-1.5 rounded-lg text-sm flex items-center gap-2 ${
                status === 'completed' ? 'bg-green-500/20 text-green-300' :
                status === 'in_progress' ? 'bg-blue-500/20 text-blue-300' :
                status === 'failed' ? 'bg-red-500/20 text-red-300' :
                status === 'awaiting_approval' ? 'bg-amber-500/20 text-amber-300' :
                'bg-gray-500/20 text-gray-300'
              }`}
            >
              <span className="font-medium">{count}</span>
              <span>{status.replace(/_/g, ' ')}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
