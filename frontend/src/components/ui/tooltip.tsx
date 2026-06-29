// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useState, useRef, useCallback, useEffect, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { cn } from '../../lib/utils'

type TooltipPosition = 'top' | 'bottom' | 'left' | 'right'

interface TooltipProps {
  content: string
  children: ReactNode
  position?: TooltipPosition
  delay?: number
  className?: string
}

const GAP = 8
const VIEWPORT_PADDING = 8

function computePosition(
  triggerRect: DOMRect,
  tooltipRect: DOMRect,
  preferred: TooltipPosition
): { x: number; y: number; final: TooltipPosition } {
  const vw = window.innerWidth
  const vh = window.innerHeight

  const fits = {
    top: triggerRect.top - GAP - tooltipRect.height >= VIEWPORT_PADDING,
    bottom: triggerRect.bottom + GAP + tooltipRect.height <= vh - VIEWPORT_PADDING,
    left: triggerRect.left - GAP - tooltipRect.width >= VIEWPORT_PADDING,
    right: triggerRect.right + GAP + tooltipRect.width <= vw - VIEWPORT_PADDING,
  }

  // Choose best position: preferred if it fits, otherwise flip
  let pos = preferred
  if (!fits[preferred]) {
    const flip: Record<TooltipPosition, TooltipPosition> = {
      top: 'bottom',
      bottom: 'top',
      left: 'right',
      right: 'left',
    }
    pos = fits[flip[preferred]]
      ? flip[preferred]
      : fits.bottom
        ? 'bottom'
        : fits.top
          ? 'top'
          : 'bottom'
  }

  let x = 0
  let y = 0

  switch (pos) {
    case 'top':
      x = triggerRect.left + triggerRect.width / 2
      y = triggerRect.top - GAP
      break
    case 'bottom':
      x = triggerRect.left + triggerRect.width / 2
      y = triggerRect.bottom + GAP
      break
    case 'left':
      x = triggerRect.left - GAP
      y = triggerRect.top + triggerRect.height / 2
      break
    case 'right':
      x = triggerRect.right + GAP
      y = triggerRect.top + triggerRect.height / 2
      break
  }

  // Clamp to viewport
  if (pos === 'top' || pos === 'bottom') {
    x = Math.max(
      VIEWPORT_PADDING + tooltipRect.width / 2,
      Math.min(vw - VIEWPORT_PADDING - tooltipRect.width / 2, x)
    )
  } else {
    y = Math.max(
      VIEWPORT_PADDING + tooltipRect.height / 2,
      Math.min(vh - VIEWPORT_PADDING - tooltipRect.height / 2, y)
    )
  }

  return { x, y, final: pos }
}

export function Tooltip({
  content,
  children,
  position = 'top',
  delay = 300,
  className,
}: TooltipProps) {
  const [visible, setVisible] = useState(false)
  const [positioned, setPositioned] = useState(false)
  const [coords, setCoords] = useState({ x: 0, y: 0 })
  const [actualPos, setActualPos] = useState<TooltipPosition>(position)
  const childRef = useRef<HTMLSpanElement>(null)
  const tooltipRef = useRef<HTMLDivElement>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const updatePosition = useCallback(() => {
    const child = childRef.current
    const tooltip = tooltipRef.current
    if (!child || !tooltip) return

    const childRect = child.getBoundingClientRect()
    const tooltipRect = tooltip.getBoundingClientRect()
    const { x, y, final } = computePosition(childRect, tooltipRect, position)

    setCoords({ x, y })
    setActualPos(final)
    setPositioned(true)
  }, [position])

  const show = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => {
      setPositioned(false)
      setVisible(true)
      // Position after render so we can measure tooltip size
      requestAnimationFrame(() => {
        requestAnimationFrame(updatePosition)
      })
    }, delay)
  }, [delay, updatePosition])

  const hide = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current)
    setVisible(false)
    setPositioned(false)
  }, [])

  useEffect(() => {
    if (!visible) return
    const handleScroll = () => updatePosition()
    window.addEventListener('scroll', handleScroll, true)
    window.addEventListener('resize', handleScroll)
    return () => {
      window.removeEventListener('scroll', handleScroll, true)
      window.removeEventListener('resize', handleScroll)
    }
  }, [visible, updatePosition])

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current)
    }
  }, [])

  const transform =
    actualPos === 'top'
      ? 'translate(-50%, -100%)'
      : actualPos === 'bottom'
        ? 'translate(-50%, 0)'
        : actualPos === 'left'
          ? 'translate(-100%, -50%)'
          : 'translate(0, -50%)'

  return (
    <>
      <span
        ref={childRef}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
        className="inline-flex"
      >
        {children}
      </span>
      {visible &&
        createPortal(
          <div
            ref={tooltipRef}
            className={cn(
              'px-2.5 py-1.5 rounded-md text-xs font-medium shadow-xl pointer-events-none z-[99999]',
              'bg-popover text-popover-foreground border border-border/80',
              className
            )}
            style={{
              position: 'fixed',
              left: coords.x,
              top: coords.y,
              transform,
              opacity: positioned ? 1 : 0,
              transition: 'opacity 0.1s ease',
            }}
          >
            {content}
          </div>,
          document.body
        )}
    </>
  )
}

export function IconButtonTooltip({
  content,
  children,
  position = 'top',
}: {
  content: string
  children: ReactNode
  position?: TooltipPosition
}) {
  return (
    <Tooltip content={content} position={position}>
      {children}
    </Tooltip>
  )
}
