// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useState } from 'react'
import { HandCoins, Wallet, AlertTriangle, Clock } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from './ui/dialog'
import { Input } from './ui/input'
import { Textarea } from './ui/textarea'
import { Button } from './ui/button'
import { Label } from './ui/label'
import { useCreateCreditRequest } from '../hooks/use-credit-requests'
import { cn } from '../lib/utils'

const MAX_REASON_LENGTH = 2000

type RequestType = 'top_up' | 'allowance'

interface CreditRequestDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function CreditRequestDialog({ open, onOpenChange }: CreditRequestDialogProps) {
  const createRequest = useCreateCreditRequest()

  const [amount, setAmount] = useState('')
  const [reason, setReason] = useState('')
  const [requestType, setRequestType] = useState<RequestType>('top_up')
  const [amountError, setAmountError] = useState('')
  const [reasonError, setReasonError] = useState('')
  const [submitError, setSubmitError] = useState('')

  const numericAmount = parseInt(amount, 10) || 0
  const isBusy = createRequest.isPending

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      setAmount('')
      setReason('')
      setRequestType('top_up')
      setAmountError('')
      setReasonError('')
      setSubmitError('')
    }
    onOpenChange(open)
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()

    let hasError = false

    if (!amount || numericAmount <= 0) {
      setAmountError('Enter a valid amount greater than 0')
      hasError = true
    } else {
      setAmountError('')
    }

    if (!reason.trim()) {
      setReasonError('Reason is required')
      hasError = true
    } else if (reason.trim().length > MAX_REASON_LENGTH) {
      setReasonError(`Reason must be ${MAX_REASON_LENGTH} characters or fewer`)
      hasError = true
    } else {
      setReasonError('')
    }

    if (hasError) return

    createRequest.mutate(
      { amount: numericAmount, reason: reason.trim(), request_type: requestType },
      {
        onSuccess: () => handleOpenChange(false),
        onError: (err) => {
          setSubmitError(err instanceof Error ? err.message : 'Failed to submit credit request')
        },
      }
    )
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <HandCoins className="w-5 h-5 text-primary" />
            Request Credits
          </DialogTitle>
          <DialogDescription>
            Ask an admin for extra credits. You can only have one pending request at a time.
          </DialogDescription>
        </DialogHeader>

        <form id="credit-request-form" onSubmit={handleSubmit} className="mt-4 space-y-5">
          {/* Request Type Toggle */}
          <div className="flex gap-2 p-1 bg-muted rounded-xl">
            <button
              type="button"
              onClick={() => setRequestType('top_up')}
              className={cn(
                'flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all',
                requestType === 'top_up'
                  ? 'bg-primary/10 border-primary/30 text-primary shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              <HandCoins className="w-4 h-4" />
              One-time top-up
            </button>
            <button
              type="button"
              onClick={() => setRequestType('allowance')}
              className={cn(
                'flex-1 flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all',
                requestType === 'allowance'
                  ? 'bg-violet-500/10 border-violet-500/30 text-violet-400 shadow-sm'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              <Clock className="w-4 h-4" />
              Daily allowance
            </button>
          </div>

          {/* Amount */}
          <div className="space-y-2">
            <Label>{requestType === 'allowance' ? 'Daily allowance (NUKE/day)' : 'Amount'}</Label>
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
                data-testid="credit-request-amount"
              />
            </div>
            {amountError && <p className="text-xs text-destructive">{amountError}</p>}
            {requestType === 'allowance' && (
              <p className="text-xs text-muted-foreground">
                If approved, your daily allowance is set to this amount instead of a one-time grant.
              </p>
            )}
          </div>

          {/* Reason */}
          <div className="space-y-2">
            <Label>Reason</Label>
            <Textarea
              value={reason}
              onChange={(e) => {
                setReason(e.target.value)
                if (reasonError) setReasonError('')
              }}
              placeholder="Why do you need these credits? e.g., running a long simulation"
              maxLength={MAX_REASON_LENGTH}
              rows={4}
              disabled={isBusy}
              data-testid="credit-request-reason"
            />
            {reasonError && <p className="text-xs text-destructive">{reasonError}</p>}
            <p className="text-xs text-muted-foreground">
              {reason.length}/{MAX_REASON_LENGTH} characters
            </p>
          </div>

          {submitError && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-destructive/10 text-destructive text-xs">
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{submitError}</span>
            </div>
          )}
        </form>

        <DialogFooter>
          <Button
            variant="outline"
            type="button"
            onClick={() => handleOpenChange(false)}
            disabled={isBusy}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            form="credit-request-form"
            loading={isBusy}
            data-testid="credit-request-submit"
          >
            Submit Request
          </Button>
        </DialogFooter>
        <DialogClose onClick={() => handleOpenChange(false)} />
      </DialogContent>
    </Dialog>
  )
}
