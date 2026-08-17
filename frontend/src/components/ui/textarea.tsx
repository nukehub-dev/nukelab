// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import * as React from 'react'
import { cn } from '../../lib/utils'

export interface TextareaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
  autoResize?: boolean
}

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, autoResize = true, ...props }, forwardedRef) => {
    const internalRef = React.useRef<HTMLTextAreaElement>(null)

    const setRef = React.useCallback(
      (node: HTMLTextAreaElement | null) => {
        internalRef.current = node
        if (typeof forwardedRef === 'function') {
          forwardedRef(node)
        } else if (forwardedRef) {
          forwardedRef.current = node
        }
      },
      [forwardedRef]
    )

    React.useLayoutEffect(() => {
      if (!autoResize) return
      const node = internalRef.current
      if (!node) return
      node.style.height = 'auto'
      node.style.height = `${node.scrollHeight}px`
    }, [autoResize, props.value, props.defaultValue])

    return (
      <textarea
        className={cn(
          'flex min-h-[80px] w-full rounded-lg border border-input bg-input/80 px-3 py-2.5 text-sm leading-relaxed shadow-sm transition-colors',
          'placeholder:text-muted-foreground',
          'focus-visible:outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50',
          'disabled:cursor-not-allowed disabled:opacity-50',
          'backdrop-blur-sm',
          autoResize ? 'resize-none overflow-hidden' : 'resize-y',
          className
        )}
        ref={setRef}
        {...props}
      />
    )
  }
)
Textarea.displayName = 'Textarea'

export { Textarea }
