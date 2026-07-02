// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useState, useRef, useEffect, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { motion, AnimatePresence } from 'framer-motion'
import { cn } from '../../lib/utils'
import { ChevronLeft, ChevronRight } from 'lucide-react'

interface TimePickerProps {
  hour: number
  minute: number
  onChange: (hour: number, minute: number) => void
  open?: boolean
  onClose?: () => void
  anchorRef?: React.RefObject<HTMLElement | null>
}

const GAP = 8
const VIEWPORT_PAD = 8

function computeDropdownPosition(
  anchorRect: DOMRect,
  panelRect: DOMRect
): { left: number; top: number } {
  const vw = window.innerWidth
  const vh = window.innerHeight

  let left = anchorRect.left
  let top = anchorRect.bottom + GAP

  if (top + panelRect.height > vh - VIEWPORT_PAD) {
    top = anchorRect.top - panelRect.height - GAP
  }

  if (left + panelRect.width > vw - VIEWPORT_PAD) {
    left = anchorRect.right - panelRect.width
  }

  left = Math.max(VIEWPORT_PAD, Math.min(vw - panelRect.width - VIEWPORT_PAD, left))
  top = Math.max(VIEWPORT_PAD, Math.min(vh - panelRect.height - VIEWPORT_PAD, top))

  return { left, top }
}

const hourPositions = Array.from({ length: 12 }, (_, i) => {
  const num = i === 0 ? 12 : i
  const angleDeg = num * 30 - 90
  const angle = angleDeg * (Math.PI / 180)
  const r = 32
  return { num, x: 50 + r * Math.cos(angle), y: 50 + r * Math.sin(angle) }
})

const minute5Positions = Array.from({ length: 12 }, (_, i) => {
  const num = i * 5
  const angleDeg = num * 6 - 90
  const angle = angleDeg * (Math.PI / 180)
  const r = 32
  return { num, x: 50 + r * Math.cos(angle), y: 50 + r * Math.sin(angle) }
})

