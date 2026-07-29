// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useMemo, useState, useCallback, useRef, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { cn, parseLocalDate } from '../../lib/utils'

export interface CalendarHeatmapData {
  date: string
  value: number
}

interface CalendarHeatmapProps {
  data: CalendarHeatmapData[]
  from: string
  to: string
  metric?: 'signups' | 'credits' | 'servers' | 'logins'
  className?: string
}

const MONTH_NAMES = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
]
const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const DAY_LABELS_WIDTH = 36
const MONTH_LABELS_LEFT = 40
const CELL_GAP = 2
const MIN_CELL = 8

function normalizeDate(dateStr: string): string {
  return dateStr.length > 10 ? dateStr.slice(0, 10) : dateStr
}

function formatISOLocal(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function formatDateLabel(dateStr: string): string {
  const d = parseLocalDate(dateStr)
  return d.toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  })
}

const LEVELS = [
  { bg: 'bg-muted', border: 'border-transparent' },
  { bg: 'bg-emerald-200', border: 'border-emerald-300' },
  { bg: 'bg-emerald-400', border: 'border-emerald-500' },
  { bg: 'bg-emerald-600', border: 'border-emerald-700' },
  { bg: 'bg-emerald-800', border: 'border-emerald-900' },
]

const METRIC_LABELS: Record<string, [string, string]> = {
  signups: ['signup', 'signups'],
  credits: ['credit', 'credits'],
  servers: ['server', 'servers'],
  logins: ['login', 'logins'],
}

function formatMetric(value: number, metric: string): string {
  const [singular, plural] = METRIC_LABELS[metric] || ['activity', 'activities']
  return value === 1 ? singular : plural
}

function getLevel(value: number, max: number): number {
  if (value <= 0 || max <= 0) return 0
  const ratio = value / max
  if (ratio <= 0.25) return 1
  if (ratio <= 0.5) return 2
  if (ratio <= 0.75) return 3
  return 4
}

interface DayCell {
  date: string
  value: number
  inRange: boolean
}

