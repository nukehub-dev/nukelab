// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useMemo } from 'react'
import { parseUtcDate } from '../../lib/utils'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
  type TooltipProps,
} from 'recharts'

export interface ResourceEvent {
  start: string
  end: string
  status: string
}

export interface Resource {
  name: string
  events: ResourceEvent[]
}

export interface ResourceTimelineProps {
  resources: Resource[]
  height?: number
  className?: string
}

const STATUS_COLORS: Record<string, string> = {
  running: 'var(--chart-2)',
  stopped: 'var(--muted-foreground)',
  pending: 'var(--chart-4)',
  error: 'var(--destructive)',
  warning: 'var(--chart-3)',
}

function CustomTooltip({ active, payload }: TooltipProps<number, string>) {
  if (!active || !payload || !payload.length) return null
  const data = payload[0].payload as {
    name: string
    status: string
    start: string
    end: string
    duration: string
  }

  return (
    <div
      className="rounded-lg border px-3 py-2 text-sm shadow-lg"
      style={{
        background: 'var(--popover)',
        borderColor: 'var(--border)',
        color: 'var(--popover-foreground)',
      }}
    >
      <p className="font-semibold">{data.name}</p>
      <p className="text-xs text-muted-foreground capitalize">{data.status}</p>
      <p className="text-xs text-muted-foreground mt-1">
        {data.start} → {data.end}
      </p>
      <p className="text-xs text-muted-foreground">{data.duration}</p>
    </div>
  )
}

export function ResourceTimeline({ resources, height = 300, className }: ResourceTimelineProps) {
  const { data } = useMemo(() => {
    const allEvents = resources.flatMap((r) => r.events)
    const allStarts = allEvents.map((e) => parseUtcDate(e.start).getTime())
    const allEnds = allEvents.map((e) => parseUtcDate(e.end).getTime())

    const minTime = Math.min(...allStarts)
    const maxTime = Math.max(...allEnds)
    const range = maxTime - minTime || 1

    const chartData = resources
      .map((resource) => {
        return resource.events.map((event, index) => {
          const start = parseUtcDate(event.start).getTime()
          const end = parseUtcDate(event.end).getTime()
          const duration = end - start
          const durationStr =
            duration < 60000
              ? `${Math.round(duration / 1000)}s`
              : duration < 3600000
                ? `${Math.round(duration / 60000)}m`
                : `${Math.round(duration / 3600000)}h`

          return {
            name: resource.name,
            eventIndex: index,
            status: event.status,
            start: parseUtcDate(event.start).toLocaleTimeString(),
            end: parseUtcDate(event.end).toLocaleTimeString(),
            duration: durationStr,
            startOffset: ((start - minTime) / range) * 100,
            width: (duration / range) * 100,
            y: resource.name,
          }
        })
      })
      .flat()

    return {
      data: chartData,
      timeRange: { min: minTime, max: maxTime, range },
    }
  }, [resources])

  const uniqueResources = useMemo(() => [...new Set(resources.map((r) => r.name))], [resources])

  // Transform for recharts - create stacked bars per resource
  const chartRows = useMemo(() => {
    return uniqueResources.map((name) => {
      const row: Record<string, string | number> = { name }
      const resourceEvents = data.filter((d) => d.y === name)
      resourceEvents.forEach((event, i) => {
        row[`gap_${i}`] = event.startOffset
        row[`event_${i}`] = event.width
        row[`status_${i}`] = event.status
        row[`duration_${i}`] = event.duration
        row[`start_${i}`] = event.start
        row[`end_${i}`] = event.end
      })
      return row
    })
  }, [uniqueResources, data])

  const maxEvents = useMemo(() => {
    return Math.max(...resources.map((r) => r.events.length))
  }, [resources])

  return (
    <div className={className} style={{ width: '100%', height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={chartRows}
          layout="vertical"
          margin={{ top: 5, right: 5, bottom: 5, left: 5 }}
          barCategoryGap={8}
        >
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="var(--border)"
            strokeOpacity={0.3}
            horizontal={false}
          />
          <XAxis type="number" domain={[0, 100]} hide />
          <YAxis
            type="category"
            dataKey="name"
            stroke="var(--muted-foreground)"
            tick={{ fill: 'var(--muted-foreground)', fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            width={100}
          />
          <Tooltip content={<CustomTooltip />} />
          {/* Render invisible gaps and visible events */}
          {Array.from({ length: maxEvents }).map((_, i) => (
            <Bar
              key={`event_${i}`}
              dataKey={`event_${i}`}
              stackId="stack"
              barSize={20}
              radius={[4, 4, 4, 4]}
              animationDuration={600}
            >
              {chartRows.map((row, index) => (
                <Cell
                  key={`cell-${index}`}
                  fill={STATUS_COLORS[row[`status_${i}`] as string] || 'var(--chart-1)'}
                />
              ))}
            </Bar>
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
