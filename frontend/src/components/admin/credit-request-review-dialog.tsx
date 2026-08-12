// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useState } from 'react'
import { HandCoins, Check, X, Wallet, AlertTriangle } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from '../ui/dialog'
import { Input } from '../ui/input'
import { Button } from '../ui/button'
import { Label } from '../ui/label'
import { useReviewCreditRequest } from '../../hooks/use-credit-requests'
import { CreditRequestThread } from '../credit-request-thread'
import { cn, formatRelativeTime } from '../../lib/utils'
import type { CreditRequest } from '../../types/api'

type ReviewAction = 'approve' | 'reject'

interface CreditRequestReviewDialogProps {
  request: CreditRequest | null
  initialAction?: ReviewAction
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function CreditRequestReviewDialog({
  request,
  initialAction = 'approve',
  open,
  onOpenChange,
}: CreditRequestReviewDialogProps) {
  const { approveRequest, rejectRequest } = useReviewCreditRequest()

  // Dialog children unmount on close, so these initializers re-run on each open.
  const [action, setAction] = useState<ReviewAction>(initialAction)
  const [amount, setAmount] = useState(request ? String(request.amount) : '')
  const [note, setNote] = useState('')
  const [amountError, setAmountError] = useState('')

  const numericAmount = parseInt(amount, 10) || 0
  const isBusy = approveRequest.isPending || rejectRequest.isPending
  const isOpenRequest = request?.status === 'pending' || request?.status === 'needs_info'

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      setAmount('')
      setNote('')
      setAmountError('')
    }
    onOpenChange(open)
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!request) return

    if (action === 'approve') {
      if (!amount || numericAmount <= 0) {
        setAmountError('Enter a valid amount greater than 0')
        return
      }
      approveRequest.mutate(
        {
          requestId: request.id,
          amount: numericAmount,
          note: note.trim() || undefined,
        },
        { onSuccess: () => handleOpenChange(false) }
      )
    } else {
      rejectRequest.mutate(
        { requestId: request.id, note: note.trim() || undefined },
        { onSuccess: () => handleOpenChange(false) }
      )
    }
  }

  const actionOptions: {
    value: ReviewAction
    label: string
    icon: React.ElementType
    color: string
    activeBg: string
  }[] = [
    {
      value: 'approve',
      label: 'Approve',
      icon: Check,
      color: 'text-emerald-400',
      activeBg: 'bg-emerald-500/10 border-emerald-500/30',
    },
    {
      value: 'reject',
      label: 'Reject',
      icon: X,
      color: 'text-red-400',
      activeBg: 'bg-red-500/10 border-red-500/30',
    },
  ]

  return (
    <Dialog open={open} onOpenChange={handleOpenChange} size="lg">
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <HandCoins className="w-5 h-5 text-primary" />
            Review Credit Request
          </DialogTitle>
          <DialogDescription>
            {request ? (
              <>
                <span className="font-medium text-foreground">
                  {request.username || request.user_id}
                </span>{' '}
                requested {request.amount.toLocaleString()} NUKE ·{' '}
                {formatRelativeTime(request.created_at)}
              </>
            ) : (
              'Select a request to review'
            )}
          </DialogDescription>
        </DialogHeader>

        {request && (
          <div className="mt-4 space-y-5">
            {/* Request details */}
            <div className="p-4 rounded-xl bg-muted/40 border border-border/50 space-y-1.5">
              <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
                Reason
              </p>
              <p className="text-sm whitespace-pre-wrap break-words">{request.reason}</p>
            </div>

            {/* Conversation thread */}
            <CreditRequestThread
              requestId={request.id}
              canReply={isOpenRequest}
              replyHint="Replying sets the request to awaiting user reply."
              replyPlaceholder="Ask the user for more details…"
            />

            {isOpenRequest && (
              <form
                id="credit-request-review-form"
                onSubmit={handleSubmit}
                className="space-y-5 border-t border-border/50 pt-4"
              >
                {/* Action Toggle */}
                <div className="flex gap-2 p-1 bg-muted rounded-xl">
                  {actionOptions.map((op) => (
                    <button
                      key={op.value}
                      type="button"
                      onClick={() => setAction(op.value)}
                      className={cn(
                        'flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all',
                        action === op.value
                          ? `${op.activeBg} ${op.color} shadow-sm`
                          : 'text-muted-foreground hover:text-foreground'
                      )}
                    >
                      <op.icon className="w-4 h-4" />
                      {op.label}
                    </button>
                  ))}
                </div>

                {/* Amount (approve only) */}
                {action === 'approve' && (
                  <div className="space-y-2">
                    <Label>Amount to Grant</Label>
                    <div className="relative">
                      <Wallet className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                      <Input
                        type="number"
                        min={1}
                        value={amount}
                        onChange={(e) => {
                          setAmount(e.target.value)
                          if (amountError) setAmountError('')
                        }}
                        placeholder="0"
                        className="pl-10"
                        disabled={isBusy}
                      />
                    </div>
                    {amountError && <p className="text-xs text-destructive">{amountError}</p>}
                    <p className="text-xs text-muted-foreground">
                      Prefilled with the requested amount; adjust to grant a different amount.
                    </p>
                  </div>
                )}

                {/* Note */}
                <div className="space-y-2">
                  <Label>
                    {action === 'approve' ? 'Note (optional)' : 'Rejection note (optional)'}
                  </Label>
                  <Input
                    type="text"
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                    placeholder={
                      action === 'approve'
                        ? 'e.g., Approved for the weekend batch job'
                        : 'e.g., Not enough justification'
                    }
                    disabled={isBusy}
                  />
                  <p className="text-xs text-muted-foreground">
                    Shown to the user with the decision.
                  </p>
                </div>

                {action === 'reject' && (
                  <div className="flex items-start gap-2 p-3 rounded-lg bg-amber-500/10 text-amber-400 text-xs">
                    <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                    <span>
                      Rejecting notifies the user and frees them to submit a new request. No credits
                      are granted.
                    </span>
                  </div>
                )}
              </form>
            )}
          </div>
        )}

        <DialogFooter>
          <Button
            variant="outline"
            type="button"
            onClick={() => handleOpenChange(false)}
            disabled={isBusy}
          >
            Cancel
          </Button>
          {isOpenRequest && (
            <Button
              type="submit"
              form="credit-request-review-form"
              loading={isBusy}
              variant={action === 'reject' ? 'destructive' : 'default'}
            >
              {action === 'approve' ? 'Approve Request' : 'Reject Request'}
            </Button>
          )}
        </DialogFooter>
        <DialogClose onClick={() => handleOpenChange(false)} />
      </DialogContent>
    </Dialog>
  )
}