export function CalendarHeatmap({
  data,
  from,
  to,
  metric = 'signups',
  className,
}: CalendarHeatmapProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [containerWidth, setContainerWidth] = useState(0)
  const [tooltip, setTooltip] = useState<{
    date: string
    value: number
    level: number
    x: number
    y: number
  } | null>(null)

  // Measure container width
  useEffect(() => {
    const el = containerRef.current
    if (!el) return

    const update = () => {
      const w = el.getBoundingClientRect().width
      setContainerWidth(w)
    }
    update()

    const ro = new ResizeObserver(update)
    ro.observe(el)
    window.addEventListener('resize', update)
    return () => {
      ro.disconnect()
      window.removeEventListener('resize', update)
    }
  }, [])

  const { weeks, maxValue, stats, monthLabels } = useMemo(() => {
    const valueMap = new Map<string, number>()
    data.forEach((d) => valueMap.set(normalizeDate(d.date), d.value))

    const fromDate = parseLocalDate(from)
    const toDate = parseLocalDate(to)

    const fromDay = fromDate.getDay()
    const daysBack = fromDay === 0 ? 6 : fromDay - 1
    fromDate.setDate(fromDate.getDate() - daysBack)

    const toDay = toDate.getDay()
    const daysForward = toDay === 0 ? 0 : 7 - toDay
    toDate.setDate(toDate.getDate() + daysForward)

    const weeksArr: DayCell[][] = []
    const months: { label: string; weekIndex: number }[] = []
    let lastMonth = -1

    const iter = new Date(fromDate)
    let currentWeek: DayCell[] = []
    let weekIdx = 0

    while (iter <= toDate) {
      const iso = formatISOLocal(iter)
      const dow = iter.getDay()
      const row = dow === 0 ? 6 : dow - 1

      if (row === 0) {
        const m = iter.getMonth()
        if (m !== lastMonth) {
          months.push({ label: MONTH_NAMES[m], weekIndex: weekIdx })
          lastMonth = m
        }
      }

      const inRange = iso >= from && iso <= to
      currentWeek[row] = {
        date: iso,
        value: inRange ? (valueMap.get(iso) ?? 0) : 0,
        inRange,
      }

      if (row === 6) {
        weeksArr.push(currentWeek)
        currentWeek = []
        weekIdx++
      }
      iter.setDate(iter.getDate() + 1)
    }

    if (currentWeek.length > 0) {
      while (currentWeek.length < 7) {
        currentWeek.push({ date: '', value: 0, inRange: false })
      }
      weeksArr.push(currentWeek)
    }

    const inRangeValues = data
      .filter((d) => {
        const nd = normalizeDate(d.date)
        return nd >= from && nd <= to
      })
      .map((d) => d.value)

    const max = Math.max(...(inRangeValues.length ? inRangeValues : [0]), 1)

    let total = 0
    let busiest = 0
    let quietest = Infinity
    inRangeValues.forEach((v) => {
      total += v
      if (v > busiest) busiest = v
      if (v < quietest) quietest = v
    })

    return {
      weeks: weeksArr,
      maxValue: max,
      stats: {
        total,
        busiest,
        quietest: quietest === Infinity ? 0 : quietest,
      },
      monthLabels: months,
    }
  }, [data, from, to])

  // Compute responsive cell size based on container width
  const cellSize = useMemo(() => {
    if (!containerWidth || weeks.length === 0) return 12
    const available = containerWidth - MONTH_LABELS_LEFT - 16 // 16px right padding reserve
    const size = Math.floor((available - (weeks.length - 1) * CELL_GAP) / weeks.length)
    return Math.max(MIN_CELL, size)
  }, [containerWidth, weeks.length])

  const weekWidth = cellSize + CELL_GAP
  const cellHeight = Math.min(cellSize, 20)

  const handleEnter = useCallback(
    (e: React.MouseEvent, day: DayCell) => {
      if (!day.inRange || !day.date) return
      const rect = (e.target as HTMLElement).getBoundingClientRect()
      setTooltip({
        date: day.date,
        value: day.value,
        level: getLevel(day.value, maxValue),
        x: rect.left + rect.width / 2,
        y: rect.top - 4,
      })
    },
    [maxValue]
  )

  const visibleMonthLabels = useMemo(() => {
    const minGap = 28
    const kept: { label: string; left: number }[] = []
    monthLabels.forEach((m) => {
      const left = m.weekIndex * weekWidth
      const last = kept[kept.length - 1]
      if (!last || left - last.left >= minGap) {
        kept.push({ label: m.label, left })
      }
    })
    return kept
  }, [monthLabels, weekWidth])

  if (weeks.length === 0) {
    return (
      <div className={cn('py-8 text-center text-sm text-muted-foreground', className)}>
        No data for selected range
      </div>
    )
  }

  return (
    <div ref={containerRef} className={cn('select-none w-full', className)}>
      {/* Month labels */}
      <div className="relative mb-1" style={{ marginLeft: MONTH_LABELS_LEFT, height: 16 }}>
        {visibleMonthLabels.map((m, i) => (
          <span
            key={i}
            className="absolute text-[10px] font-medium text-muted-foreground/70 whitespace-nowrap"
            style={{ left: m.left }}
          >
            {m.label}
          </span>
        ))}
      </div>

      {/* Grid */}
      <div className="flex gap-1">
        {/* Day labels */}
        <div className="flex flex-col shrink-0" style={{ gap: CELL_GAP, width: DAY_LABELS_WIDTH }}>
          {DAY_LABELS.map((label) => (
            <div
              key={label}
              className="text-[10px] text-muted-foreground/50 flex items-center justify-end pr-1"
              style={{ height: cellHeight }}
            >
              {label}
            </div>
          ))}
        </div>

        {/* Week columns */}
        <div className="flex" style={{ gap: CELL_GAP }}>
          {weeks.map((week, wi) => (
            <div key={wi} className="flex flex-col" style={{ gap: CELL_GAP }}>
              {week.map((day, di) => {
                const level = getLevel(day.value, maxValue)
                const lvl = LEVELS[level]

                return (
                  <motion.div
                    key={di}
                    initial={{ scale: 0.3 }}
                    animate={{ scale: 1 }}
                    transition={{ delay: wi * 0.008 + di * 0.004, duration: 0.12 }}
                    className={cn(
                      'rounded-sm shrink-0 border transition-all duration-100',
                      day.inRange && day.date
                        ? 'cursor-pointer hover:scale-[1.001] hover:ring-2 hover:ring-primary/40 hover:z-10'
                        : 'cursor-default',
                      day.inRange ? lvl.bg : 'bg-muted/40',
                      day.inRange ? lvl.border : 'border-transparent'
                    )}
                    style={{
                      width: cellSize,
                      height: cellHeight,
                      opacity: day.inRange ? 1 : 0.35,
                    }}
                    onMouseEnter={(e) => handleEnter(e, day)}
                    onMouseLeave={() => setTooltip(null)}
                  />
                )
              })}
            </div>
          ))}
        </div>
      </div>

      {/* Legend + Stats */}
      <div className="flex items-center justify-between flex-wrap gap-4 mt-3">
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-muted-foreground">Less</span>
          {LEVELS.map((lvl, i) => (
            <div
              key={i}
              className={cn('rounded-sm border', lvl.bg, lvl.border)}
              style={{ width: 14, height: 10 }}
            />
          ))}
          <span className="text-[10px] text-muted-foreground">More</span>
        </div>

        <div className="flex items-center gap-4">
          {[
            { label: 'Total', value: stats.total },
            { label: 'Peak', value: stats.busiest },
            { label: 'Min', value: stats.quietest },
          ].map((s, i) => (
            <div key={s.label} className="flex items-center gap-4">
              {i > 0 && <div className="w-px h-5 bg-border" />}
              <div className="text-center">
                <div className="text-sm font-bold text-foreground tabular-nums">
                  {s.value.toLocaleString()}
                </div>
                <div className="text-[10px] text-muted-foreground uppercase tracking-wider">
                  {s.label}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Fixed tooltip */}
      <AnimatePresence>
        {tooltip && (
          <motion.div
            initial={{ opacity: 0, y: 6, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 6, scale: 0.95 }}
            transition={{ duration: 0.15, ease: 'easeOut' }}
            className="fixed z-[100] pointer-events-none"
            style={{
              left: tooltip.x,
              top: tooltip.y - 8,
              transform: 'translate(-50%, -100%)',
            }}
          >
            <div className="px-4 py-2.5 rounded-xl bg-popover/95 border border-border/50 shadow-2xl backdrop-blur-md">
              <p className="text-[11px] text-muted-foreground font-medium">
                {formatDateLabel(tooltip.date)}
              </p>
              <div className="flex items-center gap-2 mt-1">
                <div
                  className={cn(
                    'w-2.5 h-2.5 rounded-full shrink-0 ring-1 ring-border/40',
                    tooltip.level === 0
                      ? 'bg-muted ring-muted-foreground/20'
                      : LEVELS[tooltip.level].bg
                  )}
                />
                <p className="text-sm font-bold text-foreground">
                  {tooltip.value.toLocaleString()}
                  <span className="text-muted-foreground font-normal text-xs ml-1">
                    {formatMetric(tooltip.value, metric)}
                  </span>
                </p>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
