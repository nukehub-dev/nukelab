import { useState, useMemo, useRef, useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { cn } from '../../lib/utils'

const MONTHS = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
]

const DAY_HEADERS = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa']

interface CalendarProps {
  value?: string // YYYY-MM-DD
  onSelect: (date: string) => void
  minDate?: string
  maxDate?: string
  open: boolean
  onClose: () => void
  anchorRef?: React.RefObject<HTMLElement | null>
}

function getDaysInMonth(year: number, month: number): number {
  return new Date(year, month + 1, 0).getDate()
}

function getFirstDayOfMonth(year: number, month: number): number {
  return new Date(year, month, 1).getDay()
}

function isSameDay(a: string, b: string): boolean {
  return a === b
}

function formatLocalDate(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

const GAP = 8
const VIEWPORT_PAD = 8

function computeDropdownPosition(
  anchorRect: DOMRect,
  panelRect: DOMRect
): { left: number; top: number } {
  const vw = window.innerWidth
  const vh = window.innerHeight

  // Default: below anchor, left-aligned
  let left = anchorRect.left
  let top = anchorRect.bottom + GAP

  // Flip to above if no room below
  if (top + panelRect.height > vh - VIEWPORT_PAD) {
    top = anchorRect.top - panelRect.height - GAP
  }

  // Align right if overflows right edge
  if (left + panelRect.width > vw - VIEWPORT_PAD) {
    left = anchorRect.right - panelRect.width
  }

  // Clamp to viewport
  left = Math.max(VIEWPORT_PAD, Math.min(vw - panelRect.width - VIEWPORT_PAD, left))
  top = Math.max(VIEWPORT_PAD, Math.min(vh - panelRect.height - VIEWPORT_PAD, top))

  return { left, top }
}

export function Calendar({
  value,
  onSelect,
  minDate,
  maxDate,
  open,
  onClose,
  anchorRef,
}: CalendarProps) {
  const [viewDate, setViewDate] = useState(() => {
    const d = value ? new Date(value + 'T00:00:00') : new Date()
    return { year: d.getFullYear(), month: d.getMonth() }
  })

  const panelRef = useRef<HTMLDivElement>(null)
  const [coords, setCoords] = useState({ left: 0, top: 0 })
  const [positioned, setPositioned] = useState(false)
  const [usePortal, setUsePortal] = useState(false)

  useEffect(() => {
    setUsePortal(Boolean(anchorRef))
  }, [anchorRef])

  const updatePosition = useCallback(() => {
    if (!usePortal || !anchorRef?.current || !panelRef.current) return
    const anchorRect = anchorRef.current.getBoundingClientRect()
    const panelRect = panelRef.current.getBoundingClientRect()
    const { left, top } = computeDropdownPosition(anchorRect, panelRect)
    setCoords({ left, top })
    setPositioned(true)
  }, [usePortal, anchorRef])

  // Position when opening
  useEffect(() => {
    if (!open || !usePortal) {
      queueMicrotask(() => setPositioned(false))
      return
    }
    queueMicrotask(() => setPositioned(false))
    requestAnimationFrame(() => {
      requestAnimationFrame(updatePosition)
    })
  }, [open, usePortal, updatePosition])

  // Update on scroll/resize while open
  useEffect(() => {
    if (!open || !usePortal) return
    const handle = () => updatePosition()
    window.addEventListener('scroll', handle, true)
    window.addEventListener('resize', handle)
    return () => {
      window.removeEventListener('scroll', handle, true)
      window.removeEventListener('resize', handle)
    }
  }, [open, usePortal, updatePosition])

  // Close on click outside
  useEffect(() => {
    if (!open) return
    const handleClick = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        // Also don't close if clicking the anchor trigger
        if (anchorRef?.current && anchorRef.current.contains(e.target as Node)) return
        onClose()
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open, onClose, anchorRef])

  const days = useMemo(() => {
    const total = getDaysInMonth(viewDate.year, viewDate.month)
    const firstDay = getFirstDayOfMonth(viewDate.year, viewDate.month)
    const prevMonthDays = getDaysInMonth(viewDate.year, viewDate.month - 1)

    const cells: {
      day: number
      date: string
      isCurrentMonth: boolean
      isToday: boolean
      isDisabled: boolean
    }[] = []

    // Previous month padding
    for (let i = firstDay - 1; i >= 0; i--) {
      const d = prevMonthDays - i
      const date = formatLocalDate(new Date(viewDate.year, viewDate.month - 1, d))
      cells.push({ day: d, date, isCurrentMonth: false, isToday: false, isDisabled: true })
    }

    // Current month
    const today = formatLocalDate(new Date())
    for (let d = 1; d <= total; d++) {
      const date = formatLocalDate(new Date(viewDate.year, viewDate.month, d))
      const isToday = date === today
      const isDisabled = Boolean((minDate && date < minDate) || (maxDate && date > maxDate))
      cells.push({ day: d, date, isCurrentMonth: true, isToday, isDisabled })
    }

    // Next month padding to fill 6 rows (42 cells)
    const remaining = 42 - cells.length
    for (let d = 1; d <= remaining; d++) {
      const date = formatLocalDate(new Date(viewDate.year, viewDate.month + 1, d))
      cells.push({ day: d, date, isCurrentMonth: false, isToday: false, isDisabled: true })
    }

    return cells
  }, [viewDate, minDate, maxDate])

  const goToPrevMonth = () => {
    setViewDate((v) => {
      if (v.month === 0) return { year: v.year - 1, month: 11 }
      return { year: v.year, month: v.month - 1 }
    })
  }

  const goToNextMonth = () => {
    setViewDate((v) => {
      if (v.month === 11) return { year: v.year + 1, month: 0 }
      return { year: v.year, month: v.month + 1 }
    })
  }

  const goToToday = () => {
    const d = new Date()
    setViewDate({ year: d.getFullYear(), month: d.getMonth() })
  }

  const panel = (
    <AnimatePresence>
      {open && (
        <motion.div
          ref={panelRef}
          initial={{ opacity: 0, y: 8, scale: 0.96 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 8, scale: 0.96 }}
          transition={{ duration: 0.18 }}
          className={cn(
            'z-[9999] p-4 bubble border backdrop-blur-sm w-[320px]',
            usePortal ? 'fixed' : 'absolute mt-2'
          )}
          style={{
            borderColor: 'var(--border)',
            borderWidth: '1px',
            ...(usePortal
              ? { left: coords.left, top: coords.top, opacity: positioned ? 1 : 0 }
              : {}),
          }}
        >
          {/* Header: month/year navigation */}
          <div className="flex items-center justify-between mb-4">
            <button
              onClick={goToPrevMonth}
              className="p-1.5 rounded-lg hover:bg-accent transition-colors"
            >
              <ChevronLeft className="w-4 h-4 text-muted-foreground" />
            </button>

            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-foreground">
                {MONTHS[viewDate.month]}
              </span>
              <span className="text-sm text-muted-foreground">{viewDate.year}</span>
            </div>

            <button
              onClick={goToNextMonth}
              className="p-1.5 rounded-lg hover:bg-accent transition-colors"
            >
              <ChevronRight className="w-4 h-4 text-muted-foreground" />
            </button>
          </div>

          {/* Day headers */}
          <div className="grid grid-cols-7 gap-1 mb-2">
            {DAY_HEADERS.map((h) => (
              <div
                key={h}
                className="text-center text-[11px] font-medium text-muted-foreground/70 uppercase tracking-wider py-1"
              >
                {h}
              </div>
            ))}
          </div>

          {/* Days grid */}
          <div className="grid grid-cols-7 gap-1">
            {days.map((cell, i) => {
              const isSelected = value && isSameDay(cell.date, value)

              return (
                <button
                  key={i}
                  disabled={cell.isDisabled}
                  onClick={() => {
                    if (!cell.isDisabled) {
                      onSelect(cell.date)
                      onClose()
                    }
                  }}
                  className={cn(
                    'relative aspect-square rounded-lg text-sm font-medium transition-all',
                    'flex items-center justify-center',
                    cell.isCurrentMonth ? 'text-foreground' : 'text-muted-foreground/30',
                    cell.isDisabled && cell.isCurrentMonth
                      ? 'opacity-40 cursor-not-allowed'
                      : 'hover:bg-accent cursor-pointer',
                    isSelected && 'bg-primary text-primary-foreground hover:bg-primary',
                    cell.isToday && !isSelected && 'border border-primary/50 text-primary'
                  )}
                >
                  {cell.day}
                  {cell.isToday && !isSelected && (
                    <span className="absolute bottom-1 left-1/2 -translate-x-1/2 w-1 h-1 rounded-full bg-primary" />
                  )}
                </button>
              )
            })}
          </div>

          {/* Footer */}
          <div className="mt-3 pt-3 border-t border-border/50 flex items-center justify-between">
            <button
              onClick={goToToday}
              className="text-xs font-medium text-primary hover:text-primary/80 transition-colors"
            >
              Today
            </button>
            <button
              onClick={onClose}
              className="text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
            >
              Cancel
            </button>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )

  if (usePortal) {
    return createPortal(panel, document.body)
  }
  return panel
}
