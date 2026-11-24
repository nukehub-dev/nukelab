// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useEffect, useRef, useState } from 'react'
import { Check, Copy as CopyIcon } from 'lucide-react'
import { copyTextToClipboard } from '../../lib/environment-revisions'
import { cn } from '../../lib/utils'
import { Tooltip } from './tooltip'

const COPY_FEEDBACK_DURATION_MS = 1500

export interface CopyButtonProps {
  /** Full, untruncated value written to the clipboard. */
  value: string
  /** Accessible name describing what is copied. */
  label?: string
  className?: string
}

export function CopyButton({ value, label = 'Copy value', className }: CopyButtonProps) {
  const [copied, setCopied] = useState(false)
  const resetTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => {
      if (resetTimer.current) clearTimeout(resetTimer.current)
    }
  }, [])

  const handleCopy = async () => {
    if (!(await copyTextToClipboard(value))) return
    setCopied(true)
    if (resetTimer.current) clearTimeout(resetTimer.current)
    resetTimer.current = setTimeout(() => setCopied(false), COPY_FEEDBACK_DURATION_MS)
  }

  return (
    <CopyButtonView
      copied={copied}
      label={label}
      onCopy={() => void handleCopy()}
      className={className}
    />
  )
}

export interface CopyButtonViewProps {
  copied: boolean
  label: string
  onCopy: () => void
  className?: string
}

export function CopyButtonView({ copied, label, onCopy, className }: CopyButtonViewProps) {
  return (
    <Tooltip content="Copy">
      <button
        type="button"
        aria-label={copied ? 'Copied' : label}
        data-state={copied ? 'copied' : 'idle'}
        onClick={onCopy}
        className={cn(
          'inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors',
          'hover:bg-muted/60 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50',
          copied && 'text-emerald-400',
          className
        )}
      >
        {copied ? (
          <Check className="h-3.5 w-3.5" aria-hidden="true" />
        ) : (
          <CopyIcon className="h-3.5 w-3.5" aria-hidden="true" />
        )}
        <span className="sr-only" role="status" aria-live="polite">
          {copied ? 'Copied' : ''}
        </span>
      </button>
    </Tooltip>
  )
}
