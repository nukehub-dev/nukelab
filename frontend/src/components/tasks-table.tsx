// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useMemo } from 'react'
import { Activity, ListOrdered } from 'lucide-react'
import { formatBytes, cn } from '../lib/utils'
import type { ServerTask } from '../hooks/use-servers'

interface TasksTableProps {
  tasks: ServerTask[]
  status?: 'running' | 'stopped' | 'error'
  isLoading?: boolean
}

export function TasksTable({ tasks, status, isLoading }: TasksTableProps) {
  // Highest CPU consumers first
  const sorted = useMemo(() => [...tasks].sort((a, b) => b.cpu_percent - a.cpu_percent), [tasks])

  if (isLoading && tasks.length === 0) {
    return (
      <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
        Loading tasks...
      </div>
    )
  }

  if (status === 'stopped') {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <ListOrdered className="w-8 h-8 text-muted-foreground mb-3 opacity-50" />
        <p className="text-sm text-muted-foreground">Server is stopped — no running tasks</p>
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-center">
        <Activity className="w-8 h-8 text-muted-foreground mb-3 opacity-50" />
        <p className="text-sm text-muted-foreground">
          Could not retrieve tasks from the container runtime
        </p>
      </div>
    )
  }

  if (sorted.length === 0) {
    return (
      <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
        No running tasks
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted-foreground">
            <th className="py-2 pr-4 font-medium">PID</th>
            <th className="py-2 pr-4 font-medium">User</th>
            <th className="py-2 pr-4 font-medium text-right">CPU %</th>
            <th className="py-2 pr-4 font-medium text-right">Mem %</th>
            <th className="py-2 pr-4 font-medium text-right">RSS</th>
            <th className="py-2 pr-4 font-medium">Stat</th>
            <th className="py-2 pr-4 font-medium">Time</th>
            <th className="py-2 font-medium">Command</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((task) => (
            <tr key={task.pid} className="border-b border-border/50 last:border-0">
              <td className="py-2 pr-4 font-mono text-xs">{task.pid}</td>
              <td className="py-2 pr-4 text-xs">{task.user}</td>
              <td
                className={cn(
                  'py-2 pr-4 text-right font-mono text-xs',
                  task.cpu_percent >= 50 && 'text-destructive font-medium'
                )}
              >
                {task.cpu_percent.toFixed(1)}
              </td>
              <td className="py-2 pr-4 text-right font-mono text-xs">
                {task.mem_percent.toFixed(1)}
              </td>
              <td className="py-2 pr-4 text-right font-mono text-xs">
                {formatBytes(task.rss_bytes)}
              </td>
              <td className="py-2 pr-4 font-mono text-xs">{task.stat}</td>
              <td className="py-2 pr-4 font-mono text-xs">{task.time}</td>
              <td className="py-2 font-mono text-xs break-all">{task.command}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
