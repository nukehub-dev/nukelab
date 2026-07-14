// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import * as React from 'react'
import { createPortal } from 'react-dom'
import { cn } from '../../lib/utils'
import { ChevronDown, Check, Search } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

interface ComboboxOption {
  value: string
  label: string
  image?: string
}

interface ComboboxProps {
  value: string
  onChange: (value: string) => void
  options: ComboboxOption[]
  placeholder?: string
  className?: string
  /** Extra classes for the trigger button (merged after the base styles). */
  triggerClassName?: string
  disabled?: boolean
  searchPlaceholder?: string
}

const GAP = 4
const VIEWPORT_PAD = 8

/**
 * Viewport position for the portaled panel, flipping above the anchor when
 * there is no room below. Same algorithm as calendar.tsx / time-picker.tsx.
 */
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

export function Combobox({
  value,
  onChange,
  options,
  placeholder = 'Select...',
  className,
  triggerClassName,
  disabled,
  searchPlaceholder = 'Search...',
}: ComboboxProps) {
  const [open, setOpen] = React.useState(false)
  const [search, setSearch] = React.useState('')
  const containerRef = React.useRef<HTMLDivElement>(null)
  const buttonRef = React.useRef<HTMLButtonElement>(null)
  const panelRef = React.useRef<HTMLDivElement>(null)
  const inputRef = React.useRef<HTMLInputElement>(null)
  const [coords, setCoords] = React.useState({ left: 0, top: 0, width: 0 })
  const [positioned, setPositioned] = React.useState(false)

  // The panel is portaled to document.body so it escapes the stacking
  // contexts created by backdrop-blur/transform on ancestor cards.
  const updatePosition = React.useCallback(() => {
    if (!buttonRef.current || !panelRef.current) return
    const anchorRect = buttonRef.current.getBoundingClientRect()
    const panelRect = panelRef.current.getBoundingClientRect()
    const { left, top } = computeDropdownPosition(anchorRect, panelRect)
    setCoords({ left, top, width: anchorRect.width })
    setPositioned(true)
  }, [])

  // Measure on open (two rAFs so the panel has rendered and can be measured).
  React.useEffect(() => {
    if (!open) return
    queueMicrotask(() => setPositioned(false))
    const raf = requestAnimationFrame(() => requestAnimationFrame(updatePosition))
    return () => cancelAnimationFrame(raf)
  }, [open, updatePosition])

  // Keep the panel aligned with the trigger on scroll/resize while open.
  React.useEffect(() => {
    if (!open) return
    window.addEventListener('scroll', updatePosition, true)
    window.addEventListener('resize', updatePosition)
    return () => {
      window.removeEventListener('scroll', updatePosition, true)
      window.removeEventListener('resize', updatePosition)
    }
  }, [open, updatePosition])

  // Close on outside click; the panel lives in a portal, so check both refs.
  React.useEffect(() => {
    if (!open) return
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as Node
      if (containerRef.current?.contains(target)) return
      if (panelRef.current?.contains(target)) return
      setOpen(false)
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  // Focus input when opened
  React.useEffect(() => {
    if (open && inputRef.current) {
      setTimeout(() => inputRef.current?.focus(), 100)
    }
  }, [open])

  const filteredOptions = React.useMemo(() => {
    if (!search.trim()) return options
    const query = search.toLowerCase()
    return options.filter((opt) => opt.label.toLowerCase().includes(query))
  }, [options, search])

  const selectedOption = React.useMemo(() => {
    return options.find((opt) => opt.value === value)
  }, [options, value])

  const panel = (
    <AnimatePresence>
      {open && (
        <motion.div
          ref={panelRef}
          initial={{ opacity: 0, y: -4, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -4, scale: 0.98 }}
          transition={{ duration: 0.15 }}
          className="fixed z-[9999] overflow-hidden rounded-xl border border-border bg-popover shadow-lg"
          style={{
            left: coords.left,
            top: coords.top,
            width: coords.width,
            opacity: positioned ? 1 : 0,
          }}
        >
          {/* Search Input */}
          <div className="p-2 border-b border-border">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <input
                ref={inputRef}
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={searchPlaceholder}
                className="w-full h-8 pl-9 pr-3 rounded-lg border border-input bg-background text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring/50"
                onClick={(e) => e.stopPropagation()}
              />
            </div>
          </div>

          {/* Options List */}
          <div className="max-h-60 overflow-auto p-1.5 space-y-1">
            {filteredOptions.length === 0 ? (
              <div className="py-4 text-center text-sm text-muted-foreground">No results found</div>
            ) : (
              filteredOptions.map((option) => {
                const isSelected = value === option.value
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => {
                      onChange(option.value)
                      setOpen(false)
                      setSearch('')
                    }}
                    className={cn(
                      'relative flex w-full cursor-pointer select-none items-center gap-2 rounded-lg px-3 py-2 text-sm outline-none transition-colors',
                      !isSelected && 'text-foreground hover:bg-accent',
                      isSelected && 'bg-primary/10 text-primary'
                    )}
                  >
                    <Check
                      className={cn('h-4 w-4 shrink-0', isSelected ? 'opacity-100' : 'opacity-0')}
                    />
                    <span className="flex items-center gap-2 flex-1 text-left truncate">
                      {option.image && (
                        <img
                          src={option.image}
                          alt=""
                          className="w-5 h-5 rounded-full object-cover shrink-0"
                        />
                      )}
                      <span className="truncate">{option.label}</span>
                    </span>
                  </button>
                )
              })
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  )

  return (
    <div ref={containerRef} className={cn('relative', className)}>
      <button
        ref={buttonRef}
        type="button"
        disabled={disabled}
        onClick={() => {
          setOpen(!open)
          if (!open) setSearch('')
        }}
        className={cn(
          'flex h-9 w-full items-center justify-between rounded-lg border border-input bg-input/80 px-3 py-1 text-sm shadow-sm transition-colors',
          'focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50',
          'disabled:cursor-not-allowed disabled:opacity-50 backdrop-blur-sm',
          open && 'ring-[3px] ring-ring/50',
          !value && 'text-muted-foreground',
          triggerClassName
        )}
      >
        <span className="flex items-center gap-2 truncate">
          {selectedOption?.image && (
            <img src={selectedOption.image} alt="" className="w-5 h-5 rounded-full object-cover" />
          )}
          <span className="truncate">{selectedOption?.label || placeholder}</span>
        </span>
        <ChevronDown
          className={cn(
            'h-4 w-4 shrink-0 text-muted-foreground transition-transform',
            open && 'rotate-180'
          )}
        />
      </button>

      {createPortal(panel, document.body)}
    </div>
  )
}
