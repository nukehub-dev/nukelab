// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { HandCoins } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from './ui/dialog'
import { Button } from './ui/button'
import { CreditRequestThread } from './credit-request-thread'
import { cn, formatRelativeTime } from '../lib/utils'
import type { CreditRequest } from '../types/api'

const STATUS_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  pending: { label: 'Pending', color: 'text-amber-400', bg: 'bg-amber-500/10' },
  needs_info: { label: 'Awaiting your reply', color: 'text-blue-400', bg: 'bg-blue-500/10' },
  approved: { label: 'Approved', color: 'text-emerald-400', bg: 'bg-emerald-500/10' },
  rejected: { label: 'Rejected', color: 'text-red-400', bg: 'bg-red-500/10' },
  cancelled: { label: 'Cancelled', color: 'text-muted-foreground', bg: 'bg-muted' },
}

interface CreditRequestThreadDialogProps {
  request: CreditRequest | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function CreditRequestThreadDialog({
  request,
  open,
  onOpenChange,
}: CreditRequestThreadDialogProps) {
  const isOpen = request?.status === 'pending' || request?.status === 'needs_info'
  const config = request ? STATUS_CONFIG[request.status] : undefined

  return (
    <Dialog open={open} onOpenChange={onOpenChange} size="lg">
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <HandCoins className="w-5 h-5 text-primary" />
            Credit Request
            {config && (
              <span
                className={cn(
                  'text-[10px] px-1.5 py-0.5 rounded-full font-medium',
                  config.bg,
                  config.color
                )}
              >
                {config.label}
              </span>
            )}
          </DialogTitle>
          <DialogDescription>
            {request ? (
              <>
                {request.amount.toLocaleString()} NUKE · requested{' '}
                {formatRelativeTime(request.created_at)}
                {request.status === 'approved' &&
                  request.granted_amount !== null &&
                  ` · granted ${request.granted_amount.toLocaleString()} NUKE`}
              </>
            ) : (
              'Select a request to view'
            )}
          </DialogDescription>
        </DialogHeader>

        {request && (
          <div className="mt-4 space-y-5">
            {/* Request details */}
            <div className="p-4 rounded-xl bg-muted/40 border border-border/50 space-y-1.5">
              <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Your reason
              </p>
              <p className="text-sm whitespace-pre-wrap break-words">{request.reason}</p>
              {request.review_note && (
                <p className="text-xs text-muted-foreground pt-1">
                  <span className="font-medium text-foreground">Admin note:</span>{' '}
                  {request.review_note}
                </p>
              )}
            </div>

            <CreditRequestThread
              requestId={request.id}
              canReply={isOpen}
              replyHint="Replying returns your request to pending review."
              replyPlaceholder="Reply to the admin…"
            />
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" type="button" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
        <DialogClose onClick={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  )
}
