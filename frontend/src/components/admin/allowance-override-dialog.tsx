import { useState, useMemo, useEffect } from 'react'
import { Clock, Zap, AlertTriangle } from 'lucide-react'
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
import { useAllowanceOverride } from '../../hooks/use-credits'
import type { User } from '../../types/api'

interface AllowanceOverrideDialogProps {
  user: User | null
  open: boolean
  onOpenChange: (open: boolean) => void
}

// Preset windows expressed in hours from now
const PRESET_WINDOWS = [
  { label: '24 hours', hours: 24 },
  { label: '3 days', hours: 24 * 3 },
  { label: '7 days', hours: 24 * 7 },
  { label: '14 days', hours: 24 * 14 },
  { label: '30 days', hours: 24 * 30 },
]

export function AllowanceOverrideDialog({
  user,
  open,
  onOpenChange,
}: AllowanceOverrideDialogProps) {
  const { setOverride, clearOverride } = useAllowanceOverride()

  const [amount, setAmount] = useState('')
  const [presetHours, setPresetHours] = useState<number>(24)
  const [amountError, setAmountError] = useState('')

  useEffect(() => {
    if (open && user) {
      const base = user.daily_allowance_override ?? user.daily_allowance ?? 0
      setAmount(String(base))
      setPresetHours(24)
      setAmountError('')
    }
  }, [open, user])

  const numericAmount = parseInt(amount, 10)
  const isValid = !Number.isNaN(numericAmount) && numericAmount >= 0
  const isBusy = setOverride.isPending

  const expiryIso = useMemo(() => {
    const d = new Date()
    d.setHours(d.getHours() + presetHours)
    return d.toISOString()
  }, [presetHours])

  const expiryLabel = useMemo(() => new Date(expiryIso).toLocaleString(), [expiryIso])

  const hasActiveOverride = user?.has_active_allowance_override ?? false

  const handleOpenChange = (open: boolean) => {
    if (!open) setAmountError('')
    onOpenChange(open)
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!user) return
    if (!isValid) {
      setAmountError('Enter a valid non-negative integer')
      return
    }
    setOverride.mutate(
      { userId: user.id, amount: numericAmount, until: expiryIso },
      { onSuccess: () => handleOpenChange(false) }
    )
  }

  const handleClear = () => {
    if (!user) return
    clearOverride.mutate(user.id, {
      onSuccess: () => handleOpenChange(false),
    })
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Zap className="w-5 h-5 text-amber-400" />
            Daily Allowance Override
          </DialogTitle>
          <DialogDescription>
            {user ? (
              <>
                Temporarily boost{' '}
                <span className="font-medium text-foreground">{user.username}</span>
                &apos;s daily allowance.
              </>
            ) : (
              'Select a user'
            )}
          </DialogDescription>
        </DialogHeader>

        <form id="allowance-override-form" onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div className="space-y-2">
            <label className="text-sm font-medium">Override amount (NUKE / day)</label>
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
              Base allowance: <span className="font-mono">{user?.daily_allowance ?? 0}</span>{' '}
              NUKE/day
            </p>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-medium flex items-center gap-1.5">
              <Clock className="w-3.5 h-3.5" />
              Duration
            </label>
            <div className="flex flex-wrap gap-2">
              {PRESET_WINDOWS.map((preset) => (
                <button
                  key={preset.hours}
                  type="button"
                  onClick={() => setPresetHours(preset.hours)}
                  disabled={isBusy}
                  className={
                    'px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ' +
                    (presetHours === preset.hours
                      ? 'bg-primary/10 border-primary/40 text-primary'
                      : 'border-border/40 text-muted-foreground hover:text-foreground')
                  }
                >
                  {preset.label}
                </button>
              ))}
            </div>
            <p className="text-xs text-muted-foreground">
              Expires: <span className="font-medium text-foreground">{expiryLabel}</span>
            </p>
          </div>

          {hasActiveOverride && (
            <div className="flex items-start gap-2 p-3 rounded-lg bg-amber-500/10 text-amber-400 text-xs">
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
              <div className="space-y-0.5">
                <p className="font-semibold">An override is already active</p>
                <p>
                  Saving will replace it. Use &quot;Clear override&quot; below to revert to the base
                  allowance immediately.
                </p>
              </div>
            </div>
          )}
        </form>

        <DialogFooter className="flex items-center justify-between sm:justify-between gap-2">
          <Button
            variant="ghost"
            type="button"
            onClick={handleClear}
            disabled={isBusy || clearOverride.isPending || !hasActiveOverride}
            className="text-destructive hover:text-destructive"
          >
            {clearOverride.isPending ? 'Clearing...' : 'Clear override'}
          </Button>
          <div className="flex items-center gap-2">
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
              form="allowance-override-form"
              loading={isBusy}
              disabled={!isValid}
            >
              Set Override
            </Button>
          </div>
        </DialogFooter>
        <DialogClose onClick={() => handleOpenChange(false)} />
      </DialogContent>
    </Dialog>
  )
}
