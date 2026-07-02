// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useState, useRef, useEffect } from 'react'
import { Calendar as CalendarIcon, ChevronDown } from 'lucide-react'
import { cn } from '../../lib/utils'
import { Calendar } from './calendar'

export interface DateRange {
  from: string
  to: string
}

interface DateRangePickerProps {
  value: DateRange
  onChange: (range: DateRange) => void
  className?: string
}

const PRESETS = [
  {
    label: 'Today',
    getRange: (): DateRange => {
      const d = new Date().toISOString().split('T')[0]
      return { from: d, to: d }
    },
  },
  {
    label: 'Last 7d',
    getRange: (): DateRange => {
      const to = new Date()
      const from = new Date()
      from.setDate(to.getDate() - 6)
      return { from: from.toISOString().split('T')[0], to: to.toISOString().split('T')[0] }
    },
  },
  {
    label: 'Last 30d',
    getRange: (): DateRange => {
      const to = new Date()
      const from = new Date()
      from.setDate(to.getDate() - 29)
      return { from: from.toISOString().split('T')[0], to: to.toISOString().split('T')[0] }
    },
  },
  {
    label: 'Last 90d',
    getRange: (): DateRange => {
      const to = new Date()
      const from = new Date()
      from.setDate(to.getDate() - 89)
      return { from: from.toISOString().split('T')[0], to: to.toISOString().split('T')[0] }
    },
  },
  {
    label: 'This Month',
    getRange: (): DateRange => {
      const now = new Date()
      const from = new Date(now.getFullYear(), now.getMonth(), 1)
      return { from: from.toISOString().split('T')[0], to: now.toISOString().split('T')[0] }
    },
  },
  {
    label: 'Last Month',
    getRange: (): DateRange => {
      const now = new Date()
      const from = new Date(now.getFullYear(), now.getMonth() - 1, 1)
      const to = new Date(now.getFullYear(), now.getMonth(), 0)
      return { from: from.toISOString().split('T')[0], to: to.toISOString().split('T')[0] }
    },
  },
]

function formatDisplayDate(dateStr: string): string {
  if (!dateStr) return ''
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString('en-US', { month: '2-digit', day: '2-digit', year: 'numeric' })
}

export function DateRangePicker({ value, onChange, className }: DateRangePickerProps) {
  const [showPresets, setShowPresets] = useState(false)
  const [fromOpen, setFromOpen] = useState(false)
  const [toOpen, setToOpen] = useState(false)
  const fromRef = useRef<HTMLDivElement>(null)
  const toRef = useRef<HTMLDivElement>(null)
  const today = new Date().toISOString().split('T')[0]

  // Close calendar on Escape
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setFromOpen(false)
        setToOpen(false)
        setShowPresets(false)
      }
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [])

  const daysCount = (() => {
    if (!value.from || !value.to) return 0
    const from = new Date(value.from)
    const to = new Date(value.to)
    return Math.ceil((to.getTime() - from.getTime()) / (1000 * 60 * 60 * 24)) + 1
  })()

  return (
    <div className={cn('flex items-center gap-2 flex-wrap', className)}>
      {/* From date */}
      <div className="relative" ref={fromRef}>
        <button
          onClick={() => {
            setFromOpen((o) => !o)
            setToOpen(false)
          }}
          className={cn(
            'flex items-center gap-2 pl-3 pr-3 py-1.5 rounded-lg text-sm border transition-all',
            'bg-background hover:bg-accent text-foreground',
            fromOpen && 'ring-1 ring-primary border-primary'
          )}
        >
          <CalendarIcon className="w-3.5 h-3.5 text-muted-foreground" />
          <span className={cn(!value.from && 'text-muted-foreground')}>
            {value.from ? formatDisplayDate(value.from) : 'Start'}
          </span>
        </button>
        <Calendar
          value={value.from}
          onSelect={(date) => onChange({ ...value, from: date })}
          maxDate={value.to && value.to < today ? value.to : today}
          open={fromOpen}
          onClose={() => setFromOpen(false)}
        />
      </div>

      <span className="text-muted-foreground text-sm">to</span>

      {/* To date */}
      <div className="relative" ref={toRef}>
        <button
          onClick={() => {
            setToOpen((o) => !o)
            setFromOpen(false)
          }}
          className={cn(
            'flex items-center gap-2 pl-3 pr-3 py-1.5 rounded-lg text-sm border transition-all',
            'bg-background hover:bg-accent text-foreground',
            toOpen && 'ring-1 ring-primary border-primary'
          )}
        >
          <CalendarIcon className="w-3.5 h-3.5 text-muted-foreground" />
          <span className={cn(!value.to && 'text-muted-foreground')}>
            {value.to ? formatDisplayDate(value.to) : 'End'}
          </span>
        </button>
        <Calendar
          value={value.to}
          onSelect={(date) => onChange({ ...value, to: date })}
          minDate={value.from || undefined}
          maxDate={today}
          open={toOpen}
          onClose={() => setToOpen(false)}
        />
      </div>

      {value.from && value.to && (
        <span className="text-xs text-muted-foreground tabular-nums">{daysCount}d</span>
      )}

      {/* Quick Select */}
      <div className="relative">
        <button
          onClick={() => setShowPresets((s) => !s)}
          className={cn(
            'flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-sm font-medium transition-colors border',
            'bg-background hover:bg-accent text-foreground',
            showPresets && 'ring-1 ring-primary border-primary'
          )}
        >
          Quick Select
          <ChevronDown
            className={cn(
              'w-3.5 h-3.5 text-muted-foreground transition-transform',
              showPresets && 'rotate-180'
            )}
          />
        </button>
        {showPresets && (
          <>
            <div className="fixed inset-0 z-40" onClick={() => setShowPresets(false)} />
            <div
              className="absolute right-0 top-full mt-1 z-50 min-w-[160px] bubble border backdrop-blur-sm p-1.5"
              style={{ borderColor: 'var(--border)', borderWidth: '1px' }}
            >
              {PRESETS.map((preset) => (
                <button
                  key={preset.label}
                  onClick={() => {
                    onChange(preset.getRange())
                    setShowPresets(false)
                  }}
                  className="w-full text-left px-3 py-2 rounded-lg text-sm hover:bg-accent transition-colors"
                >
                  {preset.label}
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