export function TimePicker({
  hour,
  minute,
  onChange,
  open = true,
  onClose,
  anchorRef,
}: TimePickerProps) {
  const [clockMode, setClockMode] = useState<'hour' | 'minute'>('hour')
  const isPM = hour >= 12
  const selectedClockHour = hour === 0 ? 12 : hour > 12 ? hour - 12 : hour

  const panelRef = useRef<HTMLDivElement>(null)
  const [coords, setCoords] = useState({ left: 0, top: 0 })
  const [positioned, setPositioned] = useState(false)
  const [usePortal, setUsePortal] = useState(false)

  useEffect(() => {
    setUsePortal(Boolean(anchorRef))
  }, [anchorRef])

  const isOpen = open

  const updatePosition = useCallback(() => {
    if (!usePortal || !anchorRef?.current || !panelRef.current) return
    const anchorRect = anchorRef.current.getBoundingClientRect()
    const panelRect = panelRef.current.getBoundingClientRect()
    const { left, top } = computeDropdownPosition(anchorRect, panelRect)
    setCoords({ left, top })
    setPositioned(true)
  }, [usePortal, anchorRef])

  useEffect(() => {
    if (!isOpen || !usePortal) {
      queueMicrotask(() => setPositioned(false))
      return
    }
    queueMicrotask(() => setPositioned(false))
    requestAnimationFrame(() => {
      requestAnimationFrame(updatePosition)
    })
  }, [isOpen, usePortal, updatePosition])

  useEffect(() => {
    if (!isOpen || !usePortal) return
    const handle = () => updatePosition()
    window.addEventListener('scroll', handle, true)
    window.addEventListener('resize', handle)
    return () => {
      window.removeEventListener('scroll', handle, true)
      window.removeEventListener('resize', handle)
    }
  }, [isOpen, usePortal, updatePosition])

  useEffect(() => {
    if (!isOpen || !usePortal || !onClose) return
    const handleClick = (e: MouseEvent) => {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        if (anchorRef?.current && anchorRef.current.contains(e.target as Node)) return
        onClose()
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [isOpen, usePortal, onClose, anchorRef])

  const handRotation = clockMode === 'hour' ? (selectedClockHour % 12) * 30 : minute * 6

  const handleHourClick = (clockHour: number) => {
    let newHour: number
    if (clockHour === 12) {
      newHour = isPM ? 12 : 0
    } else {
      newHour = isPM ? clockHour + 12 : clockHour
    }
    onChange(newHour, minute)
    setClockMode('minute')
  }

  const handlePeriodChange = (pm: boolean) => {
    const h12 = hour === 0 ? 12 : hour > 12 ? hour - 12 : hour
    if (h12 === 12) {
      onChange(pm ? 12 : 0, minute)
    } else {
      onChange(pm ? h12 + 12 : h12, minute)
    }
  }

  const panel = (
    <AnimatePresence>
      {isOpen && (
        <motion.div
          ref={panelRef}
          initial={{ opacity: 0, y: 8, scale: 0.96 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 8, scale: 0.96 }}
          transition={{ duration: 0.18 }}
          className={cn(
            'z-[9999] p-5 bubble border backdrop-blur-sm w-[300px]',
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
          {/* Digital display */}
          <div className="text-center select-none">
            <button
              onClick={() => setClockMode('hour')}
              className={cn(
                'text-3xl font-light tabular-nums transition-colors px-1 rounded hover:bg-accent',
                clockMode === 'hour' ? 'text-primary' : 'text-muted-foreground'
              )}
            >
              {String(hour).padStart(2, '0')}
            </button>
            <span className="text-3xl font-light text-muted-foreground">:</span>
            <button
              onClick={() => setClockMode('minute')}
              className={cn(
                'text-3xl font-light tabular-nums transition-colors px-1 rounded hover:bg-accent',
                clockMode === 'minute' ? 'text-primary' : 'text-muted-foreground'
              )}
            >
              {String(minute).padStart(2, '0')}
            </button>
          </div>

          {/* Minute fine stepper */}
          {clockMode === 'minute' && (
            <div className="flex items-center justify-center gap-2 mt-3">
              <button
                onClick={() => onChange(hour, (minute - 1 + 60) % 60)}
                className="p-1.5 rounded-lg bg-muted text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <span className="text-xs text-muted-foreground font-medium px-2">minute</span>
              <button
                onClick={() => onChange(hour, (minute + 1) % 60)}
                className="p-1.5 rounded-lg bg-muted text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          )}

          {/* Hour period toggle */}
          {clockMode === 'hour' && (
            <div className="flex items-center justify-center gap-2 mt-3">
              <button
                onClick={() => handlePeriodChange(false)}
                className={cn(
                  'px-5 py-1.5 rounded-lg text-sm font-medium transition-all',
                  !isPM
                    ? 'bg-primary text-primary-foreground shadow-sm'
                    : 'text-muted-foreground hover:bg-accent'
                )}
              >
                AM
              </button>
              <button
                onClick={() => handlePeriodChange(true)}
                className={cn(
                  'px-5 py-1.5 rounded-lg text-sm font-medium transition-all',
                  isPM
                    ? 'bg-primary text-primary-foreground shadow-sm'
                    : 'text-muted-foreground hover:bg-accent'
                )}
              >
                PM
              </button>
            </div>
          )}

          {/* Clock face */}
          <div className="relative w-56 h-56 mx-auto mt-4">
            <div className="absolute inset-0 rounded-full border-2 border-border/20 bg-surface/10" />

            {Array.from({ length: 60 }, (_, i) => {
              const isHourTick = i % 5 === 0
              const angle = (i * 6 - 90) * (Math.PI / 180)
              const innerR = isHourTick ? 43 : 45
              const x1 = 50 + innerR * Math.cos(angle)
              const y1 = 50 + innerR * Math.sin(angle)
              return (
                <div
                  key={i}
                  className={cn(
                    'absolute rounded-full bg-border/50',
                    isHourTick ? 'w-0.5 h-2.5' : 'w-px h-1.5'
                  )}
                  style={{
                    left: `${x1}%`,
                    top: `${y1}%`,
                    transform: `rotate(${i * 6}deg)`,
                    transformOrigin: 'top center',
                  }}
                />
              )
            })}

            <div className="absolute left-1/2 top-1/2 w-2.5 h-2.5 bg-primary rounded-full -translate-x-1/2 -translate-y-1/2 z-20" />

            <div
              className="absolute left-1/2 top-1/2 w-0.5 bg-primary origin-bottom rounded-full transition-transform duration-200 ease-out"
              style={{
                height: '32%',
                transform: `translate(-50%, -100%) rotate(${handRotation}deg)`,
              }}
            />

            {clockMode === 'hour' &&
              hourPositions.map(({ num, x, y }) => {
                const isSelected = selectedClockHour === num
                return (
                  <button
                    key={num}
                    onClick={() => handleHourClick(num)}
                    className={cn(
                      'absolute w-9 h-9 flex items-center justify-center rounded-full text-sm font-semibold transition-all -translate-x-1/2 -translate-y-1/2',
                      isSelected
                        ? 'bg-primary text-primary-foreground shadow-md scale-110'
                        : 'text-muted-foreground hover:bg-accent hover:text-foreground'
                    )}
                    style={{ left: `${x}%`, top: `${y}%` }}
                  >
                    {num}
                  </button>
                )
              })}

            {clockMode === 'minute' &&
              minute5Positions.map(({ num, x, y }) => {
                const isSelected = minute === num
                return (
                  <button
                    key={num}
                    onClick={() => onChange(hour, num)}
                    className={cn(
                      'absolute w-9 h-9 flex items-center justify-center rounded-full text-xs font-semibold transition-all -translate-x-1/2 -translate-y-1/2',
                      isSelected
                        ? 'bg-primary text-primary-foreground shadow-md scale-110'
                        : 'text-muted-foreground hover:bg-accent hover:text-foreground'
                    )}
                    style={{ left: `${x}%`, top: `${y}%` }}
                  >
                    {String(num).padStart(2, '0')}
                  </button>
                )
              })}
          </div>

          {/* Footer done button */}
          {onClose && (
            <div className="mt-4 pt-3 border-t border-border/50 flex justify-end">
              <button
                type="button"
                onClick={onClose}
                className="text-xs font-medium text-primary hover:text-primary/80 transition-colors"
              >
                Done
              </button>
            </div>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  )

  if (usePortal) {
    return createPortal(panel, document.body)
  }
  return panel
}
