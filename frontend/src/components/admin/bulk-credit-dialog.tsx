// SPDX-FileCopyrightText: 2023-2026 NukeHub Developers
// SPDX-License-Identifier: BSD-2-Clause

import { useState } from 'react'
import { Users, CheckCircle2, XCircle, AlertTriangle } from 'lucide-react'
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
import { useBulkCreditActions } from '../../hooks/use-credits'

type BulkMode = 'grant' | 'allowance'

interface BulkCreditDialogProps {
  mode: BulkMode
  userIds: string[]
  open: boolean
  onOpenChange: (open: boolean) => void
}

interface ResultItem {
  user_id: string
  error?: string
  granted_amount?: number
  new_balance?: number
  capped?: boolean
  daily_allowance?: number
}

export function BulkCreditDialog({ mode, userIds, open, onOpenChange }: BulkCreditDialogProps) {
  const { bulkGrantCredits, bulkSetAllowance } = useBulkCreditActions()

  const [amount, setAmount] = useState('')
  const [reason, setReason] = useState('')
  const [amountError, setAmountError] = useState('')
  const [reasonError, setReasonError] = useState('')

  const numericAmount = parseInt(amount, 10)
  const isValid = !Number.isNaN(numericAmount) && numericAmount >= 0
  const isBusy = mode === 'grant' ? bulkGrantCredits.isPending : bulkSetAllowance.isPending

  const reset = () => {
    setAmount('')
    setReason('')
    setAmountError('')
    setReasonError('')
  }

  const handleOpenChange = (open: boolean) => {
    if (!open) reset()
    onOpenChange(open)
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (userIds.length === 0) return

    if (!isValid) {
      setAmountError('Enter a valid non-negative integer')
      return
    }

    if (mode === 'grant' && !reason.trim()) {
      setReasonError('Reason is required for bulk grants')
      return
    }
    setReasonError('')
    if (mode === 'grant') {
      bulkGrantCredits.mutate(
        { userIds, amount: numericAmount, reason: reason.trim() },
        { onSuccess: () => handleOpenChange(false) }
      )
    } else {
      bulkSetAllowance.mutate(
        { userIds, amount: numericAmount },
        { onSuccess: () => handleOpenChange(false) }
      )
    }
  }

  const results = mode === 'grant' ? bulkGrantCredits.data?.results : bulkSetAllowance.data?.results
  const hasResults = results && (results.success.length > 0 || results.failed.length > 0)

  const title = mode === 'grant' ? 'Bulk Grant Credits' : 'Bulk Set Daily Allowance'
  const description =
    mode === 'grant'
      ? `Grant credits to ${userIds.length} selected user${userIds.length === 1 ? '' : 's'}.`
      : `Set the daily allowance for ${userIds.length} selected user${userIds.length === 1 ? '' : 's'}.`
  const submitLabel = mode === 'grant' ? 'Grant to All' : 'Set for All'

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Users className="w-5 h-5 text-primary" />
            {title}
          </DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>

        <form id="bulk-credit-form" onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div className="space-y-2">
            <Label>
              {mode === 'grant' ? 'Amount per user (NUKE)' : 'Daily allowance (NUKE / day)'}
            </Label>
            <Input
              type="number"
              min={0}
              step={1}
              value={amount}
              onChange={(e) => {
                setAmount(e.target.value)
                if (amountError) setAmountError('')
              }}
              placeholder="0"
              disabled={isBusy}
              autoFocus
            />
            {amountError && <p className="text-xs text-destructive">{amountError}</p>}
          </div>

          {mode === 'grant' && (
            <div className="space-y-2">
              <Label>Reason</Label>
              <Input
                type="text"
                value={reason}
                onChange={(e) => {
                  setReason(e.target.value)
                  if (reasonError) setReasonError('')
                }}
                placeholder="e.g., Beta bonus, Promo campaign"
                disabled={isBusy}
              />
              {reasonError && <p className="text-xs text-destructive">{reasonError}</p>}
              <p className="text-xs text-muted-foreground">
                This reason is recorded in each user&apos;s transaction audit log.
              </p>
            </div>
          )}

          {hasResults && (
            <div className="space-y-2 max-h-48 overflow-auto p-3 rounded-xl bg-muted/30 border border-border/30">
              {results.success.map((item: ResultItem) => (
                <div
                  key={item.user_id}
                  className="flex items-center gap-2 text-xs text-emerald-400"
                >
                  <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
                  <span className="font-mono truncate">{item.user_id.slice(0, 8)}</span>
                  {mode === 'grant' ? (
                    <span className="ml-auto">
                      +{item.granted_amount}
                      {item.capped && <span className="text-amber-400 ml-1">(capped)</span>}
                    </span>
                  ) : (
                    <span className="ml-auto">{item.daily_allowance}/day</span>
                  )}
                </div>
              ))}
              {results.failed.map((item: ResultItem) => (
                <div key={item.user_id} className="flex items-start gap-2 text-xs text-destructive">
                  <XCircle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                  <span className="font-mono">{item.user_id.slice(0, 8)}</span>
                  <span className="ml-auto text-right truncate">{item.error}</span>
                </div>
              ))}
            </div>
          )}

          {hasResults && results.success.some((r) => r.capped) && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-amber-500/10 text-amber-400 text-xs">
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>
                Some grants were capped by the system max-balance limit. The actual credited amount
                may be less than requested.
              </span>
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
            form="bulk-credit-form"
            loading={isBusy}
            disabled={userIds.length === 0 || !isValid}
          >
            {submitLabel} ({userIds.length})
          </Button>
        </DialogFooter>
        <DialogClose onClick={() => handleOpenChange(false)} />
      </DialogContent>
    </Dialog>
  )
}
