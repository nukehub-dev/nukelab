import { useState, useEffect } from 'react'
import { Wallet } from 'lucide-react'
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
import { Label } from '../ui/label'
import { Button } from '../ui/button'
import { useCreditActions } from '../../hooks/use-credits'
import type { User } from '../../types/api'

interface DailyAllowanceDialogProps {
  user: User | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function DailyAllowanceDialog({ user, open, onOpenChange }: DailyAllowanceDialogProps) {
  const actions = useCreditActions()

  const [amount, setAmount] = useState('')
  const [amountError, setAmountError] = useState('')

  useEffect(() => {
    if (open && user) {
      setAmount(String(user.daily_allowance ?? 0))
      setAmountError('')
    }
  }, [open, user])

  const numericAmount = parseInt(amount, 10)
  const isValid = !Number.isNaN(numericAmount) && numericAmount >= 0
  const isUnchanged = user?.daily_allowance === numericAmount
  const isBusy = actions.updateUserDailyAllowance.isPending

  const handleOpenChange = (open: boolean) => {
    if (!open) {
      setAmountError('')
    }
    onOpenChange(open)
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!user) return

    if (!isValid) {
      setAmountError('Enter a valid non-negative integer')
      return
    }
    if (isUnchanged) {
      handleOpenChange(false)
      return
    }

    actions.updateUserDailyAllowance.mutate(
      { userId: user.id, amount: numericAmount },
      { onSuccess: () => handleOpenChange(false) }
    )
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Wallet className="w-5 h-5 text-primary" />
            Daily Allowance
          </DialogTitle>
          <DialogDescription>
            {user ? (
              <>
                Set the daily credit allowance for{' '}
                <span className="font-medium text-foreground">{user.username}</span>
              </>
            ) : (
              'Select a user'
            )}
          </DialogDescription>
        </DialogHeader>

        <form id="daily-allowance-form" onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div className="space-y-2">
            <Label>Amount (NUKE / day)</Label>
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
            <p className="text-xs text-muted-foreground">
              Users are granted this allowance once per day. Set to 0 to disable.
            </p>
          </div>
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
            form="daily-allowance-form"
            loading={isBusy}
            disabled={!isValid || isUnchanged}
          >
            Save
          </Button>
        </DialogFooter>
        <DialogClose onClick={() => handleOpenChange(false)} />
      </DialogContent>
    </Dialog>
  )
}
